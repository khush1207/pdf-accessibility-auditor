from pathlib import Path

from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)
SAMPLES = Path(__file__).parent / "samples"


def post(data, name="a.pdf"):
    return client.post("/api/audit", files={"file": (name, data, "application/pdf")})


def setup_function():
    main.hits.clear()


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_audit_returns_report():
    r = post((SAMPLES / "good_tagged.pdf").read_bytes())
    assert r.status_code == 200
    body = r.json()
    assert body["score"] >= 85 and len(body["criteria"]) == 11


def test_rejects_non_pdf():
    assert post(b"hello world").status_code == 400


def test_rejects_corrupt_pdf():
    assert post(b"%PDF-1.7 this is not really a pdf").status_code == 422


def test_rejects_oversize(monkeypatch):
    monkeypatch.setattr(main, "MAX_BYTES", 100)
    assert post(b"%PDF-" + b"0" * 500).status_code == 413


def test_rate_limit():
    data = (SAMPLES / "good_tagged.pdf").read_bytes()
    codes = [post(data).status_code for _ in range(main.LIMIT_PER_MINUTE + 1)]
    assert codes[-1] == 429


def test_security_headers_present():
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in r.headers["content-security-policy"]
