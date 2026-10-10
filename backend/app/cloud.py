"""Cloud features: Google single sign-on (Unit 4), security posture (Unit 4),
instance metrics (Unit 5)."""
import os
import socket
import threading
import time
from collections import deque

import psutil
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse


# ----------------------------------------------------------------------
# Single sign-on (Google OpenID Connect)
# ----------------------------------------------------------------------

router = APIRouter()
oauth = OAuth()


def sso_enabled():
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def allowed_domains():
    raw = os.environ.get("SSO_ALLOWED_DOMAINS", "")
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


if sso_enabled():
    oauth.register(
        name="google",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        client_kwargs={"scope": "openid email profile"},
    )


def current_user(request: Request):
    return request.session.get("user")


def require_user(request: Request):
    if sso_enabled() and not current_user(request):
        raise HTTPException(401, "Please sign in first.")


@router.get("/auth/login")
async def login(request: Request):
    if not sso_enabled():
        raise HTTPException(503, "Single sign-on is not configured on this server.")
    redirect_uri = os.environ.get("OAUTH_REDIRECT_URI") or str(request.url_for("callback"))
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/callback", name="callback")
async def callback(request: Request):
    if not sso_enabled():
        raise HTTPException(503, "Single sign-on is not configured on this server.")
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        raise HTTPException(400, "Sign-in failed, please try again.")
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if not email or not info.get("email_verified"):
        raise HTTPException(403, "A verified email address is required.")
    domains = allowed_domains()
    if domains and email.split("@")[-1] not in domains:
        raise HTTPException(403, "This email domain is not allowed.")
    request.session["user"] = {"email": email, "name": info.get("name", "")}
    return RedirectResponse("/")


@router.get("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


@router.get("/api/me")
def me(request: Request):
    return {"sso_enabled": sso_enabled(), "user": current_user(request)}


# ----------------------------------------------------------------------
# Security posture (CSPM style checks)
# ----------------------------------------------------------------------

PASS, WARN, FAIL = "Pass", "Warn", "Fail"


REQUIRED_SECURITY_HEADERS = {
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "strict-transport-security",
}

_last_security_headers_ok = None


def record_security_headers(headers):
    global _last_security_headers_ok

    received = {
        name.lower(): value
        for name, value in headers.items()
    }

    _last_security_headers_ok = all(
        received.get(name)
        for name in REQUIRED_SECURITY_HEADERS
    )

def check(cid, category, title, status, detail, fix=""):
    return {"id": cid, "category": category, "title": title, "status": status, "detail": detail, "fix": fix}


def assess(ctx):
    out = []
    https = ctx["scheme"] == "https"
    out.append(check("tls", "Data protection", "Traffic is encrypted in transit",
                     PASS if https else FAIL,
                     "Request arrived over " + ctx["scheme"] + ".",
                     "" if https else "Serve only over HTTPS. Render terminates TLS automatically on its public URL."))

    out.append(check("headers", "Network", "Security headers are set",
                     PASS if ctx["headers_ok"] else FAIL,
                     "CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy and HSTS are added to every response."
                     if ctx["headers_ok"] else "Some security headers are missing."))

    out.append(check("sso", "Identity and access", "Single sign-on protects the API",
                     PASS if ctx["sso"] else WARN,
                     "Google OpenID Connect login is required." if ctx["sso"] else "Login is not required, anyone with the URL can use the service.",
                     "" if ctx["sso"] else "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to enable SSO."))

    if ctx["sso"]:
        domains = ctx["domains"]
        out.append(check("sso_domains", "Identity and access", "Sign-in is limited to approved email domains",
                         PASS if domains else WARN,
                         "Allowed domains: " + ", ".join(domains) if domains else "Any verified Google account can sign in.",
                         "" if domains else "Set SSO_ALLOWED_DOMAINS to your institute domain."))

    secret = os.environ.get("SESSION_SECRET", "")
    out.append(check("session_secret", "Secrets management", "Session signing key comes from the environment",
                     PASS if len(secret) >= 32 else FAIL,
                     "A shared key of sufficient length is configured, so sessions stay valid across load-balanced instances."
                     if len(secret) >= 32 else "No strong SESSION_SECRET set, a random key is generated per process and sessions break across instances.",
                     "" if len(secret) >= 32 else "Set SESSION_SECRET to a random value of at least 32 characters."))

    out.append(check("rate_limit", "Abuse protection", "Per-client rate limiting is active",
                     PASS if ctx["rate_limit"] > 0 else FAIL, "Limit: %d audits per minute per client." % ctx["rate_limit"]))

    out.append(check("upload_limit", "Abuse protection", "Upload size and page limits are enforced",
                     PASS if ctx["max_bytes"] <= 25 * 1024 * 1024 else WARN,
                     "Maximum upload %d MB, concurrent audits %d." % (ctx["max_bytes"] // 1048576, ctx["max_concurrent"])))

    root = hasattr(os, "geteuid") and os.geteuid() == 0
    out.append(check("non_root", "Workload hardening", "Process runs as a non-root user",
                     FAIL if root else PASS, "Running as root." if root else "Running as an unprivileged user.",
                     "Add a USER instruction in the Dockerfile." if root else ""))

    out.append(check("api_docs", "Exposure", "Interactive API docs are hidden in production",
                     PASS if ctx["openapi_url"] is None else WARN,
                     "OpenAPI and docs endpoints are disabled." if ctx["openapi_url"] is None else "API docs are publicly reachable (fine for local development).",
                     "" if ctx["openapi_url"] is None else "Set PRODUCTION=1 to hide them."))

    out.append(check(
                    "retention",
                    "Data protection",
                    "Uploaded documents are not retained",
                    PASS,
                    "PDFs are processed for the audit and are not intentionally retained. "
                    "Large uploads may temporarily use disk-backed storage during request processing."))

    out.append(check("ai_consent", "Data protection", "External AI sharing is opt-in",
                     PASS, "Page images go to an AI service only when the user ticks the option and an API key is configured."))

    counted = [c for c in out]
    passed = sum(1 for c in counted if c["status"] == PASS)
    return {"score": round(100 * passed / len(counted)), "passed": passed, "total": len(counted), "checks": out}


# ----------------------------------------------------------------------
# Instance metrics (resource utilization)
# ----------------------------------------------------------------------

INSTANCE = os.environ.get("RENDER_INSTANCE_ID") or os.environ.get("HOSTNAME") or socket.gethostname()
START = time.time()
_lock = threading.Lock()
_counts = {"requests": 0, "audits": 0, "errors": 0, "rejected": 0}
_latencies = deque(maxlen=500)
_inflight = 0
_proc = psutil.Process()
psutil.cpu_percent(interval=None)


def started(path):
    global _inflight
    with _lock:
        _counts["requests"] += 1
        _inflight += 1


def finished(path, status, seconds):
    global _inflight
    with _lock:
        _inflight -= 1
        if path == "/api/audit" and status == 200:
            _counts["audits"] += 1
            _latencies.append(seconds)
        if status >= 500:
            _counts["errors"] += 1
        if status in (429, 503):
            _counts["rejected"] += 1


def percentile(values, p):
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(len(s) * p))], 3)


def snapshot():
    with _lock:
        lat = list(_latencies)
        counts = dict(_counts)
        inflight = _inflight
    mem = psutil.virtual_memory()
    return {
        "instance": INSTANCE,
        "uptime_seconds": int(time.time() - START),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_count": psutil.cpu_count(),
        "process_memory_mb": round(_proc.memory_info().rss / 1048576, 1),
        "system_memory_percent": mem.percent,
        "load_average": [round(x, 2) for x in os.getloadavg()] if hasattr(os, "getloadavg") else None,
        "in_flight_requests": inflight,
        "requests_total": counts["requests"],
        "audits_completed": counts["audits"],
        "server_errors": counts["errors"],
        "rejected_busy_or_rate_limited": counts["rejected"],
        "audit_latency_p50_seconds": percentile(lat, 0.5),
        "audit_latency_p95_seconds": percentile(lat, 0.95),
    }
