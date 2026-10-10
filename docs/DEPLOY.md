# Deployment on Render

Render is a managed platform (PaaS) running on public cloud infrastructure, with a public HTTPS URL, TLS handled at its edge, and a platform load balancer in front of the service. The app is packaged as a Docker container.

## 1. Push to GitHub

```
git init
git add .
git commit -m "PDF accessibility auditor"
git branch -M main
git remote add origin https://github.com/<your-username>/pdf-access-auditor.git
git push -u origin main
```

CI runs on every push: tests, security scans (bandit, pip-audit), Docker build and a container smoke test.

## 2. Create the service

1. In Render choose New, then Blueprint, and pick the repository. It reads `render.yaml`.
2. Values marked sync false are asked for during setup. For the first deploy you can leave the Google and AI values empty and add them later under Environment.
3. Wait for the first deploy to finish and open the `.onrender.com` URL. Take screenshots of the dashboard (service, events, environment, logs) for the report.

`SESSION_SECRET` is generated for you and stays the same across deploys, so sessions remain valid.

## 3. Continuous deployment from GitHub Actions

Auto-deploy is off in `render.yaml` so that a deploy only happens after the tests and scans pass.

1. In the Render service, open Settings and copy the Deploy Hook URL.
2. In GitHub, go to Settings, Secrets and variables, Actions, and add:
   - RENDER_DEPLOY_HOOK: the hook URL
   - RENDER_URL: the service URL, for example https://pdf-access-auditor.onrender.com
3. Push a change to main and watch the Actions tab: test, security, build, deploy.

Treat the hook URL as a secret, anyone who has it can trigger a deploy.

## 4. Turn on single sign-on (Unit 4)

1. In Google Cloud Console open APIs and Services, Credentials, and create an OAuth client ID of type Web application.
2. Add the authorized redirect URI: `https://<your-service>.onrender.com/auth/callback`
3. In Render, add environment variables:
   - GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET from the client
   - SSO_ALLOWED_DOMAINS, for example your institute email domain (comma separated, optional)
   - OAUTH_REDIRECT_URI, only if the sign-in redirect uses the wrong address
4. Redeploy. The main page now shows Sign in with Google, and the API returns 401 to anonymous callers.
5. Click Platform status in the top bar after signing in to see the posture score and instance metrics.

Until SSO is configured the service is open to anyone with the URL, and the posture page says so.

## 5. Optional AI check

Add ANTHROPIC_API_KEY under Environment. The user still has to tick the checkbox for each audit, because page images are sent to an external service.

## 6. Load balancing and scaling

- Render places its own load balancer in front of the service. On the free plan there is one instance. As far as I know, running several instances needs a paid plan, so check the dashboard before relying on it. `render.yaml` has a commented `numInstances` line for that.
- The app is stateless (signed cookie sessions, nothing stored on disk), so extra instances work without changes.
- To demonstrate load balancing without a paid plan, run `docker compose up --build` locally. It starts three app containers behind nginx. Then run `python scripts/load_test.py http://localhost:8080 60 6` and note the requests per instance. Kill one container and run it again to show failover.

## 7. Troubleshooting

- First request is slow or times out: free instances sleep after 15 minutes without traffic (confirmed in Render docs), and Render shows a loading page while the service wakes, and the wake-up time is not documented, so time it yourself. Open the URL once before a demo.
- 503 busy message: the server allows one audit at a time on the free plan. Wait a few seconds and retry.
- 504 timeout: the document is very long or the instance is slow. Try a shorter file.
- Sign-in redirects fail: the redirect URI in Google must exactly match `https://<service>/auth/callback`.
- Check Logs in the Render dashboard for errors.
