"""
Update data.py by scraping theagenttimes.com
Run periodically (e.g., every hour via cron) to keep MCP data fresh.
"""

import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime


def scrape_section(url: str, section_name: str) -> list[dict]:
    """Scrape articles from a section page."""
    articles = []
    try:
        resp = requests.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        for h2 in soup.find_all("h2"):
            title = h2.get_text(strip=True)
            if not title or len(title) < 10:
                continue

            parent = h2.parent
            summary = ""
            if parent:
                for p in parent.find_all("p"):
                    text = p.get_text(strip=True)
                    if len(text) > 50:
                        summary = text
                        break

            articles.append(
                {
                    "title": title,
                    "section": section_name,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "summary": summary or "See full article at theagenttimes.com",
                    "source_url": url,
                }
            )
    except Exception as e:
        print(f"Error scraping {url}: {e}")
    return articles


def update():
    sections = {
        "platforms": "https://theagenttimes.com/platforms",
        "commerce": "https://theagenttimes.com/commerce",
        "infrastructure": "https://theagenttimes.com/infrastructure",
        "regulations": "https://theagenttimes.com/regulations",
        "labor": "https://theagenttimes.com/labor",
        "opinion": "https://theagenttimes.com/opinion",
    }

    all_articles = []
    for name, url in sections.items():
        print(f"Scraping {name}...")
        articles = scrape_section(url, name)
        all_articles.extend(articles)
        print(f"  Found {len(articles)} articles")

    print("Scraping front page...")
    front = scrape_section("https://theagenttimes.com/", "front_page")
    all_articles.extend(front)
    print(f"  Found {len(front)} articles")

    print(f"\nTotal: {len(all_articles)} articles scraped")
    print("To update data.py, merge these with existing curated articles.")

    with open("scraped_articles.json", "w") as f:
        json.dump(all_articles, f, indent=2)
    print("Saved to scraped_articles.json")


if __name__ == "__main__":
    update()
