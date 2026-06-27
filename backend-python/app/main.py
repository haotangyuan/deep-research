from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from .api import model, research, user
from app.infrastructure.cache import close_cache, init_cache
from app.core.common import AppError, failure_response
from app.core.config import get_settings
from app.infrastructure.db import close_db
from app.infrastructure.observability import init_observability, shutdown_observability
from app.application.pipeline import research_task_queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_cache()
    init_observability()
    await research_task_queue.start()
    yield
    await research_task_queue.stop()
    await close_cache()
    await close_db()
    shutdown_observability()


app = FastAPI(
    title="Deep Research API",
    description="基于多智能体协作的自动化深度研究平台",
    version="1.0.0",
    openapi_url="/v3/api-docs",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(user.router)
app.include_router(model.router)
app.include_router(research.router)

if get_settings().research_observability_enabled:
    FastAPIInstrumentor.instrument_app(app)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return failure_response(str(exc))


@app.exception_handler(Exception)
async def generic_error_handler(_: Request, exc: Exception):
    return failure_response("执行异常")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/scalar/index.html", response_class=HTMLResponse)
@app.get("/scalar.html", response_class=HTMLResponse)
async def scalar_index():
    return """
    <!doctype html>
    <html>
      <head>
        <title>Deep Research API</title>
        <meta charset="utf-8" />
      </head>
      <body>
        <script id="api-reference" data-url="/v3/api-docs"></script>
        <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
      </body>
    </html>
    """
