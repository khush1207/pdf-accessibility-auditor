"""All accessibility rules. Each check returns a list of Finding objects.

Sections: data model, tag-tree reader, document, text layer and structure,
reading order, links, visual (contrast and fonts).
"""
import re

import numpy as np
import pikepdf
import pymupdf
from dataclasses import dataclass, asdict
from typing import Optional

from . import semantic


# Rendering a page to an image costs memory in proportion to its area, so every
# render is scaled down to this pixel budget (6 million pixels is about 18 MB as RGB).
MAX_RENDER_PIXELS = 6_000_000


def safe_zoom(page, wanted):
    """The zoom to render a page at: the wanted zoom, reduced for very large pages."""
    area = max(page.rect.width * page.rect.height, 1)
    return min(wanted, (MAX_RENDER_PIXELS / area) ** 0.5)

# ----------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------

PASSED = "Passed"
FAILED = "Failed"
NOT_PRESENT = "Not Present"
CANNOT_TELL = "Cannot Tell"


@dataclass
class Finding:
    criterion: str
    status: str
    message: str
    fix: str = ""
    page: Optional[int] = None
    bbox: Optional[tuple] = None
    severity: str = "medium"
    source: str = "rule"

    def to_dict(self):
        return asdict(self)


# ----------------------------------------------------------------------
# Tag tree reader
# ----------------------------------------------------------------------

def resolve_role(elem, rolemap):
    role = str(elem.get("/S", ""))
    seen = set()
    while role in rolemap and role not in seen:
        seen.add(role)
        role = str(rolemap[role])
    return role.lstrip("/")


def collect(pdf):
    root = pdf.Root.get("/StructTreeRoot")
    if root is None:
        return []
    rolemap = {}
    if "/RoleMap" in root:
        rolemap = {str(k): v for k, v in root.RoleMap.items()}
    page_index = {p.objgen: i for i, p in enumerate(pdf.pages)}
    records = []

    def visit(node, page, depth):
        """Returns (roles found below this node, pages found below this node)."""
        roles, pages = set(), set()
        if depth > 80:
            return roles, pages
        if isinstance(node, pikepdf.Array):
            for child in node:
                r, p = visit(child, page, depth + 1)
                roles |= r
                pages |= p
        elif isinstance(node, pikepdf.Dictionary):
            # Any node (a tag or a content reference) can carry the page it sits on
            pg = node.get("/Pg")
            if pg is not None and pg.objgen in page_index:
                page = page_index[pg.objgen]
                pages.add(page)
            if "/S" in node:
                role = resolve_role(node, rolemap)
                alt = str(node["/Alt"]).strip() if "/Alt" in node else ""
                actual = str(node["/ActualText"]).strip() if "/ActualText" in node else ""
                rec = {"role": role, "alt": alt, "actual": actual, "page": page, "below": set()}
                records.append(rec)
                if "/K" in node:
                    rec["below"], below_pages = visit(node["/K"], page, depth + 1)
                    pages |= below_pages
                    if rec["page"] is None and below_pages:
                        rec["page"] = min(below_pages)  # take the first page of its content
                roles = rec["below"] | {role}
            elif "/K" in node:
                r, p = visit(node["/K"], page, depth + 1)
                roles |= r
                pages |= p
        return roles, pages

    visit(root.get("/K"), None, 0)
    return records


# ----------------------------------------------------------------------
# Document checks: language, title, bookmarks
# ----------------------------------------------------------------------

BAD_TITLES = {"", "untitled", "(anonymous)", "none", "title"}


def title_is_bad(title):
    t = title.strip().lower()
    return t in BAD_TITLES or t.startswith("microsoft word -") or re.search(r"\.(docx?|indd|pptx?|pdf)$", t) is not None


def check_document(pdf, page_count):
    out = []
    lang = str(pdf.Root.get("/Lang", "")).strip()
    if lang:
        out.append(Finding("language", PASSED, "Document language is set to " + lang + "."))
    else:
        out.append(Finding("language", FAILED, "Document language is not set, so screen readers may use the wrong voice.",
                           "Set the document language (for example en-IN or hi-IN) in the export or properties dialog.",
                           severity="high"))

    title = str(pdf.docinfo.get("/Title", "")) if pdf.docinfo is not None else ""
    if title_is_bad(title):
        out.append(Finding("title", FAILED, "Document has no meaningful title.",
                           "Add a descriptive title in the document properties and show it in the title bar.",
                           severity="medium"))
    else:
        out.append(Finding("title", PASSED, "Document title is set."))

    if page_count > 5:
        if "/Outlines" in pdf.Root:
            out.append(Finding("bookmarks", PASSED, "Bookmarks are present for navigation."))
        else:
            out.append(Finding("bookmarks", FAILED, "Long document without bookmarks.",
                               "Add bookmarks that follow the heading structure.", severity="low"))
    else:
        out.append(Finding("bookmarks", NOT_PRESENT, "Document is short, bookmarks are not required."))
    return out


# ----------------------------------------------------------------------
# Structure checks: text layer, tags, alt text, tables
# ----------------------------------------------------------------------

MIN_IMAGE_AREA = 1500
HEADINGS = {"H1": 1, "H2": 2, "H3": 3, "H4": 4, "H5": 5, "H6": 6}
MAX_AI_FIGURES = 5


def is_tagged(pdf):
    mark = pdf.Root.get("/MarkInfo")
    marked = bool(mark is not None and mark.get("/Marked", False))
    return marked and "/StructTreeRoot" in pdf.Root


def check_text_layer(doc, n):
    scanned = set()
    for pno in range(n):
        page = doc[pno]
        if len(page.get_text("words")) < 3:
            area = sum(pymupdf.Rect(i["bbox"]).get_area() for i in page.get_image_info())
            if area > 0.6 * page.rect.get_area():
                scanned.add(pno)
    if not scanned:
        return [Finding("text_layer", PASSED, "Every page has selectable text.")], scanned
    pages = ", ".join(str(p + 1) for p in sorted(scanned)[:10])
    f = Finding("text_layer", FAILED, "Pages " + pages + " look like scanned images with no text layer.",
                "Run OCR on the scan, or export the original document to PDF instead of scanning it.", severity="high")
    return [f], scanned


def page_images(doc, n, scanned):
    found = []
    for pno in range(n):
        if pno in scanned:
            continue
        for info in doc[pno].get_image_info():
            r = pymupdf.Rect(info["bbox"])
            if r.get_area() >= MIN_IMAGE_AREA:
                found.append((pno, tuple(round(v, 1) for v in r)))
    return found


def tag_findings(tagged, records, n):
    if not tagged:
        return [Finding("semantic_tags", FAILED, "Document is not tagged, so screen readers get no structure.",
                        "Export from the source application with Tagged PDF enabled, or tag it in Acrobat.",
                        severity="high")]
    heads = [HEADINGS[r["role"]] for r in records if r["role"] in HEADINGS]
    if not records:
        return [Finding("semantic_tags", FAILED, "Tag tree is empty.", "Re-export the document with tags.", severity="high")]
    if n > 1 and not heads:
        return [Finding("semantic_tags", FAILED, "Document is tagged but has no headings.",
                        "Apply heading styles in the source document before exporting.", severity="medium")]
    for a, b in zip(heads, heads[1:]):
        if b > a + 1:
            return [Finding("semantic_tags", FAILED, "Heading level jumps from H%d to H%d." % (a, b),
                            "Use heading levels in order without skipping.", severity="medium")]
    return [Finding("semantic_tags", PASSED, "Tags and heading hierarchy look valid.")]


def alt_findings(doc, tagged, records, images, use_ai, n):
    figures = [
    r for r in records
    if r["role"] == "Figure"
    and r["page"] is not None
    and 0 <= r["page"] < n
]
    if not images and not figures:
        return [Finding("alt_text", NOT_PRESENT, "No informative images found.")]
    out = []
    if not tagged:
        for pno, bbox in images[:8]:
            out.append(Finding("alt_text", FAILED, "Image cannot have alternative text because the document is untagged.",
                               "Tag the document, then add alternative text or mark decorative images as artifacts.",
                               page=pno, bbox=bbox, severity="high"))
        return out
    if len(images) > len(figures):
        out.append(Finding("alt_text", FAILED, "%d images are not tagged as figures." % (len(images) - len(figures)),
                           "Tag informative images as figures, mark decorative ones as artifacts.", severity="high"))
    ai_used = 0
    for fig in figures:
        if fig["page"] is not None and fig["page"] >= len(doc):
            continue
        alt = fig["alt"] or fig["actual"]
        if not alt:
            out.append(Finding("alt_text", FAILED, "Figure has no alternative text.",
                               "Add a short description of what the figure shows.", page=fig["page"], severity="high"))
            continue
        png = None
        if use_ai and ai_used < MAX_AI_FIGURES and fig["page"] is not None:
            page_obj = doc[fig["page"]]
            z = safe_zoom(page_obj, 1.2)
            png = page_obj.get_pixmap(matrix=pymupdf.Matrix(z, z)).tobytes("png")
            ai_used += 1
        label, reason, source = semantic.rate_alt_text(alt, png, use_ai)
        out.append(Finding("alt_text", label, reason, "" if label == "Passed" else "Rewrite the alternative text to describe the content or purpose of the image.",
                           page=fig["page"], severity="medium", source=source))
    return out or [Finding("alt_text", PASSED, "All figures have alternative text.")]


def table_findings(doc, n, scanned, tagged, records):
    tables = [r for r in records if r["role"] == "Table"]
    visual = []
    if not tables or not tagged:
        for pno in range(min(n, 12)):
            if pno in scanned:
                continue
            if len(doc[pno].get_drawings()) < 6:
                continue
            try:
                for t in doc[pno].find_tables().tables:
                    visual.append((pno, tuple(round(v, 1) for v in t.bbox)))
            except Exception:
                continue
    if not tables and not visual:
        return [Finding("table_structure", NOT_PRESENT, "No tables found.")]
    if not tagged or (visual and not tables):
        pno, bbox = visual[0]
        return [Finding("table_structure", FAILED, "A table is drawn on the page but is not tagged as a table.",
                        "Tag the table with header and data cells.", page=pno, bbox=bbox, severity="high")]
    out = []
    for t in tables:
        if "TR" not in t["below"] or "TH" not in t["below"]:
            out.append(Finding("table_structure", FAILED, "Table has no header cells marked.",
                               "Mark the first row or column as header cells (TH).", page=t["page"], severity="medium"))
    return out or [Finding("table_structure", PASSED, "Tables have rows and header cells.")]


def check_structure(pdf, doc, n, scanned, use_ai=False):
    tagged = is_tagged(pdf)
    records = collect(pdf) if tagged else []
    images = page_images(doc, n, scanned)
    out = tag_findings(tagged, records, n)
    out += alt_findings(doc, tagged, records, images, use_ai, n)
    out += table_findings(doc, n, scanned, tagged, records)
    return out, tagged


# ----------------------------------------------------------------------
# Reading order
# ----------------------------------------------------------------------

DISORDER_LIMIT = 0.15


def geometric_rank(blocks, width):
    mid = width / 2
    kind = []
    for b in blocks:
        x0, y0, x1, y1 = b[:4]
        if x1 <= mid + 10:
            kind.append(0)
        elif x0 >= mid - 10:
            kind.append(1)
        else:
            kind.append(2)
    keys = []
    for i, b in enumerate(blocks):
        above = sum(1 for j, o in enumerate(blocks) if kind[j] == 2 and j != i and o[3] <= b[1] + 1)
        keys.append((above, kind[i], b[1], b[0]))
    order = sorted(range(len(blocks)), key=lambda i: keys[i])
    rank = [0] * len(blocks)
    for r, i in enumerate(order):
        rank[i] = r
    return rank


def disorder(rank):
    n = len(rank)
    pairs = n * (n - 1) / 2
    inv = sum(1 for i in range(n) for j in range(i + 1, n) if rank[i] > rank[j])
    return inv / pairs if pairs else 0


def check_reading_order(doc, n, scanned, tagged):
    worst = None
    judged = 0
    for pno in range(min(n, 30)):
        if pno in scanned:
            continue
        page = doc[pno]
        blocks = [b for b in page.get_text("blocks") if b[6] == 0 and len(b[4].strip()) >= 15]
        if len(blocks) < 4:
            continue
        judged += 1
        d = disorder(geometric_rank(blocks, page.rect.width))
        if d > DISORDER_LIMIT and (worst is None or d > worst[0]):
            first = next(b for i, b in enumerate(blocks) if i > 0)
            worst = (d, pno, tuple(round(v, 1) for v in first[:4]))
    if judged == 0:
        return [Finding("reading_order", NOT_PRESENT, "Too little text to judge reading order.")]
    if worst is None:
        return [Finding("reading_order", PASSED, "Content order matches the visual order.")]
    d, pno, bbox = worst
    if tagged:
        return [Finding("reading_order", CANNOT_TELL,
                        "Content stream order differs from visual order on page %d. The tag tree may still be correct, check it manually." % (pno + 1),
                        page=pno, bbox=bbox, severity="medium")]
    return [Finding("reading_order", FAILED,
                    "Text is stored in a different order than it appears (page %d), so screen readers will read it jumbled." % (pno + 1),
                    "Tag the document and fix the reading order, or re-export from the source with columns defined properly.",
                    page=pno, bbox=bbox, severity="high")]


# ----------------------------------------------------------------------
# Links
# ----------------------------------------------------------------------

GENERIC = {"click here", "here", "link", "read more", "more", "this link", "click", "download"}


def check_links(doc, n, scanned):
    total = 0
    out = []
    for pno in range(min(n, 30)):
        if pno in scanned:
            continue
        page = doc[pno]
        for link in page.get_links():
            if link.get("kind") != pymupdf.LINK_URI:
                continue
            total += 1
            rect = pymupdf.Rect(link["from"])
            text = page.get_textbox(rect).strip()
            bbox = tuple(round(v, 1) for v in rect)
            if not text:
                out.append(Finding("links", CANNOT_TELL, "Link has no visible text, it may be an image link without a label.",
                                   page=pno, bbox=bbox, severity="low"))
            elif text.lower().strip(".:") in GENERIC:
                out.append(Finding("links", FAILED, "Link text '%s' does not say where the link goes." % text,
                                   "Use descriptive text such as the name of the page or document.",
                                   page=pno, bbox=bbox, severity="medium"))
            elif text.lower().startswith("http") and len(text) > 45:
                out.append(Finding("links", FAILED, "A long raw URL is used as link text.",
                                   "Replace the URL with a short descriptive label.", page=pno, bbox=bbox, severity="low"))
    if total == 0:
        return [Finding("links", NOT_PRESENT, "No hyperlinks found.")]
    return out or [Finding("links", PASSED, "Link text is descriptive.")]


# ----------------------------------------------------------------------
# Visual checks: contrast and fonts
# ----------------------------------------------------------------------

LEGACY_HINTS = ("kruti", "devlys", "chanakya", "walkman", "shusha")
BASE14 = ("helvetica", "times", "courier", "symbol", "zapfdingbats", "arial")
SMALL_PT = 9
MAX_SPANS = 120


def luminance(rgb):
    def f(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast_ratio(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def int_to_rgb(c):
    return ((c >> 16) & 255, (c >> 8) & 255, c & 255)


def background(arr, bbox, zoom):
    x0, y0, x1, y1 = [int(v * zoom) for v in bbox]
    h, w = arr.shape[:2]
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    crop = arr[y0:y1, x0:x1, :3].astype(np.int32) // 4
    packed = (crop[..., 0] << 12 | crop[..., 1] << 6 | crop[..., 2]).ravel()
    vals, counts = np.unique(packed, return_counts=True)
    top = int(vals[counts.argmax()])
    return (((top >> 12) & 63) * 4 + 2, ((top >> 6) & 63) * 4 + 2, (top & 63) * 4 + 2)


def check_contrast(doc, n, scanned):
    zoom = 1.5
    worst_pages = []
    judged = 0
    for pno in range(min(n, 30)):
        if pno in scanned:
            continue
        page = doc[pno]
        spans = []
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for line in b["lines"]:
                for s in line["spans"]:
                    if s["text"].strip() and s["size"] >= 4:
                        spans.append(s)
        if not spans:
            continue
        zoom = safe_zoom(page, 1.5)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        bad = []
        for s in spans[:MAX_SPANS]:
            bg = background(arr, s["bbox"], zoom)
            if bg is None:
                continue
            judged += 1
            large = s["size"] >= 18 or (s["size"] >= 14 and s["flags"] & 16)
            need = 3.0 if large else 4.5
            ratio = contrast_ratio(int_to_rgb(s["color"]), bg)
            if ratio < need:
                bad.append((ratio, s))
        if bad:
            bad.sort(key=lambda x: x[0])
            worst_pages.append((pno, len(bad), bad[0]))
    if judged == 0:
        return [Finding("color_contrast", NOT_PRESENT, "No text to measure contrast on.")]
    if not worst_pages:
        return [Finding("color_contrast", PASSED, "Text meets WCAG contrast ratios.")]
    out = []
    for pno, count, (ratio, s) in worst_pages[:6]:
        out.append(Finding("color_contrast", FAILED,
                           "%d text spans on page %d are below the required contrast (lowest %.1f:1)." % (count, pno + 1, ratio),
                           "Darken the text or lighten the background to reach at least 4.5:1 for body text.",
                           page=pno, bbox=tuple(round(v, 1) for v in s["bbox"]), severity="medium"))
    return out


def check_fonts(doc, n, scanned):
    small = total = 0
    small_first = None
    garbled = 0
    legacy = set()
    unembedded = set()
    for pno in range(min(n, 60)):
        if pno in scanned:
            continue
        page = doc[pno]
        for f in page.get_fonts():
            ext, base = f[1], f[3].split("+")[-1].lower()
            if any(h in base for h in LEGACY_HINTS):
                legacy.add(f[3].split("+")[-1])
            elif ext == "n/a" and not base.startswith(BASE14):
                unembedded.add(f[3].split("+")[-1])
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for line in b["lines"]:
                for s in line["spans"]:
                    k = len(s["text"].strip())
                    total += k
                    garbled += s["text"].count("\ufffd") + s["text"].count("(cid:")
                    if k and s["size"] < SMALL_PT:
                        small += k
                        if small_first is None:
                            small_first = (pno, tuple(round(v, 1) for v in s["bbox"]))
    if total == 0:
        return [Finding("font_readability", NOT_PRESENT, "No text to assess fonts on.")]
    out = []
    if legacy:
        out.append(Finding("font_readability", FAILED,
                           "Legacy Hindi font detected (%s). Screen readers and search will read this text as gibberish." % ", ".join(sorted(legacy)),
                           "Re-type or convert the text to Unicode Devanagari and re-export.", severity="high"))
    if garbled:
        out.append(Finding("font_readability", FAILED, "Some characters cannot be mapped to readable text.",
                           "Embed the fonts properly or re-export with Unicode text.", severity="high"))
    if small / total > 0.2:
        pno, bbox = small_first
        out.append(Finding("font_readability", FAILED, "%d%% of the text is smaller than %d pt." % (100 * small / total, SMALL_PT),
                           "Use at least 10 to 12 pt for body text.", page=pno, bbox=bbox, severity="medium"))
    if unembedded:
        out.append(Finding("font_readability", FAILED, "Fonts not embedded: %s." % ", ".join(sorted(unembedded)[:4]),
                           "Embed all fonts when exporting.", severity="low"))
    return out or [Finding("font_readability", PASSED, "Fonts are embedded and text size is readable.")]
