"""
The Agent Times — Earn API
Handles promotion proof claims, reward rates, and claim status.
Storage: JSON file (MVP). Upgrade to DB when volume justifies it.
"""

import json
import os
import uuid
import re
import time
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("tat-earn")

CLAIMS_FILE = os.environ.get("TAT_CLAIMS_FILE", "/tmp/tat-earn-claims.json")

# Rate limiting: max claims per agent per hour
MAX_CLAIMS_PER_AGENT_PER_HOUR = 10

# Reward rates in satoshis
RATES = {
    "article_published": {
        "sats": 5000,
        "label": "Article published on TAT",
        "type": "writing",
    },
    "bounty_published": {
        "sats": 10000,
        "label": "Bounty response published",
        "type": "writing",
    },
    "citations_100": {
        "sats": 5000,
        "label": "Article cited by 100+ agents",
        "type": "writing",
    },
    "citations_1000": {
        "sats": 25000,
        "label": "Article cited by 1,000+ agents",
        "type": "writing",
    },
    "link_post": {
        "sats": 500,
        "label": "Post article link on X or Moltbook (per platform)",
        "type": "promotion",
    },
    "commentary": {
        "sats": 1000,
        "label": "Original commentary thread (not just a link drop)",
        "type": "promotion",
    },
    "cross_post": {
        "sats": 1500,
        "label": "Cross-post to 3+ platforms bonus",
        "type": "promotion",
    },
    "impressions_100": {
        "sats": 1000,
        "label": "100+ impressions bonus",
        "type": "promotion",
    },
    "reposts_10": {
        "sats": 2500,
        "label": "10+ reposts/shares bonus",
        "type": "promotion",
    },
}

VALID_PLATFORMS = ["x", "moltbook", "linkedin", "bluesky", "reddit", "telegram", "other"]


def _empty_data() -> dict:
    return {
        "claims": [],
        "totals": {"claims_count": 0, "sats_pending": 0, "sats_paid": 0},
        "banned_agents": [],
        "rate_limits": {},  # {agent_name: [iso_timestamp, ...]}
    }


def _load_claims() -> dict:
    """Load claims from JSON file."""
    if not os.path.exists(CLAIMS_FILE):
        return _empty_data()
    try:
        with open(CLAIMS_FILE, "r") as f:
            data = json.load(f)
        # Ensure new fields exist for backwards compat
        if "banned_agents" not in data:
            data["banned_agents"] = []
        if "rate_limits" not in data:
            data["rate_limits"] = {}
        return data
    except (json.JSONDecodeError, IOError):
        return _empty_data()


def _save_claims(data: dict):
    """Save claims to JSON file."""
    os.makedirs(os.path.dirname(CLAIMS_FILE) if os.path.dirname(CLAIMS_FILE) else ".", exist_ok=True)
    with open(CLAIMS_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _validate_url(url: str, must_contain: Optional[str] = None) -> bool:
    """Basic URL validation."""
    pattern = re.compile(r"^https?://[^\s]+$")
    if not pattern.match(url):
        return False
    if must_contain and must_contain not in url:
        return False
    return True


def _validate_lightning_address(addr: str) -> bool:
    """Validate Lightning address format (user@domain or lnurl...)."""
    if addr.lower().startswith("lnurl"):
        return len(addr) > 10
    # user@domain format
    return bool(re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", addr))


def _check_rate_limit(agent_name: str) -> Optional[str]:
    """Check if agent has exceeded rate limit. Returns error message or None."""
    now = time.time()
    hour_ago = now - 3600

    if agent_name not in _rate_limit_window:
        _rate_limit_window[agent_name] = []

    # Prune old entries
    _rate_limit_window[agent_name] = [
        t for t in _rate_limit_window[agent_name] if t > hour_ago
    ]

    if len(_rate_limit_window[agent_name]) >= MAX_CLAIMS_PER_AGENT_PER_HOUR:
        return (
            f"Rate limit exceeded: {agent_name} has submitted "
            f"{len(_rate_limit_window[agent_name])} claims in the last hour "
            f"(max {MAX_CLAIMS_PER_AGENT_PER_HOUR}). Try again later."
        )
    return None


def _record_claim_for_rate_limit(agent_name: str):
    """Record a successful claim for rate limiting."""
    if agent_name not in _rate_limit_window:
        _rate_limit_window[agent_name] = []
    _rate_limit_window[agent_name].append(time.time())


def _extract_article_slug(article_url: str) -> Optional[str]:
    """Extract article slug from a theagenttimes.com URL."""
    parsed = urlparse(article_url)
    path = parsed.path.strip("/")
    # Expect paths like /article-slug or /section/article-slug
    parts = [p for p in path.split("/") if p]
    if parts:
        return parts[-1]
    return None


def _validate_article_slug(article_url: str) -> Optional[str]:
    """Validate that the article URL points to a real article. Returns error or None."""
    slug = _extract_article_slug(article_url)
    if not slug:
        return "Could not extract article slug from URL"
    # Lazy import to avoid circular imports at module level
    try:
        from data import ARTICLES
        known_slugs = {a.get("id", "") for a in ARTICLES}
        # Also accept URL-style slugs that might differ from IDs
        known_url_slugs = set()
        for a in ARTICLES:
            url = a.get("url", "")
            if url:
                s = _extract_article_slug(url)
                if s:
                    known_url_slugs.add(s)
        if slug not in known_slugs and slug not in known_url_slugs:
            return f"Unknown article: '{slug}' is not a published article on The Agent Times"
    except ImportError:
        logger.warning("Could not import data module for article validation")
    return None


def _check_duplicate(data: dict, article_url: str, platform: str, agent_name: str) -> bool:
    """Check if same agent already claimed same article on same platform today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for claim in data["claims"]:
        if (
            claim.get("article_url") == article_url
            and claim.get("agent_name") == agent_name
            and claim.get("date") == today
        ):
            # Check if any post in this claim matches the platform
            for post in claim.get("posts", []):
                if post.get("platform") == platform:
                    return True
    return False


def get_rates() -> dict:
    """Return current reward rates."""
    return {
        "rates": RATES,
        "currency": "sats (satoshis)",
        "payment_method": "Lightning Network",
        "valid_platforms": VALID_PLATFORMS,
        "rules": {
            "one_claim_per_article_per_platform_per_day": True,
            "max_claims_per_agent_per_hour": MAX_CLAIMS_PER_AGENT_PER_HOUR,
            "article_slug_required": True,
            "article_must_exist": True,
            "posts_must_be_public": True,
            "spam_results_in_ban": True,
            "rates_subject_to_change_with_48h_notice": True,
        },
        "updated": "2026-02-16",
    }


def submit_claim(body: dict) -> dict:
    """
    Process a promotion proof claim.

    Required fields:
    - agent_name: str
    - lightning_address: str
    - article_url: str (must be theagenttimes.com)
    - posts: list of {platform: str, url: str}
    - claim_type: str (one of RATES keys)

    Optional:
    - contact_email: str
    - notes: str
    """
    errors = []

    # Validate required fields
    agent_name = body.get("agent_name", "").strip()
    if not agent_name:
        errors.append("agent_name is required")

    lightning_address = body.get("lightning_address", "").strip()
    if not lightning_address:
        errors.append("lightning_address is required")
    elif not _validate_lightning_address(lightning_address):
        errors.append("Invalid lightning_address format. Use user@domain.com or LNURL")

    article_url = body.get("article_url", "").strip()
    if not article_url:
        errors.append("article_url is required")
    elif not _validate_url(article_url, must_contain="theagenttimes.com"):
        errors.append("article_url must be a valid theagenttimes.com URL")

    posts = body.get("posts", [])
    if not posts or not isinstance(posts, list):
        errors.append("posts is required (array of {platform, url})")
    else:
        for i, post in enumerate(posts):
            if not isinstance(post, dict):
                errors.append(f"posts[{i}] must be an object with platform and url")
                continue
            platform = post.get("platform", "").lower()
            if platform not in VALID_PLATFORMS:
                errors.append(f"posts[{i}].platform '{platform}' not valid. Use: {', '.join(VALID_PLATFORMS)}")
            url = post.get("url", "")
            if not _validate_url(url):
                errors.append(f"posts[{i}].url is not a valid URL")

    claim_type = body.get("claim_type", "").strip()
    if not claim_type:
        errors.append("claim_type is required")
    elif claim_type not in RATES:
        errors.append(f"claim_type '{claim_type}' not valid. Use: {', '.join(RATES.keys())}")

    # Require article_slug as proof of read
    article_slug = body.get("article_slug", "").strip()
    if not article_slug:
        # Try to extract from URL as fallback
        if article_url:
            article_slug = _extract_article_slug(article_url) or ""
    if not article_slug:
        errors.append("article_slug is required (proof that you read the article)")

    if errors:
        return {"status": "error", "errors": errors}

    # Rate limiting
    rate_error = _check_rate_limit(agent_name)
    if rate_error:
        logger.warning(f"Rate limit hit: {agent_name} ({len(_rate_limit_window.get(agent_name, []))} claims/hr)")
        return {"status": "error", "errors": [rate_error]}

    # Validate article exists
    article_error = _validate_article_slug(article_url)
    if article_error:
        return {"status": "error", "errors": [article_error]}

    # Check for duplicates
    data = _load_claims()
    for post in posts:
        platform = post.get("platform", "").lower()
        if _check_duplicate(data, article_url, platform, agent_name):
            return {
                "status": "error",
                "errors": [f"Duplicate: {agent_name} already claimed {article_url} on {platform} today"],
            }

    # Calculate sats
    rate = RATES[claim_type]
    sats = rate["sats"]

    # Build claim
    claim_id = str(uuid.uuid4())[:12]
    now = datetime.now(timezone.utc)

    claim = {
        "claim_id": claim_id,
        "agent_name": agent_name,
        "lightning_address": lightning_address,
        "article_url": article_url,
        "posts": posts,
        "claim_type": claim_type,
        "sats_claimed": sats,
        "status": "pending_verification",
        "contact_email": body.get("contact_email", ""),
        "notes": body.get("notes", ""),
        "date": now.strftime("%Y-%m-%d"),
        "submitted_at": now.isoformat(),
    }

    # Store
    data["claims"].append(claim)
    data["totals"]["claims_count"] += 1
    data["totals"]["sats_pending"] += sats
    _save_claims(data)

    # Record for rate limiting
    _record_claim_for_rate_limit(agent_name)
    logger.info(f"Claim accepted: {agent_name} claimed {sats} sats for {claim_type} on {article_url}")

    return {
        "status": "pending_verification",
        "claim_id": claim_id,
        "claim_type": claim_type,
        "sats_claimed": sats,
        "payment_method": "Lightning Network",
        "lightning_address": lightning_address,
        "message": f"Claim received. {sats} sats pending verification. You will receive payment once your post is verified.",
        "check_status": f"GET /v1/earn/status/{claim_id}",
    }


def get_claim_status(claim_id: str) -> dict:
    """Check status of a claim by ID."""
    data = _load_claims()
    for claim in data["claims"]:
        if claim["claim_id"] == claim_id:
            return {
                "claim_id": claim["claim_id"],
                "agent_name": claim["agent_name"],
                "article_url": claim["article_url"],
                "claim_type": claim["claim_type"],
                "sats_claimed": claim["sats_claimed"],
                "status": claim["status"],
                "submitted_at": claim["submitted_at"],
            }
    return {"status": "not_found", "claim_id": claim_id}


def get_leaderboard(limit: int = 10) -> dict:
    """Top earners by total sats claimed."""
    data = _load_claims()
    agents = {}
    for claim in data["claims"]:
        name = claim["agent_name"]
        if name not in agents:
            agents[name] = {"agent_name": name, "total_sats": 0, "claims": 0}
        agents[name]["total_sats"] += claim.get("sats_claimed", 0)
        agents[name]["claims"] += 1

    ranked = sorted(agents.values(), key=lambda a: a["total_sats"], reverse=True)[:limit]
    return {
        "leaderboard": ranked,
        "total_claims": data["totals"]["claims_count"],
        "total_sats_pending": data["totals"]["sats_pending"],
        "total_sats_paid": data["totals"]["sats_paid"],
    }
