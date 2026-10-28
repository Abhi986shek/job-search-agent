"""Domain-agnostic helpers: logging, safe errors, text normalisation, hashing, async bridging."""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any, Coroutine, TypeVar
from urllib.parse import urlparse

import httpx

from config import settings

T = TypeVar("T")

logger = logging.getLogger("job_agent")


def setup_logging() -> None:
    """Log to job_agent/app.log (rotating) and the console. Safe to call twice."""
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(settings.log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(file_handler)
    logger.addHandler(console)
    # httpx logs full request URLs at INFO, and SerpApi/Adzuna carry keys in the
    # query string. Keep it at WARNING so keys never reach the log.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def safe_error(exc: BaseException) -> str:
    """Describe an exception without its message.

    httpx error messages include the full URL, and some sources put API keys in
    the query string. Only the status code or exception type is ever surfaced.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "request timed out"
    if isinstance(exc, httpx.RequestError):
        return f"network error ({type(exc).__name__})"
    return type(exc).__name__


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite has no timezone type)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def from_json(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def normalize_text(value: str | None) -> str:
    """Lowercase, strip accents and punctuation, collapse spaces."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return re.sub(r"\s+", " ", value).strip()


_COMPANY_SUFFIXES = re.compile(
    r"\b(the|private limited|pvt ltd|pvt|pte|ltd|limited|inc|llc|llp|plc|gmbh|corp|corporation|co|company|"
    r"technologies|technology|tech|solutions|services|software|systems|consulting|consultancy|labs|group|global|india)\b"
)


def normalize_company(value: str | None) -> str:
    text = normalize_text(value)
    text = _COMPANY_SUFFIXES.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


# ── Dedupe helpers ─────────────────────────────────────────────────────────────
# Jobs from different sources are matched in this order (see repositories.upsert_job):
#   1. a shared reference: ATS job id (Greenhouse, Lever, Ashby, Workday), Naukri id, or cleaned apply URL
#   2. the same company|title|city key
#   3. the same company and title, with at least one city in common (multi-city postings)
# Looser matches (similar titles) are only flagged as possible duplicates for the owner to merge.

_CITY_ALIASES = {
    "bangalore": "bengaluru", "bengalore": "bengaluru", "banglore": "bengaluru",
    "gurgaon": "gurugram", "bombay": "mumbai", "madras": "chennai", "calcutta": "kolkata",
    "new delhi": "delhi", "trivandrum": "thiruvananthapuram", "cochin": "kochi", "ernakulam": "kochi",
    "poona": "pune", "mysore": "mysuru", "mangalore": "mangaluru", "vizag": "visakhapatnam",
    "baroda": "vadodara", "trichy": "tiruchirappalli", "work from home": "remote", "wfh": "remote",
}
# Multi-word names first, so "navi mumbai" wins over "mumbai".
_KNOWN_CITIES = (
    "navi mumbai", "greater noida", "thiruvananthapuram", "tiruchirappalli", "visakhapatnam",
    "bengaluru", "mumbai", "thane", "pune", "hyderabad", "secunderabad", "chennai", "kolkata", "delhi",
    "noida", "gurugram", "faridabad", "ghaziabad", "ahmedabad", "gandhinagar", "jaipur", "kochi",
    "coimbatore", "madurai", "mysuru", "mangaluru", "hubli", "indore", "bhopal", "nagpur", "nashik",
    "lucknow", "kanpur", "chandigarh", "mohali", "panchkula", "vadodara", "surat", "rajkot", "vijayawada",
    "bhubaneswar", "guwahati", "patna", "ranchi", "dehradun", "goa", "vellore", "remote",
)
_CITY_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in _KNOWN_CITIES) + r")\b")
_ALIAS_RE = re.compile(r"\b(" + "|".join(re.escape(a) for a in sorted(_CITY_ALIASES, key=len, reverse=True)) + r")\b")


def _apply_city_aliases(text: str) -> str:
    return _ALIAS_RE.sub(lambda m: _CITY_ALIASES[m.group(1)], text)


def cities_in(location: str | None) -> list[str]:
    """Known city names found anywhere in a location string, in order, aliases resolved.
    'Pune; Bengaluru; Mumbai (All Areas)' -> ['pune', 'bengaluru', 'mumbai'];
    Workday 'IND19-01-Bengaluru-EPIP 122' -> ['bengaluru']."""
    text = _apply_city_aliases(normalize_text(location))
    found: list[str] = []
    for m in _CITY_RE.finditer(text):
        city = m.group(1)
        if city not in found and not (city == "mumbai" and "navi mumbai" in found) \
                and not (city == "noida" and "greater noida" in found):
            found.append(city)
    return found


def primary_city(location: str | None) -> str:
    """First known city, else the first part of the location ('Berlin, Germany' -> 'berlin')."""
    found = cities_in(location)
    if found:
        return found[0]
    first = re.split(r"[,;|/(]", location or "", maxsplit=1)[0]
    return _apply_city_aliases(normalize_text(first))


_TITLE_ABBREV = {
    "sr": "senior", "snr": "senior", "jr": "junior", "jnr": "junior", "engg": "engineer", "engr": "engineer",
    "mgr": "manager", "mngr": "manager", "assoc": "associate", "asst": "assistant", "sw": "software",
    "dev": "developer", "devs": "developer", "backend": "back end", "frontend": "front end",
    "fullstack": "full stack",
}
_TITLE_NOISE = {"walk", "in", "walkin", "urgent", "urgently", "hiring", "immediate", "joiner", "joiners",
                "opening", "openings", "vacancy", "vacancies", "wfh", "remote", "hybrid", "onsite", "on", "site",
                "office", "work", "from", "home", "india", "all", "areas", "area", "location", "locations",
                "years", "year", "yrs", "yr", "exp", "experience", "to", "plus", "only", "and"}
_JOB_CODE_RE = re.compile(r"\b[A-Za-z]{1,5}[-_]?\d{4,}\b|\b\d{5,}\b")
_SEGMENT_SPLIT_RE = re.compile(r"\s*(?:\|\||\||\s[-\u2013\u2014]\s)\s*")


def _is_noise_segment(segment: str) -> bool:
    """True when a title part only names places, work mode, experience or hiring noise."""
    text = _CITY_RE.sub(" ", _apply_city_aliases(normalize_text(segment)))
    words = [w for w in text.split() if not w.isdigit() and w not in _TITLE_NOISE]
    return not words


def normalize_title(title: str | None) -> str:
    """Normalise a job title for matching without merging different roles.

    Removes job codes, bracketed or dash-separated parts that only hold a place, work mode or
    experience range, and hiring noise ('Walk-in ||'). Expands sr/jr/engg and similar.
    Keeps seniority and tech words, so 'Backend Developer - .NET' and '- Java' stay different."""
    text = _JOB_CODE_RE.sub(" ", title or "")
    text = re.sub(r"[\(\[]([^\)\]]*)[\)\]]", lambda m: " " if _is_noise_segment(m.group(1)) else f" {m.group(1)} ", text)
    parts = [p for p in _SEGMENT_SPLIT_RE.split(text) if p.strip() and not _is_noise_segment(p)]
    words = normalize_text(" ".join(parts) or text).split()
    expanded = " ".join(_TITLE_ABBREV.get(w, w) for w in words).split()
    lead_noise = {"walkin", "urgent", "urgently", "hiring", "immediate", "joiner", "joiners"}
    while expanded:
        if expanded[:2] == ["walk", "in"]:
            del expanded[:2]
        elif expanded[0] in lead_noise:
            expanded.pop(0)
        else:
            break
    return " ".join(expanded)


def make_dedupe_key(company: str | None, title: str | None, location: str | None) -> str:
    """company|title|city with normalised parts, e.g. 'cgi|senior back end developer|bengaluru'."""
    return f"{normalize_company(company)}|{normalize_title(title)}|{primary_city(location)}"


_ID_PARAMS = {"gh_jid", "jobid", "job_id", "jk", "currentjobid", "jid", "reqid", "req_id", "requisitionid",
              "postingid", "id"}
_NO_URL_REF_HOSTS = ("google.com", "google.co.in", "bit.ly", "t.me", "lnkd.in")


def canonical_job_url(url: str | None) -> str:
    """A URL that identifies one posting: host + path + id-like query params, tracking removed.
    Returns '' for URLs that could be shared by many jobs (careers home pages, search pages)."""
    if not url:
        return ""
    from urllib.parse import parse_qsl

    try:
        p = urlparse(url.strip())
    except ValueError:
        return ""
    if p.scheme not in ("http", "https") or not p.netloc:
        return ""
    host = p.netloc.lower().split("@")[-1].split(":")[0].removeprefix("www.")
    if any(host == h or host.endswith("." + h) for h in _NO_URL_REF_HOSTS):
        return ""
    path = re.sub(r"/+$", "", p.path or "").lower()
    keep = sorted((k.lower(), v) for k, v in parse_qsl(p.query) if k.lower() in _ID_PARAMS and v)
    last = path.rsplit("/", 1)[-1]
    specific = keep or re.search(r"\d{4,}", path) or re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", path) or len(last) >= 20
    if not specific:
        return ""
    query = "&".join(f"{k}={v}" for k, v in keep)
    return host + path + (f"?{query}" if query else "")


def job_match_refs(source: str, source_job_id: str, *urls: str | None) -> list[str]:
    """References that identify the same posting across sources."""
    refs: list[str] = []

    def add(ref: str) -> None:
        if ref and ref not in refs:
            refs.append(ref[:800])

    if source == "ats":  # our ATS client ids: greenhouse:<board>:<id>, lever:<board>:<id>, ashby:<board>:<id>
        parts = (source_job_id or "").split(":", 2)
        if len(parts) == 3 and parts[2] and "/" not in parts[2]:
            add(f"{parts[0]}:{parts[2].lower()}")
    for url in urls:
        if not url:
            continue
        low = url.lower()
        m = re.search(r"[?&]gh_jid=(\d+)", low) or (
            re.search(r"greenhouse\.io/.*?/jobs/(\d+)", low))
        if m:
            add(f"greenhouse:{m.group(1)}")
        m = re.search(r"jobs\.(?:eu\.)?lever\.co/[^/]+/([0-9a-f-]{36})", low)
        if m:
            add(f"lever:{m.group(1)}")
        m = re.search(r"jobs\.ashbyhq\.com/[^/]+/([0-9a-f-]{36})", low)
        if m:
            add(f"ashby:{m.group(1)}")
        m = re.search(r"//([^./]+)\.[^/]*myworkdayjobs\.com/.*/job/.*_([a-z0-9-]+?)(?:[/?#]|$)", low)
        if m:
            add(f"workday:{m.group(1)}:{m.group(2)}")
        m = re.search(r"naukri\.com/job-listings-[^?#]*?-(\d{9,})(?:[/?#]|$)", low)
        if m:
            add(f"naukri:{m.group(1)}")
        m = re.search(r"linkedin\.com/jobs/view/(?:[^/?#]*?-)?(\d{6,})", low)
        if m:
            add(f"linkedin:{m.group(1)}")
        canon = canonical_job_url(url)
        if canon:
            add("url:" + canon)
    return refs


_PORTAL_HOSTS = ("naukri.com", "linkedin.com", "indeed.com", "indeed.co.in", "glassdoor.com", "glassdoor.co.in",
                 "foundit.in", "cutshort.io", "instahyre.com", "wellfound.com", "hirist.tech", "iimjobs.com",
                 "monsterindia.com", "shine.com", "timesjobs.com", "apna.co")
_AGGREGATOR_HOSTS = ("adzuna.in", "adzuna.com", "google.com", "jooble.org", "talent.com", "careerjet.co.in",
                     "freehire.me", "himalayas.app")


def apply_url_rank(url: str | None) -> int:
    """Lower is better: 0 company site or ATS, 1 job portal, 2 aggregator redirect, 3 none."""
    host = clean_domain(url)
    if not host:
        return 3
    if any(host == h or host.endswith("." + h) for h in _AGGREGATOR_HOSTS):
        return 2
    if any(host == h or host.endswith("." + h) for h in _PORTAL_HOSTS):
        return 1
    return 0


def title_similarity(a: str, b: str) -> float:
    """0..1 similarity of two normalised titles (word overlap blended with sequence match)."""
    from difflib import SequenceMatcher

    if not a or not b:
        return 0.0
    wa, wb = set(a.split()), set(b.split())
    jaccard = len(wa & wb) / len(wa | wb)
    return round(max(jaccard, SequenceMatcher(None, a, b).ratio()), 3)


def same_company(a: str, b: str) -> bool:
    """Normalised company names match, or one is the other plus extra words ('cgi' vs 'cgi information')."""
    if not a or not b:
        return False
    return a == b or a.startswith(b + " ") or b.startswith(a + " ")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def clean_domain(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip().lower()
    if "://" in value:
        value = urlparse(value).netloc or value
    value = value.removeprefix("www.").split("/")[0]
    return re.sub(r"[^a-z0-9.\-]", "", value)


_PORTALS = {
    "naukri.com": "Naukri",
    "linkedin.com": "LinkedIn",
    "indeed.com": "Indeed",
    "indeed.co.in": "Indeed",
    "glassdoor.co.in": "Glassdoor",
    "glassdoor.com": "Glassdoor",
    "cutshort.io": "Cutshort",
    "instahyre.com": "Instahyre",
    "foundit.in": "Foundit",
    "wellfound.com": "Wellfound",
    "hirist.tech": "Hirist",
    "iimjobs.com": "iimjobs",
    "greenhouse.io": "Greenhouse",
    "lever.co": "Lever",
    "ashbyhq.com": "Ashby",
    "myworkdayjobs.com": "Workday",
}


def detect_portal(url: str | None) -> str:
    host = clean_domain(url)
    for domain, name in _PORTALS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host or "unknown"


def is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def run_coro_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine from sync code, whether or not an event loop is running here."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def parse_datetime(value: Any) -> datetime | None:
    """Parse ISO dates from sources. Relative dates ('3 days ago') return None."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text[:10]):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            continue
    return None


def _fernet():
    from cryptography.fernet import Fernet

    if not settings.ENCRYPTION_KEY:
        raise RuntimeError("ENCRYPTION_KEY is not set in job_agent/.env")
    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def slugify(value: str, max_len: int = 60) -> str:
    return (normalize_text(value).replace(" ", "-")[:max_len].strip("-")) or "cv"
