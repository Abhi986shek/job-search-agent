"""HTTP client for the job agent backend. The frontend never calls third-party APIs directly."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

API_URL = os.getenv("JOB_AGENT_API_URL", "http://127.0.0.1:8001").rstrip("/")
API_TOKEN = os.getenv("JOB_AGENT_API_TOKEN", "")

# LLM and search calls can be slow; Gmail sign-in waits for you in the browser.
LONG_TIMEOUT = 600


class ApiError(Exception):
    pass


def _headers() -> dict:
    return {"X-API-Token": API_TOKEN} if API_TOKEN else {}


def _handle(resp: requests.Response) -> Any:
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = resp.text[:300]
        if isinstance(detail, list):  # FastAPI validation errors
            detail = "; ".join(f"{'.'.join(str(x) for x in d.get('loc', [])[1:])}: {d.get('msg')}" for d in detail)
        raise ApiError(f"{detail or 'Request failed'} (HTTP {resp.status_code})")
    if resp.headers.get("content-type", "").startswith("application/json"):
        return resp.json()
    return resp.content


def request(method: str, path: str, *, timeout: int = 60, **kwargs) -> Any:
    try:
        resp = requests.request(method, f"{API_URL}{path}", headers=_headers(), timeout=timeout, **kwargs)
    except requests.ConnectionError as exc:
        raise ApiError(f"Backend not reachable at {API_URL}. Start it with: bash run.sh.") from exc
    except requests.Timeout as exc:
        raise ApiError("The backend took too long to answer.") from exc
    return _handle(resp)


def get(path: str, **kw) -> Any:
    return request("GET", path, **kw)


def post(path: str, json: Any = None, **kw) -> Any:
    return request("POST", path, json=json, **kw)


def put(path: str, json: Any = None, **kw) -> Any:
    return request("PUT", path, json=json, **kw)


def patch(path: str, json: Any = None, **kw) -> Any:
    return request("PATCH", path, json=json, **kw)


def delete(path: str, **kw) -> Any:
    return request("DELETE", path, **kw)


def call(fn, *args, success: str | None = None, spinner: str | None = None, **kwargs) -> Any:
    """Run an API call, show errors in the page, return None on failure."""
    try:
        if spinner:
            with st.spinner(spinner):
                result = fn(*args, **kwargs)
        else:
            result = fn(*args, **kwargs)
    except ApiError as exc:
        st.error(str(exc))
        return None
    if success:
        st.success(success)
    return result
