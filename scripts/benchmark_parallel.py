import sys
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import cpu_count, get_context
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.audit import summarize_item  # noqa: E402


def make_files(count, pages):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    import io
    styles = getSampleStyleSheet()
    out = []
    for i in range(count):
        buf = io.BytesIO()
        story = []
        for p in range(pages):
            story.append(Paragraph("Notice %d section %d" % (i, p), styles["Heading1"]))
            for _ in range(10):
                story.append(Paragraph("The college will conduct the examination as per the notified schedule. " * 6, styles["Normal"]))
                story.append(Spacer(1, 6))
        SimpleDocTemplate(buf, pagesize=A4, title="Benchmark %d" % i).build(story)
        out.append(("doc%d.pdf" % i, buf.getvalue()))
    return out


def load_folder(folder):
    return [(p.name, p.read_bytes()) for p in sorted(Path(folder).glob("*.pdf"))]


def run_sequential(items):
    start = time.time()
    for it in items:
        summarize_item(it)
    return time.time() - start


def run_parallel(items, workers):
    ctx = get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
        list(pool.map(summarize_item, items[:workers]))
        start = time.time()
        list(pool.map(summarize_item, items))
        return time.time() - start


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else None
    items = load_folder(folder) if folder else make_files(8, 15)
    print("documents: %d, logical CPUs: %d" % (len(items), cpu_count()))
    base = run_sequential(items)
    print("%-10s %8s %9s %11s" % ("workers", "seconds", "speedup", "efficiency"))
    print("%-10s %8.2f %9.2f %10.0f%%" % ("1 (seq)", base, 1.0, 100))
    for w in (2, 4):
        if w > cpu_count():
            continue
        t = run_parallel(items, w)
        print("%-10d %8.2f %9.2f %10.0f%%" % (w, t, base / t, 100 * base / t / w))
