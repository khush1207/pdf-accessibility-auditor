# PDF Accessibility Auditor

Upload a PDF and get an accessibility score, a verdict per criterion, highlighted problem pages and suggested fixes. Rule-based checks cover tags, headings, tables, reading order, contrast, fonts, links, language, title and scanned pages. An optional AI check judges alternative text quality.

Each criterion uses four labels: Passed, Failed, Not Present, Cannot Tell.

Cloud features (course units 4 and 5): Google single sign-on, a security posture endpoint, instance metrics, concurrency and rate limits, parallel batch audits, and a load-balancer demonstration.

## Run locally

```
pip install -r backend/requirements-dev.txt
python scripts/make_samples.py
cd backend
pytest
uvicorn app.main:app --reload
```

Open http://localhost:8000. Status view: click Platform status in the top bar. API docs (local only): http://localhost:8000/docs.

## Run with Docker, three instances behind nginx

```
docker compose up --build
python scripts/load_test.py http://localhost:8080 60 6
```

The load test prints how many requests each instance served.

## Deploy

See docs/DEPLOY.md (Render, CI/CD, SSO setup).

## Layout

```
backend/app/main.py      API routes, upload limits, rate limit, security headers
backend/app/audit.py     runs every check, scoring, highlighted pages
backend/app/checks.py    all accessibility rules (tags, alt text, tables, order, links, contrast, fonts)
backend/app/semantic.py  alt text quality: rules plus optional AI call
backend/app/cloud.py     Google SSO, security posture, instance metrics
frontend/index.html      the whole page: audit, batch and status views, plus styles
frontend/app.js          all browser code
deploy/                  nginx load balancer configs
scripts/                 sample PDFs, load test, parallel benchmark
docs/                    PLAN, DEPLOY, SECURITY, EVIDENCE
render.yaml              Render blueprint
.github/workflows/       CI/CD: tests, security scans, build, deploy
```
