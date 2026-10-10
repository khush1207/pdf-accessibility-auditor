import io
import sys
from pathlib import Path

import pikepdf
from PIL import Image, ImageDraw
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("backend/tests/samples")
OUT.mkdir(parents=True, exist_ok=True)

LOREM = ("The college will conduct the semester examination according to the notified schedule. "
         "Students must carry their identity card and hall ticket to every session. ")


def chart_png(path):
    img = Image.new("RGB", (400, 220), "white")
    d = ImageDraw.Draw(img)
    for i, h in enumerate([60, 110, 90, 160]):
        d.rectangle([40 + i * 85, 200 - h, 100 + i * 85, 200], fill=(40, 90, 160))
    img.save(path)


def make_bad(path):
    chart_png("/tmp/chart.png")
    W, H = A4
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(60, H - 60, "Notice for all students")
    c.setFont("Helvetica", 11)
    for col_x in (320, 60):
        y = H - 120
        for p in range(3):
            for line in range(3):
                c.drawString(col_x, y, LOREM[line * 30: line * 30 + 40])
                y -= 14
            y -= 30
    c.drawImage("/tmp/chart.png", 60, 300, width=200, height=110)
    c.setFillColor(colors.Color(0.8, 0.8, 0.8))
    c.setFont("Helvetica", 7)
    y = 270
    for i in range(10):
        c.drawString(60, y, "Fine print: the exact conditions are listed in the circular, line %d." % i)
        y -= 9
    c.setFillColor(colors.blue)
    c.setFont("Helvetica", 11)
    c.drawString(60, 150, "click here")
    c.linkURL("https://example.org/circular", (60, 145, 120, 162))
    c.save()


def make_scanned(path):
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    for i in range(12):
        d.text((100, 150 + i * 40), "Scanned notice line %d about admissions" % i, fill="black")
    img.save("/tmp/scan.png")
    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawImage("/tmp/scan.png", 0, 0, width=A4[0], height=A4[1])
    c.save()


def make_good(path):
    chart_png("/tmp/chart.png")
    styles = getSampleStyleSheet()
    tmp = io.BytesIO()
    doc = SimpleDocTemplate(tmp, pagesize=A4, title="Examination circular 2026")
    story = [Paragraph("Examination circular", styles["Heading1"]),
             Paragraph(LOREM * 3, styles["Normal"]), Spacer(1, 14),
             Paragraph("Attendance summary", styles["Heading2"]),
             RLImage("/tmp/chart.png", width=240, height=132), Spacer(1, 14)]
    t = Table([["Class", "Present", "Absent"], ["B1", "52", "3"], ["B2", "49", "6"]])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    story += [t, Spacer(1, 14), Paragraph(LOREM * 2, styles["Normal"])]
    doc.build(story)
    tmp.seek(0)

    pdf = pikepdf.open(tmp)
    page = pdf.pages[0]

    def elem(role, parent, kids=None, **extra):
        d = pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name("/" + role), P=parent, Pg=page.obj, **extra)
        if kids is not None:
            d.K = pikepdf.Array(kids)
        return pdf.make_indirect(d)

    root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
    document = elem("Document", root)
    h1 = elem("H1", document)
    p1 = elem("P", document)
    h2 = elem("H2", document)
    fig = elem("Figure", document, Alt=pikepdf.String("Bar chart of student attendance for four classes"))
    table = elem("Table", document)
    rows = []
    for cells in (["TH", "TH", "TH"], ["TD", "TD", "TD"], ["TD", "TD", "TD"]):
        tr = elem("TR", table)
        tr.K = pikepdf.Array([elem(role, tr) for role in cells])
        rows.append(tr)
    table.K = pikepdf.Array(rows)
    document.K = pikepdf.Array([h1, p1, h2, fig, table])
    root.K = pikepdf.Array([document])
    pdf.Root.StructTreeRoot = root
    pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
    pdf.Root.Lang = pikepdf.String("en-IN")
    pdf.save(path)


if __name__ == "__main__":
    make_bad(OUT / "bad_untagged.pdf")
    make_good(OUT / "good_tagged.pdf")
    make_scanned(OUT / "scanned.pdf")
    print("samples written to", OUT)
