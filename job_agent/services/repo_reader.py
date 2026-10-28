"""Read-only access to the owner's GitHub repos, shared by the Assistant and the profile chat.

Rules enforced here, not in the prompts:
- Personal repos can always be read.
- Office (company) repos can be read only when "Content allowed" is ticked for them.
- Secret-looking values (keys, passwords, tokens) are redacted before anything reaches a model.
- Output is capped, so one call cannot dump a whole repo.
"""

from __future__ import annotations

import re

from clients import github
from db import profile_repository as prepo
from utils import logger

MAX_README = 3000
MAX_FILE = 6000
MAX_TREE = 80

SECRET_VALUE = re.compile(r"((?:api[_-]?key|secret[_-]?\w*|password|passwd|access[_-]?token|auth[_-]?token|"
                          r"private[_-]?key|client[_-]?secret)\s*[:=]\s*)(['\"]?)[^\s'\"]+\2", re.I)


def redact(text: str) -> str:
    return SECRET_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]{m.group(2)}", text or "")


def _find(full_name: str) -> dict | None:
    return next((r for r in prepo.list_github_repos() if r["full_name"] == full_name), None)


def _readable(row: dict) -> tuple[bool, str]:
    if row["account_type"] == "personal":
        return True, ""
    if row.get("llm_allowed"):
        return True, ""
    return False, "Office repo: content is not allowed. Tick 'Content allowed' on the GitHub tab to read it."


def list_repos() -> list[dict]:
    """Every synced repo with its selection and whether its content may be read. No commit counts."""
    out = []
    for r in prepo.list_github_repos():
        readable, _ = _readable(r)
        out.append({"full_name": r["full_name"], "account": r["account_type"],
                    "selected_for_profile": bool(r.get("is_selected")), "content_readable": readable,
                    "primary_language": r.get("primary_language"), "description": (r.get("description") or "")[:200]})
    return out


async def read_repo(full_name: str) -> dict:
    row = _find(full_name)
    if not row:
        return {"error": f"{full_name} is not a synced repo. Sync it on the GitHub tab first."}
    readable, why = _readable(row)
    if not readable:
        return {"error": why}
    d = await github.repo_details(row["account_type"], full_name)
    code = d.get("code") or {}
    logger.info("repo read for assistant: %s", full_name)
    if code.get("error"):
        code_out = {"error": code["error"]}
    else:
        code_out = {
            "file_count": code.get("file_count"),
            "python_file_count": code.get("python_file_count"),
            "tree_sample": (code.get("tree") or [])[:MAX_TREE],
            "imports_used": code.get("imports") or [],
            "aws_and_framework_words": {k: v for k, v in (code.get("service_mentions") or {}).items()},
            "dependency_files": {k: redact(v[:1200]) for k, v in (code.get("dependencies") or {}).items()},
        }
    return {"full_name": full_name, "description": row.get("description") or "",
            "languages": d.get("languages") or {}, "readme": redact(d.get("readme_text") or "")[:MAX_README],
            "code": code_out}


async def read_file(full_name: str, path: str) -> dict:
    row = _find(full_name)
    if not row:
        return {"error": f"{full_name} is not a synced repo."}
    readable, why = _readable(row)
    if not readable:
        return {"error": why}
    res = await github.file_text(row["account_type"], full_name, path)
    if "error" in res:
        return res
    text = res["text"]
    truncated = len(text) > MAX_FILE
    logger.info("file read for assistant: %s:%s", full_name, path)
    return {"full_name": full_name, "path": path, "text": redact(text[:MAX_FILE]), "truncated": truncated}
