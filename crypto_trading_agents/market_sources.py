from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Any

import requests


FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=7"
RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
]

BULL_WORDS = r"(surge|rally|adoption|upgrade|inflow|bullish|partnership|approval|breakout|accumulat)"
BEAR_WORDS = r"(hack|exploit|lawsuit|outflow|bearish|crash|liquidat|ban|regulat|sell[- ]off|dump)"


@dataclass(slots=True)
class NewsItem:
    title: str
    link: str
    source: str
    published: str | None = None
    score: int = 0


def fetch_fear_greed() -> dict[str, Any] | None:
    try:
        response = requests.get(FEAR_GREED_URL, timeout=10)
        response.raise_for_status()
        payload = response.json()
        entries = payload.get("data", [])
        if not entries:
            return None
        current = entries[0]
        history = entries[1:]
        values = [int(entry.get("value", 5)) for entry in entries if str(entry.get("value", "")).isdigit()]
        return {
            "value": int(current.get("value", 50)),
            "classification": current.get("value_classification", "Neutral"),
            "history": [
                {"value": int(item.get("value", 50)), "date": item.get("timestamp", "")}
                for item in history[:6]
            ],
            "average_7d": sum(values) / len(values) if values else None,
        }
    except Exception:
        return None


def fetch_news(limit: int = 12) -> list[NewsItem]:
    items: list[NewsItem] = []
    for feed in RSS_FEEDS:
        try:
            response = requests.get(feed, timeout=10, headers={"User-Agent": "crypto-trading-agents"})
            response.raise_for_status()
            root = ET.fromstring(response.content)
            for node in root.findall(".//item"):
                title = (node.findtext("title") or "").strip()
                link = (node.findtext("link") or "").strip()
                published = (node.findtext("pubDate") or "").strip() or None
                if title:
                    items.append(
                        NewsItem(
                            title=title,
                            link=link,
                            source="CoinDesk" if "coindesk" in feed else "Cointelegraph",
                            published=published,
                            score=news_score(title),
                        )
                    )
        except Exception:
            continue
    items.sort(key=lambda item: item.score, reverse=True)
    return items[:limit]


def news_score(title: str) -> int:
    score = 0
    if re.search(BULL_WORDS, title, flags=re.IGNORECASE):
        score += 1
    if re.search(BEAR_WORDS, title, flags=re.IGNORECASE):
        score -= 1
    return score


def news_as_dicts(items: list[NewsItem]) -> list[dict[str, Any]]:
    return [asdict(item) for item in items]
