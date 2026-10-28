"""Apify actor that reads your own public LinkedIn profile (cookie-free harvestapi profile scraper).

Uses the cookie-free harvestapi profile scraper. The token is sent as a Bearer header,
not in the URL, so it never reaches logs. Only your own profile URL is ever passed.
"""

from __future__ import annotations

import httpx

from config import settings
from utils import safe_error

BASE = "https://api.apify.com/v2"


def configured() -> bool:
    return bool(settings.APIFY_TOKEN)


async def fetch_profile(profile_url: str) -> dict:
    """Run the actor synchronously and return {"item": {...}} or {"error": "..."}."""
    if not configured():
        return {"error": "APIFY_TOKEN not set"}
    if "linkedin.com/in/" not in (profile_url or ""):
        return {"error": "Enter your LinkedIn profile URL, e.g. https://www.linkedin.com/in/your-name"}
    actor = settings.APIFY_LINKEDIN_ACTOR.replace("/", "~")
    url = f"{BASE}/acts/{actor}/run-sync-get-dataset-items"
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(url, json={"urls": [profile_url]},
                                     headers={"Authorization": f"Bearer {settings.APIFY_TOKEN}"})
            resp.raise_for_status()
            items = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Apify: {safe_error(exc)}"}
    if not isinstance(items, list) or not items:
        return {"error": "Apify returned no profile data"}
    return {"item": items[0]}
