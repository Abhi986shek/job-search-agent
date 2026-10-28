"""Keyword-based O*NET occupation suggestions for tech roles. PredictLeads discovery filters by these codes.

Suggestions only. You confirm or edit the codes on each target role. Full list: https://www.onetonline.org
"""

from __future__ import annotations

from utils import normalize_text

ONET_CODES: list[tuple[str, str, tuple[str, ...]]] = [
    ("15-1252.00", "Software Developers",
     ("software", "developer", "backend", "back end", "full stack", "fullstack", "sde", "engineer", "python",
      "java", "golang", "node", "programmer", "mobile", "android", "ios")),
    ("15-1254.00", "Web Developers", ("web", "frontend", "front end", "react", "angular", "javascript", "ui developer")),
    ("15-1253.00", "Software Quality Assurance Analysts and Testers",
     ("qa", "quality", "test", "tester", "sdet", "automation testing")),
    ("15-1299.08", "Computer Systems Engineers/Architects",
     ("devops", "cloud", "sre", "site reliability", "platform", "infrastructure", "architect", "solutions architect")),
    ("15-1244.00", "Network and Computer Systems Administrators", ("sysadmin", "system administrator", "network admin")),
    ("15-1241.00", "Computer Network Architects", ("network architect", "network engineer")),
    ("15-1212.00", "Information Security Analysts", ("security", "cybersecurity", "soc", "appsec", "infosec")),
    ("15-1242.00", "Database Administrators", ("dba", "database administrator")),
    ("15-1243.00", "Database Architects", ("data architect", "database architect", "data engineer")),
    ("15-2051.00", "Data Scientists", ("data scientist", "machine learning", "ml", "ai", "deep learning", "nlp", "llm",
                                       "genai", "data science")),
    ("15-2051.01", "Business Intelligence Analysts", ("bi", "business intelligence", "data analyst", "analytics")),
    ("15-1221.00", "Computer and Information Research Scientists", ("research scientist", "research engineer")),
    ("15-1211.00", "Computer Systems Analysts", ("systems analyst", "business analyst", "it analyst")),
    ("11-3021.00", "Computer and Information Systems Managers",
     ("engineering manager", "tech lead", "it manager", "head of engineering", "cto", "director of engineering",
      "vp engineering")),
    ("15-1299.09", "Information Technology Project Managers", ("project manager", "program manager", "scrum master")),
    ("15-1255.00", "Web and Digital Interface Designers", ("ui designer", "ux", "product designer")),
]


def suggest(title: str, limit: int = 3) -> list[dict]:
    text = f" {normalize_text(title)} "
    scored = []
    for code, name, keywords in ONET_CODES:
        hits = sum(1 for k in keywords if f" {normalize_text(k)} " in text)
        if hits:
            scored.append((hits, code, name))
    scored.sort(key=lambda x: -x[0])
    out = [{"code": c, "name": n} for _, c, n in scored[:limit]]
    return out or [{"code": "15-1252.00", "name": "Software Developers"}]


def all_codes() -> list[dict]:
    return [{"code": c, "name": n} for c, n, _ in ONET_CODES]
