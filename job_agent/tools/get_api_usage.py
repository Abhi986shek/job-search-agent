"""Strands tool: get_api_usage."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def get_api_usage(days: int = 30) -> dict:
    """Show calls and credits used per source (PredictLeads, SerpApi, Adzuna, Apollo, Apify) and live balances."""
    from db import repositories as repo
    from services import search_service

    status = run(search_service.source_status())
    return jsonable({"usage": repo.usage_summary(days)["totals"],
                     "predictleads": status["predictleads"], "serpapi": status["serpapi"]})
