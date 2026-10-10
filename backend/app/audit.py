"""Runs every check, scores the result and draws highlighted pages."""
import base64
import io
import time

import pikepdf
import pymupdf

from .checks import (CANNOT_TELL, FAILED, NOT_PRESENT, PASSED, Finding, check_contrast, check_document,
                     check_fonts, check_links, check_reading_order, safe_zoom, check_structure, check_text_layer, is_tagged)


# ----------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------

CRITERIA = {
    "text_layer": ("Selectable text", 15),
    "alt_text": ("Alternative text", 18),
    "semantic_tags": ("Tags and headings", 15),
    "reading_order": ("Reading order", 12),
    "table_structure": ("Table structure", 8),
    "color_contrast": ("Color contrast", 10),
    "font_readability": ("Font readability", 8),
    "links": ("Link text", 4),
    "language": ("Document language", 5),
    "title": ("Document title", 3),
    "bookmarks": ("Bookmarks", 2),
}


def rollup(findings):
    by = {}
    for f in findings:
        by.setdefault(f.criterion, []).append(f.status)
    out = {}
    for key in CRITERIA:
        sts = by.get(key)
        if not sts:
            out[key] = CANNOT_TELL
        elif FAILED in sts:
            out[key] = FAILED
        elif CANNOT_TELL in sts:
            out[key] = CANNOT_TELL
        elif PASSED in sts:
            out[key] = PASSED
        else:
            out[key] = NOT_PRESENT
    return out


def score(statuses):
    total = penalty = 0
    for key, st in statuses.items():
        w = CRITERIA[key][1]
        if st == NOT_PRESENT:
            continue
        total += w
        if st == FAILED:
            penalty += w
        elif st == CANNOT_TELL:
            penalty += w * 0.4
    if total == 0:
        return 100
    return round(100 * (1 - penalty / total))


def grade(value):
    if value >= 85:
        return "Good"
    if value >= 60:
        return "Needs work"
    return "Poor"


# ----------------------------------------------------------------------
# Highlighted pages
# ----------------------------------------------------------------------

def image_boxes(page):
    """Positions of the images on a page (tiny ones such as bullets are ignored)."""
    return [tuple(i["bbox"]) for i in page.get_image_info() if pymupdf.Rect(i["bbox"]).get_area() >= 1500]


def draw_label(page, rect, text):
    """Small red tag with white text, placed just above the top-left corner of a box."""
    width = 6.5 * len(text) + 8
    x = max(0, rect.x0)
    y = max(0, rect.y0 - 16)
    tag = pymupdf.Rect(x, y, x + width, y + 15)
    page.draw_rect(tag, color=(0.85, 0.1, 0.1), fill=(0.85, 0.1, 0.1))
    page.insert_text((x + 4, y + 11.5), text, fontname="helv", fontsize=10, color=(1, 1, 1))


def highlight_pages(data, problems, max_pages=40):
    """One PNG for every page that a problem points to.
    `problems` must be the same ordered list the user sees, so that the number drawn
    next to a box is the number of that finding in the list (1, 2, 3 ...).
    A finding with a position gets that box. An alt text finding without one outlines
    the images on its page. A page with no boxes at all gets a border."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = {}  # page number -> {box: [finding numbers]}
    for number, f in enumerate(problems, start=1):
        if f.page is None:
            continue
        boxes = pages.setdefault(f.page, {})
        if f.bbox:
            found = [tuple(f.bbox)]
        elif f.criterion == "alt_text":
            found = image_boxes(doc[f.page])
        elif f.criterion == "table_structure":
            try:
                found = [tuple(tb.bbox) for tb in doc[f.page].find_tables().tables]
            except Exception:
                found = []
        else:
            found = []
        if not found:  # no position known: outline the whole page
            found = [tuple(doc[f.page].rect + (6, 6, -6, -6))]
        for box in found:
            boxes.setdefault(box, []).append(number)
    out = {}
    for pno in sorted(pages)[:max_pages]:
        page = doc[pno]
        for box, numbers in pages[pno].items():
            rect = pymupdf.Rect(box) + (-2, -2, 2, 2)
            page.draw_rect(rect, color=(0.85, 0.1, 0.1), width=1.6)
            draw_label(page, rect, ",".join(str(n) for n in numbers))
            z = safe_zoom(page, 1.1)
            png = page.get_pixmap(matrix=pymupdf.Matrix(z, z)).tobytes("png")
        out[pno + 1] = base64.b64encode(png).decode()
    doc.close()
    return out
# ----------------------------------------------------------------------
# Audit orchestration
# ----------------------------------------------------------------------

MAX_PAGES = 40
MAX_PAGE_SIDE = 5000  # points (1 pt = 1/72 inch); A0 poster is about 3400, A4 is 842
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
class AuditError(Exception):
    pass


def safe(criteria, fn, *args):
    try:
        return fn(*args)
    except Exception:
        return [Finding(c, CANNOT_TELL, "This check could not run on this file.", severity="low") for c in criteria]


def run_audit(data, use_ai=False, with_highlights=True):
    try:
        pdf = pikepdf.open(io.BytesIO(data))
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise AuditError("The file could not be read as a valid, unencrypted PDF.")
    if doc.page_count == 0:
        raise AuditError("The PDF has no pages.")
    n = min(doc.page_count, MAX_PAGES)
    for pno in range(n):
        r = doc[pno].rect
        if max(r.width, r.height) > MAX_PAGE_SIDE:
            raise AuditError("Page %d is far larger than any normal page size, so this file was not audited." % (pno + 1))

    findings = safe(["language", "title", "bookmarks"], check_document, pdf, doc.page_count)
    try:
        layer, scanned = check_text_layer(doc, n)
    except Exception:
        layer, scanned = [Finding("text_layer", CANNOT_TELL, "This check could not run on this file.", severity="low")], set()
    findings += layer
    try:
        tagged = is_tagged(pdf)
    except Exception:
        tagged = False
    try:
        structure, tagged = check_structure(pdf, doc, n, scanned, use_ai)
    except Exception:
        structure = [Finding(c, CANNOT_TELL, "This check could not run on this file.", severity="low")
                     for c in ("semantic_tags", "alt_text", "table_structure")]
    findings += structure
    findings += safe(["reading_order"], check_reading_order, doc, n, scanned, tagged)
    findings += safe(["color_contrast"], check_contrast, doc, n, scanned)
    findings += safe(["font_readability"], check_fonts, doc, n, scanned)
    findings += safe(["links"], check_links, doc, n, scanned)

    statuses = rollup(findings)
    value = score(statuses)
    problems = [f for f in findings if f.status != "Passed" and f.status != "Not Present"]
    problems.sort(key=lambda f: (f.status != FAILED, SEVERITY_ORDER.get(f.severity, 3)))

    result = {
        "score": value,
        "grade": grade(value),
        "pages": doc.page_count,
        "pages_checked": n,
        "tagged": tagged,
        "ai_used": any(f.source == "ai" for f in findings),
        "criteria": [{"id": k, "label": CRITERIA[k][0], "status": statuses[k]} for k in CRITERIA],
        "findings": [f.to_dict() for f in problems],
        "highlights": highlight_pages(data, problems) if with_highlights else {},
    }
    doc.close()
    pdf.close()
    return result


def summarize(name, data):
    start = time.time()
    try:
        r = run_audit(data, use_ai=False, with_highlights=False)
    except AuditError as e:
        return {"file": name, "error": str(e)}
    return {
        "file": name,
        "score": r["score"],
        "grade": r["grade"],
        "pages": r["pages"],
        "criteria": {c["id"]: c["status"] for c in r["criteria"]},
        "top_findings": [f["message"] for f in r["findings"][:5]],
        "seconds": round(time.time() - start, 2),
    }


def summarize_item(item):
    return summarize(item[0], item[1])

