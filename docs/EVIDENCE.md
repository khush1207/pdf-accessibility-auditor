# Measured evidence (collected while building)

These numbers were measured in the build sandbox (1 CPU, Linux). Re-run them on your own machine and in the deployed service and use your numbers in the report.

## Test suite

25 automated tests pass (pytest): rule checks on good, bad and scanned PDFs, contrast maths, reading order logic, AI fallback behaviour, upload validation, rate limiting, SSO gating, posture, metrics, busy handling and batch audits.

## Static analysis and dependency scan

- bandit, medium and high severity: no issues. Two low severity notes for intentional try/except handlers.
- pip-audit on requirements.txt: no known vulnerabilities at the time of the run.

## Performance fix

Synthetic 40 page PDF with tables, whole-document audit:

| Version | Time |
|---|---|
| Before optimizing contrast sampling and table detection | 23.1 s |
| After | 1.8 s |

Results were identical before and after (same score and criteria), only the speed changed.

## Load balancing experiment

Three uvicorn instances on one machine behind nginx (round robin, max_fails 2, fail_timeout 10 s). Load: 60 audit requests, concurrency 6, using `scripts/load_test.py`.

| Scenario | Requests per instance | Status codes |
|---|---|---|
| All three up | app1 19, app2 20, app3 21 | 60 x 200 |
| app2 killed | app1 30, app3 30 | 60 x 200, no failed requests |
| app2 restarted, tested immediately | app1 30, app3 30 | 60 x 200, app2 not yet back |
| app2 restarted, tested after the fail timeout | app1 21, app2 18, app3 21 | all 200 |

Throughput was about 38 to 45 requests per second on a single CPU, which says little about a real deployment. The point of the experiment is distribution and failover, not speed. The same script works against the Render URL.

## Still to collect on your side

- Screenshots of the Render dashboard, the live app, the Platform status view and the GitHub Actions run.
- Parallel speedup table from `scripts/benchmark_parallel.py` on a multi-core machine.
- Accuracy results on your own set of real PDFs, rule-only versus hybrid.
