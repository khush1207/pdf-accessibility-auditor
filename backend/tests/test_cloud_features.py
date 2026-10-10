import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app import cloud, main

client = TestClient(main.app)
SAMPLES = Path(__file__).parent / "samples"


def setup_function():
    main.hits.clear()


def pdf(name="good_tagged.pdf"):
    return (SAMPLES / name).read_bytes()


def test_served_by_header_and_hsts():
    r = client.get("/api/health")
    assert r.headers["x-served-by"]
    assert "max-age" in r.headers["strict-transport-security"]


def test_metrics_report_utilization():
    client.post("/api/audit", files={"file": ("a.pdf", pdf(), "application/pdf")})
    m = client.get("/api/metrics").json()
    for key in ("instance", "cpu_percent", "process_memory_mb", "in_flight_requests", "audits_completed", "audit_latency_p95_seconds"):
        assert key in m
    assert m["audits_completed"] >= 1


def test_posture_reports_checks():
    p = client.get("/api/posture").json()
    ids = {c["id"] for c in p["checks"]}
    assert {"tls", "headers", "sso", "session_secret", "rate_limit", "non_root", "retention"} <= ids
    assert 0 <= p["score"] <= 100


def test_posture_flags_missing_sso(monkeypatch):
    monkeypatch.setattr(cloud, "sso_enabled", lambda: False)
    p = client.get("/api/posture").json()
    sso = next(c for c in p["checks"] if c["id"] == "sso")
    assert sso["status"] == "Warn"


def test_sso_blocks_anonymous_requests(monkeypatch):
    monkeypatch.setattr(cloud, "sso_enabled", lambda: True)
    assert client.post("/api/audit", files={"file": ("a.pdf", pdf(), "application/pdf")}).status_code == 401
    assert client.get("/api/metrics").status_code == 401
    assert client.get("/api/posture").status_code == 401
    assert client.get("/api/health").status_code == 200
    me = client.get("/api/me").json()
    assert me["sso_enabled"] is True and me["user"] is None


def test_login_unavailable_when_not_configured(monkeypatch):
    monkeypatch.setattr(cloud, "sso_enabled", lambda: False)
    assert client.get("/auth/login", follow_redirects=False).status_code == 503


def test_busy_server_returns_503(monkeypatch):
    class FullSlots:
        async def acquire(self):
            await asyncio.sleep(10)

        def release(self):
            pass

    monkeypatch.setattr(main, "slots", FullSlots())
    monkeypatch.setattr(asyncio, "wait_for", _fast_timeout(asyncio.wait_for))
    r = client.post("/api/audit", files={"file": ("a.pdf", pdf(), "application/pdf")})
    assert r.status_code == 503
    assert r.headers["retry-after"]


def _fast_timeout(real):
    async def wrapper(aw, timeout):
        return await real(aw, 0.05)
    return wrapper


def test_batch_audits_in_parallel():
    files = [("files", ("good.pdf", pdf("good_tagged.pdf"), "application/pdf")),
             ("files", ("bad.pdf", pdf("bad_untagged.pdf"), "application/pdf")),
             ("files", ("scan.pdf", pdf("scanned.pdf"), "application/pdf"))]
    r = client.post("/api/audit-batch", files=files)
    assert r.status_code == 200
    body = r.json()
    by = {x["file"]: x for x in body["results"]}
    assert by["good.pdf"]["score"] >= 85
    assert by["bad.pdf"]["score"] < 40
    assert by["scan.pdf"]["criteria"]["text_layer"] == "Failed"


def test_batch_limits():
    files = [("files", ("a%d.pdf" % i, pdf(), "application/pdf")) for i in range(main.BATCH_MAX_FILES + 1)]
    assert client.post("/api/audit-batch", files=files).status_code == 400


def test_page_and_script_served():
    page = client.get("/")
    assert page.status_code == 200
    assert "status-view" in page.text and "<style>" in page.text
    assert client.get("/app.js").status_code == 200
