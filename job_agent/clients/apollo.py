"""Apollo: find recruiters or hiring managers at a company, then reveal one work email.

Search does not reveal emails. Revealing an email (people/match) spends Apollo credits,
so it is only called when you click "Reveal email" for one person.
"""

from __future__ import annotations

import httpx

from config import settings
from utils import clean_domain, safe_error

API_BASE = "https://api.apollo.io/api/v1"
DEFAULT_TITLES = ["recruiter", "talent acquisition", "technical recruiter", "hr", "hiring manager",
                  "engineering manager", "head of engineering"]


def configured() -> bool:
    return bool(settings.APOLLO_API_KEY)


def _headers() -> dict:
    return {"Content-Type": "application/json", "Accept": "application/json", "X-Api-Key": settings.APOLLO_API_KEY}


def _person(p: dict) -> dict:
    email = p.get("email") or ""
    if "email_not_unlocked" in email:
        email = ""
    org = p.get("organization") or {}
    return {
        "apollo_person_id": p.get("id"),
        "full_name": p.get("name") or " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x),
        "title": p.get("title") or "",
        "company": org.get("name") or p.get("organization_name") or "",
        "linkedin_url": p.get("linkedin_url") or "",
        "email": email,
        "email_status": "verified" if email and p.get("email_status") == "verified" else ("guessed" if email else "unknown"),
    }


async def search_people(domain: str, company_name: str = "", titles: list[str] | None = None,
                        per_page: int = 10) -> dict:
    if not configured():
        return {"error": "APOLLO_API_KEY not set"}
    payload: dict = {"person_titles": titles or DEFAULT_TITLES, "per_page": per_page, "page": 1}
    dom = clean_domain(domain)
    if dom:
        payload["q_organization_domains_list"] = [dom]
    elif company_name:
        payload["q_keywords"] = company_name
    else:
        return {"error": "Company domain or name needed for Apollo search"}
    try:
        async with httpx.AsyncClient(headers=_headers(), timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.post(f"{API_BASE}/mixed_people/api_search", json=payload)
            if resp.status_code in (404, 405):
                resp = await client.post(f"{API_BASE}/mixed_people/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Apollo search: {safe_error(exc)}"}
    people = data.get("people") or data.get("contacts") or []
    return {"people": [_person(p) for p in people if isinstance(p, dict)]}


async def reveal_email(apollo_person_id: str) -> dict:
    """people/match by Apollo ID. Spends Apollo credits."""
    if not configured():
        return {"error": "APOLLO_API_KEY not set"}
    try:
        async with httpx.AsyncClient(headers=_headers(), timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.post(f"{API_BASE}/people/match",
                                     json={"id": apollo_person_id, "reveal_personal_emails": False})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Apollo match: {safe_error(exc)}"}
    person = data.get("person") or {}
    if not person:
        return {"error": "Apollo found no match"}
    return {"person": _person(person)}
