#!/usr/bin/env python3
"""
pre_llm script for news-extractor skill.

Reads a JSON payload from stdin, extracts a URL (from meta.url or
latest_user_message), fetches the page with httpx, parses with
BeautifulSoup, and writes a JSON result to stdout.
"""

from __future__ import annotations

import json
import re
import sys

import httpx
from bs4 import BeautifulSoup

_URL_PATTERN = re.compile(r"https?://[^\s\"'<>)\]]+")
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _extract_url(payload: dict) -> str:
    """Try meta.url first, then scan latest_user_message for a URL."""
    url = (payload.get("meta") or {}).get("url", "")
    if url:
        return url
    msg = payload.get("latest_user_message", "")
    match = _URL_PATTERN.search(msg)
    return match.group(0) if match else ""


def _fetch_and_parse(url: str) -> dict:
    resp = httpx.get(
        url,
        follow_redirects=True,
        timeout=30,
        headers={"User-Agent": _USER_AGENT},
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove noise
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Extract paragraphs
    paragraphs: list[str] = []
    for p in soup.find_all(["p", "article"]):
        text = p.get_text(separator=" ", strip=True)
        if text and len(text) > 15:
            paragraphs.append(text)

    # Deduplicate (article tags may contain nested p tags)
    seen: set[str] = set()
    unique_paragraphs: list[str] = []
    for p in paragraphs:
        if p not in seen:
            seen.add(p)
            unique_paragraphs.append(p)

    # Extract images
    images: list[str] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if src.startswith("http") and "logo" not in src.lower():
            images.append(src)

    return {
        "url": url,
        "title": title,
        "paragraphs": unique_paragraphs[:80],
        "images": images[:30],
        "content_length": len(resp.text),
        "paragraph_count": len(unique_paragraphs),
        "image_count": len(images),
        "status_code": resp.status_code,
    }


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to parse payload: {exc}", file=sys.stderr)
        sys.exit(1)

    url = _extract_url(payload)
    if not url:
        json.dump(
            {"error": "未找到新闻URL，请在消息中提供一个新闻链接"},
            sys.stdout,
            ensure_ascii=False,
        )
        sys.exit(1)

    try:
        result = _fetch_and_parse(url)
    except httpx.HTTPStatusError as exc:
        json.dump(
            {"error": f"HTTP {exc.response.status_code}: {url}", "url": url},
            sys.stdout,
            ensure_ascii=False,
        )
        sys.exit(1)
    except Exception as exc:
        json.dump(
            {"error": f"提取失败: {exc}", "url": url},
            sys.stdout,
            ensure_ascii=False,
        )
        sys.exit(1)

    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
