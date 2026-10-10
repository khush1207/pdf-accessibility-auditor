I'm Kavan, a third-year AI & ML student at Symbiosis Institute of Technology (SIT), Pune. I'm continuing a project from another Claude account, so please read this fully and continue from where it stands instead of starting over. I'll upload the project zip (pdf-access-auditor.zip) with this message.

COURSE AND DEADLINE
- Course TE7948 Introduction to Cloud Computing, CA 3 Mini Project (CO4 and CO5), 10 marks.
- Rubric: Design, setup and configuration [2]; Implementation and cloud deployment [3] (fully deployed with no errors, clear deployment steps); Report [5] (detailed report explaining the project, cloud setup and CI/CD configuration, with a GitHub link).
- Deadline: 13 October 2026.
- Syllabus Unit 4 (cloud security, CSPM, SSO) and Unit 5 (HPC on cloud, load balancing and resource utilization) should be clearly visible in the project and the report.

PROJECT
PDF Accessibility Auditor: a cloud-hosted app that audits public and educational PDFs for accessibility (tags, headings, alt text, tables, reading order, contrast, fonts, links, language, title, scanned pages, legacy Hindi fonts) and returns a score, per-criterion verdict (Passed, Failed, Not Present, Cannot Tell), highlighted pages and fixes. Optional AI check for alt text quality (opt-in).
Novelty, honestly: about 6 out of 10. arXiv 2509.18965 already benchmarks LLMs on the same seven criteria and proposes a hybrid as future work. Our contribution is building and deploying the hybrid, targeting Indian public and college documents, and a small annotated dataset. Do not inflate the novelty claim.

CURRENT STATE (in the zip)
- FastAPI backend plus accessible HTML/JS frontend, Dockerfile, render.yaml, GitHub Actions (tests, bandit, pip-audit, Docker build, deploy to Render by deploy hook).
- Added for Units 4 and 5: Google OIDC single sign-on (off until env vars are set), /api/posture (CSPM-style posture checks), /api/metrics, status page, concurrency and rate limits, /api/audit-batch (process-pool parallelism), nginx load balancer demo in docker-compose.
- Read README.md, then docs/PLAN.md, docs/SECURITY.md, docs/DEPLOY.md, docs/EVIDENCE.md.
- Verified: 25 pytest tests pass; bandit has no medium or high issues; pip-audit clean; a 40 page audit went from 23 s to 1.8 s; a real nginx in front of three instances split traffic evenly and survived one instance being killed.

NOT DONE OR NOT VERIFIED
- Not yet deployed to Render. Docker build and GitHub Actions have never been run.
- SSO tested only with mocks, not against live Google.
- The AI call was tested only with mocks.
- Parallel speedup not measured (the build sandbox had 1 CPU).
- No real Indian PDFs collected or labelled yet; no evaluation numbers; report not written.
- Render free-tier behaviour (sleeping when idle, multiple instances needing a paid plan) is from memory, please verify.

WHAT I NEED NEXT (in order)
1. Help me deploy on Render following docs/DEPLOY.md and fix whatever breaks.
2. Set up Google SSO and the GitHub secrets so CI/CD deploys.
3. Tune the checks against the real PDFs I'll provide and fix false positives.
4. Build the evaluation (rule-only versus hybrid) and run the load test and parallel benchmark.
5. Write the report as a Word document, using the evidence and screenshots I collect.

HOW TO WORK WITH ME
Give exact steps, since I'm a student. Keep code readable with light comments. Be honest about limits and unverified claims. Avoid em dashes in documents. Course deliverables are usually Word (.docx). Ask before making large changes.
