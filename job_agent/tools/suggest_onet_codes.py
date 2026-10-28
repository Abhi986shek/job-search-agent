"""Strands tool: suggest_onet_codes."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def suggest_onet_codes(job_title: str) -> list:
    """Suggest O*NET occupation codes for a job title. PredictLeads job search filters by these codes.

    Args:
        job_title: e.g. "Data Engineer".
    """
    import onet

    return onet.suggest(job_title, 3)
