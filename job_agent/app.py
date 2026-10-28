"""FastAPI entry point. Run from the job_agent folder:

    ..\\Myenv\\Scripts\\python.exe app.py

Binds to 127.0.0.1 only. There are no user accounts; set BACKEND_API_TOKEN to require
an X-API-Token header on every request except /health.
"""

from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import settings
from db.session import init_db
from routes import router
from utils import logger, safe_error, setup_logging


async def _reply_checker() -> None:
    """Check tracked Gmail threads every REPLY_CHECK_MINUTES while the backend runs."""
    from db import outreach_repository as orepo
    from services import outreach_service

    while True:
        await asyncio.sleep(max(1, settings.REPLY_CHECK_MINUTES) * 60)
        try:
            if orepo.get_email_account():
                res = await outreach_service.check_replies()
                if res.get("new_replies"):
                    logger.info("reply checker: %s new replies", res["new_replies"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("reply checker failed: %s", safe_error(exc))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    init_db()
    task = asyncio.create_task(_reply_checker())
    logger.info("job agent backend started on %s:%s", settings.HOST, settings.PORT)
    yield
    task.cancel()


app = FastAPI(title="Job Search and CV Agent", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def require_token(request: Request, call_next):
    if settings.BACKEND_API_TOKEN and request.url.path not in ("/health", "/docs", "/openapi.json"):
        sent = request.headers.get("X-API-Token", "")
        if not hmac.compare_digest(sent, settings.BACKEND_API_TOKEN):
            return JSONResponse({"detail": "Missing or wrong X-API-Token"}, status_code=401)
    return await call_next(request)


app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host=settings.HOST, port=settings.PORT, reload=False)
