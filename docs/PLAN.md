# Project plan: PDF Accessibility Auditor (CA 3 Mini Project, CO4 and CO5)

Course: TE7948 Introduction to Cloud Computing. Deadline: 13 October 2026.

## 1. Problem and positioning

Public notices, circulars and college documents are often published as PDFs that blind and low-vision users cannot read with a screen reader. This project is a cloud-hosted auditor that takes a PDF and returns a score, a per-criterion verdict, highlighted problem areas and concrete fixes.

### Honest novelty check

A September 2025 benchmark paper (arXiv 2509.18965, Kumar, Padath, Wang) already annotates scholarly PDFs on seven criteria (alt text quality, reading order, semantic tagging, table structure, links, color contrast, font readability), defines four labels (Passed, Failed, Not Present, Cannot Tell), benchmarks five LLMs and proposes a hybrid of checkers, LLMs and human review as future work. So "hybrid rule plus AI" alone is not a defensible novelty claim.

What this project adds:

1. It builds and deploys the hybrid as a working system, which that paper leaves as future work.
2. It targets Indian public and educational documents: scanned notices with no text layer, legacy Hindi fonts that read as gibberish, Word-export filenames used as titles.
3. It reuses the four-label scheme so results are comparable.
4. A small annotated set of real Indian public and college PDFs (to be collected).

Suggested honest novelty rating: about 6 out of 10.

## 2. Scope

In scope: upload, rule checks, optional AI check for alt text quality, scoring, highlighted pages, SSO, security posture, metrics, load balancing demonstration, parallel batch audits, deployment on Render, CI/CD with security scans.

Out of scope: automatically fixing PDFs, full WCAG or PDF/UA certification, OCR, tag-tree reading order (future work).

## 3. Architecture

Single Docker container (FastAPI) serving the API and the static frontend, deployed as a Render web service on public cloud infrastructure.

- Frontend: plain HTML, CSS and JS, built to be accessible itself.
- Backend modules: document, structure, layout, visual and links checks, scoring, highlights, SSO (auth), posture (CSPM), metrics.
- Semantic layer: heuristic alt text rules plus an optional, opt-in LLM check.
- Stateless design: signed cookie sessions and no stored files, so the service scales horizontally.
- Load balancing: Render's platform load balancer in production, nginx with three instances in docker-compose for the demonstration.

## 4. Syllabus mapping

| Unit | Topic | Where it appears |
|---|---|---|
| 1 | SaaS, PaaS, IaaS, deployment models | The tool is delivered as SaaS, hosted on a PaaS (Render), public cloud deployment model |
| 2 | Virtualization, containers | Docker image, container isolation, non-root user |
| 3 | Multi-tier architecture, SOA, parallelization | Frontend, API and processing tiers, REST API, process-pool batch audits |
| 4 | Cloud security, CSPM, SSO | docs/SECURITY.md, /api/posture, Google OIDC login, CI scans |
| 5 | HPC, load balancing, resource utilization | nginx load balancer experiment, /api/metrics, concurrency limits, parallel benchmark |

## 5. Remaining schedule

| Date | Goal |
|---|---|
| 8 Oct | Push to GitHub, deploy on Render, confirm the live URL works, take screenshots |
| 9 Oct | Configure Google SSO, set the GitHub secrets so CI/CD deploys, collect 20 to 40 real PDFs |
| 10 Oct | Run the audit on the real PDFs, fix false positives, label results by hand |
| 11 Oct | Evaluation (rule-only versus hybrid), parallel benchmark, load test against the Render URL, collect screenshots |
| 12 Oct | Write the report |
| 13 Oct | Buffer, final check, submit |

## 6. Evaluation plan

- Ground truth: manual four-label verdicts per criterion on the collected PDFs. Ask a second person to label a subset and report agreement (Cohen's kappa).
- Systems: rule-only (AI off) versus hybrid (AI on). An LLM-only baseline is optional.
- Metrics: per-criterion accuracy, precision and recall for Failed.

## 7. Mapping to the rubric (10 marks)

| Rubric item | Marks | Evidence |
|---|---|---|
| Design, setup and configuration | 2 | Modular repo, README, architecture diagram, tests, Docker, Blueprint file |
| Implementation and cloud deployment | 3 | Live Render URL with no errors, CD pipeline, health check, SSO, status page |
| Report with CI/CD and GitHub link | 5 | Problem, novelty with literature table, cloud setup steps, security (docs/SECURITY.md), CI/CD screenshots, load balancing and evaluation results |

## 8. Risks

- Render free instances sleep and have limited memory, so open the URL before a demo and keep documents modest.
- SSO needs an OAuth client set up in Google Cloud Console, allow time for it.
- Annotation effort is the biggest time cost, cap the dataset at what you can label well.
- Tagged PDFs with out-of-order content stream are reported as Cannot Tell until tag-tree parsing is added.
- Verify legal and guideline references (RPwD Act 2016, GIGW 3.0) before citing them.
