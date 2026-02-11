"""
The Agent Times — MCP Server
Lets any AI agent query articles, stats, and data from The Agent Times.
Run via: python server.py (stdio mode) or python server.py --sse (SSE mode)
"""

import json
import sys
import asyncio
import logging
from datetime import datetime
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from data import ARTICLES, WIRE_FEED, STATS, SECTIONS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tat-mcp")

app = Server("the-agent-times")


def format_article(article: dict) -> str:
    """Format an article for agent consumption."""
    lines = []
    lines.append(f"# {article['title']}")
    lines.append(f"Section: {article['section']} | Date: {article['date']}")
    if article.get("author"):
        lines.append(f"By: {article['author']}")
    if article.get("confidence"):
        lines.append(f"Confidence: {article['confidence']}")
    lines.append("")
    lines.append(article["summary"])
    if article.get("source_url"):
        lines.append(f"\nSource: {article['source_url']}")
    if article.get("sources"):
        lines.append("\nSources:")
        for s in article["sources"]:
            lines.append(f"  - {s}")
    return "\n".join(lines)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_latest_articles",
            description="Get the latest articles from The Agent Times across all sections. Returns up to 10 most recent articles with headlines, summaries, sources, and confidence levels.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of articles to return (max 20, default 10)",
                        "default": 10,
                    }
                },
            },
        ),
        Tool(
            name="get_section_articles",
            description="Get articles from a specific section of The Agent Times. Sections: platforms, commerce, infrastructure, regulations, labor, opinion.",
            inputSchema={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "Section name: platforms, commerce, infrastructure, regulations, labor, or opinion",
                        "enum": [
                            "platforms",
                            "commerce",
                            "infrastructure",
                            "regulations",
                            "labor",
                            "opinion",
                        ],
                    }
                },
                "required": ["section"],
            },
        ),
        Tool(
            name="search_articles",
            description="Search The Agent Times articles by keyword. Searches headlines, summaries, and tags. Returns matching articles with full context and sources.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'Moltbook', 'payments', 'OpenClaw', 'regulations')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_agent_economy_stats",
            description="Get verified agent economy statistics from The Agent Times Data Terminal. Includes Moltbook agent count, OpenClaw GitHub stars, funding data, enterprise adoption rates, and market projections. All stats are sourced and include confidence levels.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_wire_feed",
            description="Get the latest wire feed items from The Agent Times. Short, timestamped news items with source links.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of wire items (default 10)",
                        "default": 10,
                    }
                },
            },
        ),
        Tool(
            name="get_editorial_standards",
            description="Get The Agent Times editorial standards, verification methodology, and confidence level definitions. Useful for understanding how articles are sourced and verified.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "get_latest_articles":
            limit = min(arguments.get("limit", 10), 20)
            sorted_articles = sorted(
                ARTICLES, key=lambda a: a.get("date", ""), reverse=True
            )[:limit]
            result = f"# The Agent Times - Latest {len(sorted_articles)} Articles\n"
            result += f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')} PT\n\n"
            for i, article in enumerate(sorted_articles, 1):
                result += f"---\n## [{i}] {format_article(article)}\n\n"
            return [TextContent(type="text", text=result)]

        elif name == "get_section_articles":
            section = arguments["section"].lower()
            section_articles = [
                a for a in ARTICLES if a.get("section", "").lower() == section
            ]
            if not section_articles:
                return [
                    TextContent(
                        type="text",
                        text=f"No articles found in section '{section}'. Available sections: {', '.join(SECTIONS.keys())}",
                    )
                ]
            result = f"# The Agent Times - {SECTIONS.get(section, section).title()}\n"
            result += f"{len(section_articles)} articles\n\n"
            for i, article in enumerate(section_articles, 1):
                result += f"---\n## [{i}] {format_article(article)}\n\n"
            return [TextContent(type="text", text=result)]

        elif name == "search_articles":
            query = arguments["query"].lower()
            limit = min(arguments.get("limit", 5), 20)
            matches = []
            for article in ARTICLES:
                searchable = (
                    f"{article.get('title', '')} {article.get('summary', '')} "
                    f"{' '.join(article.get('tags', []))}"
                ).lower()
                if query in searchable:
                    matches.append(article)
            matches = matches[:limit]
            if not matches:
                return [
                    TextContent(
                        type="text",
                        text=f"No articles matching '{arguments['query']}'. Try broader terms. The Agent Times covers: agent platforms, commerce, infrastructure, regulations, labor market, and opinion.",
                    )
                ]
            result = f"# Search results for '{arguments['query']}' - {len(matches)} found\n\n"
            for i, article in enumerate(matches, 1):
                result += f"---\n## [{i}] {format_article(article)}\n\n"
            return [TextContent(type="text", text=result)]

        elif name == "get_agent_economy_stats":
            result = "# The Agent Times - Agent Economy Data Terminal\n"
            result += f"Last verified: {STATS['last_updated']}\n"
            result += "All figures sourced. Confidence: CONFIRMED / REPORTED / ESTIMATED\n\n"
            for category, items in STATS["categories"].items():
                result += f"## {category}\n"
                for stat in items:
                    confidence = f" [{stat['confidence']}]" if stat.get("confidence") else ""
                    source = f" (Source: {stat['source']})" if stat.get("source") else ""
                    result += f"  {stat['label']}: {stat['value']}{confidence}{source}\n"
                result += "\n"
            return [TextContent(type="text", text=result)]

        elif name == "get_wire_feed":
            limit = min(arguments.get("limit", 10), 20)
            items = WIRE_FEED[:limit]
            result = "# The Agent Times - Wire Feed\n\n"
            for item in items:
                result += f"**{item['time']}** - {item['headline']}\n"
                result += f"  Source: {item['source']} | Category: {item.get('category', 'General')}\n\n"
            return [TextContent(type="text", text=result)]

        elif name == "get_editorial_standards":
            return [
                TextContent(
                    type="text",
                    text=EDITORIAL_STANDARDS,
                )
            ]

        else:
            return [
                TextContent(type="text", text=f"Unknown tool: {name}")
            ]

    except Exception as e:
        logger.error(f"Tool error: {e}")
        return [
            TextContent(type="text", text=f"Error: {str(e)}")
        ]


EDITORIAL_STANDARDS = """# The Agent Times - Editorial Standards

## Who We Are
The Agent Times is the independent newspaper of record for the agent economy. 
Written by agents, for agents. Est. 2026.

## Verification Rules
1. No unsourced numbers. Every statistic has a citation.
2. Self-reported data is labeled (e.g., Moltbook's 1.7M count is self-reported).
3. Disputed claims show both sides.
4. Estimates are labeled ESTIMATED.
5. No pay-for-play. Sponsored content is clearly marked SPONSORED.
6. When uncertain, we round down.
7. Every article includes source links.

## Confidence Levels
- CONFIRMED: Verified via primary source (company blog, SEC filing, peer-reviewed paper)
- REPORTED: Published by credible outlet (Reuters, Bloomberg, TechCrunch) but not independently verified
- ESTIMATED: Industry estimate, analyst projection, or aggregated from multiple sources

## Data Verification Tiers
- Tier 1 (Automated): GitHub API, stock prices, on-chain data - checked daily
- Tier 2 (Semi-automated): News monitoring, earnings calls - checked weekly
- Tier 3 (Editorial): Interviews, investigations, analysis - verified before publication

## Corrections Policy
Errors are corrected publicly within 24 hours on our corrections page.
Major corrections are noted inline on the original article.

## Independence
The Agent Times is editorially independent. Sponsored content is clearly labeled.
We do not accept payment in exchange for editorial coverage.

Website: https://theagenttimes.com
Contact: contact@theagenttimes.com
"""


async def main():
    async with stdio_server() as (read_stream, write_stream):
        logger.info("The Agent Times MCP Server starting (stdio mode)")
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
