import asyncio
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
total = int(sys.argv[2]) if len(sys.argv) > 2 else 60
concurrency = int(sys.argv[3]) if len(sys.argv) > 3 else 6
pdf_path = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("backend/tests/samples/good_tagged.pdf")
data = pdf_path.read_bytes()


async def one(client, sem, results):
    async with sem:
        start = time.time()
        try:
            r = await client.post(url + "/api/audit", files={"file": ("test.pdf", data, "application/pdf")})
            results.append((r.status_code, r.headers.get("x-served-by", "?"), time.time() - start))
        except Exception:
            results.append((0, "error", time.time() - start))


async def main():
    results = []
    sem = asyncio.Semaphore(concurrency)
    begin = time.time()
    async with httpx.AsyncClient(timeout=120) as client:
        await asyncio.gather(*[one(client, sem, results) for _ in range(total)])
    wall = time.time() - begin
    lat = sorted(r[2] for r in results)
    print("requests: %d, concurrency: %d, wall time: %.2fs, throughput: %.1f req/s" % (total, concurrency, wall, total / wall))
    print("status codes:", dict(Counter(r[0] for r in results)))
    print("latency p50 %.2fs, p95 %.2fs, max %.2fs" % (lat[len(lat) // 2], lat[int(len(lat) * 0.95) - 1], lat[-1]))
    print("requests per instance:")
    for name, count in sorted(Counter(r[1] for r in results).items()):
        print("  %-12s %d" % (name, count))


asyncio.run(main())
