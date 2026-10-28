"""GitHub REST API: list repos for the personal account and the company org, count your commits, read READMEs.

Read-only. Tokens come from .env (fine-grained, read-only). Without a personal token the
public repos of GITHUB_PERSONAL_USERNAME are listed.
"""

from __future__ import annotations

import asyncio
import re

import httpx

from config import settings
from utils import parse_datetime, safe_error

API = "https://api.github.com"


def _headers(token: str, raw: bool = False) -> dict:
    h = {"Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def account_config(account_type: str) -> tuple[str, str]:
    """(token, login_or_org) for an account type."""
    if account_type == "personal":
        return settings.GITHUB_PERSONAL_TOKEN, settings.GITHUB_PERSONAL_USERNAME
    return settings.GITHUB_COMPANY_TOKEN, settings.GITHUB_COMPANY_ORG


def configured(account_type: str) -> bool:
    token, name = account_config(account_type)
    return bool(token or name)


async def _paged(client: httpx.AsyncClient, url: str, params: dict) -> list[dict]:
    items: list[dict] = []
    page = 1
    while page <= 20:
        resp = await client.get(url, params={**params, "per_page": 100, "page": page})
        resp.raise_for_status()
        batch = resp.json()
        if not isinstance(batch, list) or not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return items


async def _whoami(client: httpx.AsyncClient) -> str:
    resp = await client.get(f"{API}/user")
    resp.raise_for_status()
    return resp.json().get("login") or ""


async def _commit_count(client: httpx.AsyncClient, full_name: str, author: str) -> int | None:
    if not author:
        return None
    resp = await client.get(f"{API}/repos/{full_name}/commits", params={"author": author, "per_page": 1})
    if resp.status_code == 409:  # empty repository
        return 0
    if resp.status_code >= 400:
        return None
    link = resp.headers.get("link", "")
    m = re.search(r'[?&]page=(\d+)>; rel="last"', link)
    if m:
        return int(m.group(1))
    data = resp.json()
    return len(data) if isinstance(data, list) else 0


async def list_repos(account_type: str) -> dict:
    """Returns {"login_or_org", "author_login", "repos": [...]} or {"error": "..."}."""
    token, name = account_config(account_type)
    if not configured(account_type):
        return {"error": f"GitHub {account_type} account not configured in .env"}
    try:
        async with httpx.AsyncClient(headers=_headers(token), timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            author = ""
            if token:
                author = await _whoami(client)
            if account_type == "personal":
                if token:
                    raw = await _paged(client, f"{API}/user/repos", {"affiliation": "owner,collaborator"})
                else:
                    raw = await _paged(client, f"{API}/users/{name}/repos", {"type": "owner"})
                author = author or name
                label = author or name
            else:
                # The office account can be an organisation or a user account.
                # No org name, or the name is the token's own user: list that user's repos.
                if token and (not name or name.lower() == author.lower()):
                    raw = await _paged(client, f"{API}/user/repos", {"affiliation": "owner"})
                    label = author
                else:
                    resp = await client.get(f"{API}/orgs/{name}")
                    if resp.status_code == 404:   # not an org: treat it as a user account
                        raw = await _paged(client, f"{API}/users/{name}/repos", {"type": "owner"})
                    else:
                        resp.raise_for_status()
                        raw = await _paged(client, f"{API}/orgs/{name}/repos", {"type": "all"})
                    label = name
                author = author or name or settings.GITHUB_PERSONAL_USERNAME

            sem = asyncio.Semaphore(8)

            async def count(repo: dict) -> int | None:
                async with sem:
                    try:
                        return await _commit_count(client, repo["full_name"], author)
                    except httpx.HTTPError:
                        return None

            counts = await asyncio.gather(*(count(r) for r in raw))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"GitHub {account_type}: {safe_error(exc)}"}

    repos = []
    for r, c in zip(raw, counts):
        repos.append({
            "full_name": r.get("full_name"),
            "is_private": bool(r.get("private")),
            "primary_language": r.get("language"),
            "topics": r.get("topics") or [],
            "description": r.get("description") or "",
            "last_pushed_at": parse_datetime(r.get("pushed_at")),
            "my_commit_count": c,
            "fork": bool(r.get("fork")),
            "archived": bool(r.get("archived")),
        })
    return {"login_or_org": label, "author_login": author, "repos": repos}


# What the code scan looks for. A mention in text is weaker evidence than an import, so both are returned.
CODE_SERVICE_PATTERNS = {
    "AWS Bedrock": r"bedrock", "Amazon Nova": r"\bnova\b", "Amazon S3": r"\bs3\b", "DynamoDB": r"dynamodb",
    "AWS Lambda": r"\blambda\b", "SageMaker": r"sagemaker", "Rekognition": r"rekognition",
    "AWS IoT": r"iot.?core|awsiot", "Strands Agents": r"\bstrands\b", "Django": r"\bdjango\b",
    "FastAPI": r"fastapi", "Flask": r"\bflask\b", "Streamlit": r"streamlit", "PostgreSQL": r"postgres|psycopg",
    "SAML SSO": r"saml", "Slack": r"slack", "WhatsApp": r"whatsapp", "Docker": r"dockerfile",
    "Terraform": r"terraform", "AWS CDK": r"aws_cdk|aws-cdk",
}
DEPENDENCY_FILES = ("requirements.txt", "pyproject.toml", "package.json", "Pipfile")
MAX_SOURCE_FILES = 40
MAX_TREE_PATHS = 150


async def _code_summary(client: httpx.AsyncClient, token: str, full_name: str) -> dict:
    """File tree, dependency files, Python imports and service mentions, read from the default branch.
    Read-only. Only the owner's own repos (or company repos with content allowed) reach this."""
    r = await client.get(f"{API}/repos/{full_name}/git/trees/HEAD", params={"recursive": "1"},
                         headers=_headers(token))
    if r.status_code != 200:
        return {"error": f"tree not available (HTTP {r.status_code})"}
    paths = [t["path"] for t in r.json().get("tree", []) if t.get("type") == "blob"]
    raw = _headers(token, raw=True)

    async def fetch(path: str) -> tuple[str, str]:
        resp = await client.get(f"{API}/repos/{full_name}/contents/{path}", headers=raw)
        return path, (resp.text if resp.status_code == 200 else "")

    deps: dict[str, str] = {}
    dep_paths = [p for p in paths if p.split("/")[-1] in DEPENDENCY_FILES][:4]
    for path, text in await asyncio.gather(*(fetch(p) for p in dep_paths)):
        deps[path] = text[:1200]

    py_paths = [p for p in paths if p.endswith(".py") and "/migrations/" not in p]
    sampled = py_paths[:MAX_SOURCE_FILES]
    imports: set[str] = set()
    services: dict[str, list[str]] = {}
    for path, text in await asyncio.gather(*(fetch(p) for p in sampled)):
        imports.update(re.findall(r"^\s*(?:from|import)\s+([A-Za-z_]\w*)", text, re.M))
        for name, pattern in CODE_SERVICE_PATTERNS.items():
            if re.search(pattern, text, re.I):
                services.setdefault(name, []).append(path)
    return {
        "file_count": len(paths),
        "python_file_count": len(py_paths),
        "sampled_python_files": len(sampled),
        "tree": paths[:MAX_TREE_PATHS],
        "dependencies": deps,
        "imports": sorted(imports),
        "service_mentions": {k: v[:5] for k, v in services.items()},
    }


async def repo_details(account_type: str, full_name: str) -> dict:
    """README text (first 8,000 chars), language breakdown and a code summary for one selected repo."""
    token, _ = account_config(account_type)
    out: dict = {"readme_text": "", "languages": {}, "code": None}
    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            r = await client.get(f"{API}/repos/{full_name}/readme", headers=_headers(token, raw=True))
            if r.status_code == 200:
                out["readme_text"] = r.text[:8000]
        except httpx.HTTPError:
            pass
        try:
            r = await client.get(f"{API}/repos/{full_name}/languages", headers=_headers(token))
            if r.status_code == 200:
                out["languages"] = r.json()
        except httpx.HTTPError:
            pass
        try:
            out["code"] = await _code_summary(client, token, full_name)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            out["code"] = {"error": safe_error(exc)}
    return out


async def file_text(account_type: str, full_name: str, path: str) -> dict:
    """Raw text of one file in the default branch. Returns {"text": ...} or {"error": ...}. Read-only."""
    token, _ = account_config(account_type)
    if not path or ".." in path.split("/") or path.startswith("/"):
        return {"error": "Give a path inside the repo, e.g. src/app.py"}
    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            r = await client.get(f"{API}/repos/{full_name}/contents/{path}", headers=_headers(token, raw=True))
        except httpx.HTTPError as exc:
            return {"error": safe_error(exc)}
    if r.status_code == 404:
        return {"error": f"No file {path} in {full_name}"}
    if r.status_code != 200:
        return {"error": f"GitHub returned HTTP {r.status_code} for {path}"}
    return {"text": r.text}
