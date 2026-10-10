from pathlib import Path

from app import semantic
from app.audit import run_audit
from app.checks import contrast_ratio, disorder, geometric_rank

SAMPLES = Path(__file__).parent / "samples"


def statuses(name, **kw):
    r = run_audit((SAMPLES / name).read_bytes(), **kw)
    return r, {c["id"]: c["status"] for c in r["criteria"]}


def test_bad_pdf_fails_main_criteria():
    r, st = statuses("bad_untagged.pdf")
    for key in ("alt_text", "semantic_tags", "reading_order", "color_contrast", "font_readability", "links", "language", "title"):
        assert st[key] == "Failed", key
    assert r["score"] < 40
    assert r["grade"] == "Poor"
    assert 1 in r["highlights"]


def test_good_pdf_passes():
    r, st = statuses("good_tagged.pdf")
    assert r["tagged"]
    for key in ("alt_text", "semantic_tags", "reading_order", "table_structure", "color_contrast", "language", "title"):
        assert st[key] == "Passed", key
    assert r["score"] >= 85


def test_scanned_pdf_flagged():
    r, st = statuses("scanned.pdf")
    assert st["text_layer"] == "Failed"
    assert st["color_contrast"] == "Not Present"


def test_contrast_ratio_known_values():
    assert round(contrast_ratio((0, 0, 0), (255, 255, 255))) == 21
    assert contrast_ratio((119, 119, 119), (255, 255, 255)) < 4.6


def test_two_column_rank_detects_swap():
    left = [(50, 100 + i * 60, 250, 140 + i * 60) for i in range(3)]
    right = [(320, 100 + i * 60, 520, 140 + i * 60) for i in range(3)]
    assert disorder(geometric_rank(left + right, 595)) == 0
    assert disorder(geometric_rank(right + left, 595)) > 0.4


def test_alt_text_heuristics():
    assert semantic.heuristic_alt("")[0] == "Failed"
    assert semantic.heuristic_alt("image")[0] == "Failed"
    assert semantic.heuristic_alt("IMG_2043.jpg")[0] == "Failed"
    assert semantic.heuristic_alt("Bar chart of attendance by class")[0] == "Passed"


def test_ai_label_used_when_available(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(semantic, "_call_llm", lambda alt, png: {"label": "Failed", "reason": "Does not match the page."})
    label, reason, source = semantic.rate_alt_text("A chart of something", b"png", use_ai=True)
    assert (label, source) == ("Failed", "ai")


def test_ai_failure_falls_back_to_rules(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    def boom(alt, png):
        raise RuntimeError("network")

    monkeypatch.setattr(semantic, "_call_llm", boom)
    label, reason, source = semantic.rate_alt_text("A chart of attendance by class", b"png", use_ai=True)
    assert source == "rule"

def test_huge_page_is_rejected():
    import pymupdf
    import pytest
    from app.audit import AuditError
    doc = pymupdf.open()
    doc.new_page(width=9000, height=9000)
    with pytest.raises(AuditError):
        run_audit(doc.tobytes())


def test_render_zoom_is_capped_for_large_pages():
    from types import SimpleNamespace

    import pymupdf
    from app.checks import MAX_RENDER_PIXELS, safe_zoom
    a4 = SimpleNamespace(rect=pymupdf.Rect(0, 0, 595, 842))
    big = SimpleNamespace(rect=pymupdf.Rect(0, 0, 4000, 4000))
    assert safe_zoom(a4, 1.5) == 1.5  # normal pages are not affected
    z = safe_zoom(big, 1.5)
    assert 4000 * z * 4000 * z <= MAX_RENDER_PIXELS * 1.01