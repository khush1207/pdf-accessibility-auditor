import asyncio
import multiprocessing
import os
import secrets
import time
from collections import defaultdict, deque
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import cloud, semantic
from .audit import AuditError, run_audit, summarize_item

MAX_BYTES = 20 * 1024 * 1024
BATCH_MAX_FILES = 5
BATCH_MAX_TOTAL = 40 * 1024 * 1024
LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "10"))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_AUDITS", "2"))
BATCH_WORKERS = int(os.environ.get("BATCH_WORKERS", "2"))
AUDIT_TIMEOUT = 60
PRODUCTION = bool(os.environ.get("RENDER") or os.environ.get("PRODUCTION"))

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'",
}

hits = defaultdict(deque)
slots = asyncio.Semaphore(MAX_CONCURRENT)
_pool = None

app = FastAPI(
    title="PDF Accessibility Auditor",
    docs_url=None if PRODUCTION else "/docs",
    redoc_url=None,
    openapi_url=None if PRODUCTION else "/openapi.json",
)


@app.middleware("http")
async def track_and_secure(request, call_next):
    path = request.url.path
    cloud.started(path)
    start = time.time()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
    finally:
        cloud.finished(path, status, time.time() - start)
    for key, value in SECURITY_HEADERS.items():
        response.headers[key] = value
    response.headers["X-Served-By"] = cloud.INSTANCE
    cloud.record_security_headers(response.headers)
    return response


app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET") or secrets.token_hex(32),
    same_site="lax",
    https_only=PRODUCTION,
    max_age=8 * 3600,
)
app.include_router(cloud.router)


def rate_limited(ip):
    now = time.time()
    q = hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= LIMIT_PER_MINUTE:
        return True
    q.append(now)
    return False


def client_ip(request):
    return request.client.host if request.client else "unknown"


async def read_pdf(file):
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File is larger than 20 MB.")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(400, "Only PDF files are accepted.")
    return data


async def acquire_slot():
    try:
        await asyncio.wait_for(slots.acquire(), timeout=15)
    except asyncio.TimeoutError:
        raise HTTPException(503, "The server is busy, please try again shortly.", headers={"Retry-After": "10"})


def get_pool():
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=BATCH_WORKERS, mp_context=multiprocessing.get_context("spawn"))
    return _pool


@app.get("/api/health")
def health():
    return {"status": "ok", "instance": cloud.INSTANCE, "ai_available": semantic.ai_available(), "sso_enabled": cloud.sso_enabled()}


@app.get("/api/metrics", dependencies=[Depends(cloud.require_user)])
def get_metrics():
    return cloud.snapshot()


@app.get("/api/posture", dependencies=[Depends(cloud.require_user)])
def get_posture(request: Request):
    ctx = {
        "scheme": request.headers.get("x-forwarded-proto", request.url.scheme),
        "headers_ok": cloud._last_security_headers_ok is True,
        "sso": cloud.sso_enabled(),
        "domains": cloud.allowed_domains(),
        "rate_limit": LIMIT_PER_MINUTE,
        "max_bytes": MAX_BYTES,
        "max_concurrent": MAX_CONCURRENT,
        "openapi_url": app.openapi_url,
    }
    return cloud.assess(ctx)


@app.post("/api/audit", dependencies=[Depends(cloud.require_user)])
async def audit(request: Request, file: UploadFile = File(...), use_ai: bool = Form(False)):
    if rate_limited(client_ip(request)):
        raise HTTPException(429, "Too many requests, please wait a minute.")
    data = await read_pdf(file)
    await acquire_slot()
    try:
        return await asyncio.wait_for(run_in_threadpool(run_audit, data, use_ai), AUDIT_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(504, "The audit took too long. Try a shorter document.")
    except AuditError as e:
        raise HTTPException(422, str(e))
    finally:
        slots.release()


@app.post("/api/audit-batch", dependencies=[Depends(cloud.require_user)])
async def audit_batch(request: Request, files: list[UploadFile] = File(...)):
    if rate_limited(client_ip(request)):
        raise HTTPException(429, "Too many requests, please wait a minute.")
    if len(files) > BATCH_MAX_FILES:
        raise HTTPException(400, "At most %d files per batch." % BATCH_MAX_FILES)
    items, total = [], 0
    for f in files:
        data = await read_pdf(f)
        total += len(data)
        items.append(((f.filename or "file.pdf")[:100], data))
    if total > BATCH_MAX_TOTAL:
        raise HTTPException(413, "Batch is larger than 40 MB.")
    await acquire_slot()
    try:
        start = time.time()
        loop = asyncio.get_running_loop()
        jobs = [loop.run_in_executor(get_pool(), summarize_item, item) for item in items]
        results = await asyncio.wait_for(asyncio.gather(*jobs), AUDIT_TIMEOUT * 2)
        return {"workers": BATCH_WORKERS, "files": len(items), "wall_seconds": round(time.time() - start, 2), "results": results}
    except asyncio.TimeoutError:
        raise HTTPException(504, "The batch took too long.")
    finally:
        slots.release()


frontend = Path(__file__).resolve().parents[2] / "frontend"
if frontend.exists():
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
