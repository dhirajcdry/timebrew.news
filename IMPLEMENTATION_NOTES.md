# TimeBrew: editorial redesign and source-grounding improvements

Prepared for review on October 12, 2026, against main commit
`fe35d5370197acf6c6994baa32a97803c663e97d`. Prepared for review on a separate
branch and draft pull request; no production merge or deployment is included.

## What changed

- A warm cream/sage landing page with readable editorial hierarchy, real section
  navigation, mobile menu, accessible sample dialog, dark-mode tokens, and a clear
  signup path. The preview is explicitly a historical 2024 collection, with NASA,
  Apple, and Royal Swedish Academy primary-source links.
- Removed fabricated headlines, unverified metrics/pricing, placeholder links,
  and the claims about editing/pausing brews that the current dashboard cannot fulfill.
- Auth/dashboard routes load on demand, keeping their code out of the landing's
  initial entry bundle. This is a bundle-size improvement, not a measured load-time result.
- Curation retains the provider's separate citation/search metadata. Articles
  must match that evidence and a conservative public-URL policy. Stable source IDs
  bind final stories to their original URL, publisher domain, and publication metadata.
- Recognizable homepage, section, category, topic, and search URLs are rejected as
  full-story sources, even when cited. This is a narrow URL-shape check, not a
  guarantee that every other link is an article; query-based article IDs remain usable.
- No restored rejected links, invented relative timestamps, or empty-day filler.
  Known out-of-window dates are rejected; unknown dates stay explicitly unavailable.
  An empty/unprovenanced source set withholds the email and records a failed run.
- The selected article count survives creation, storage, list/detail API responses,
  and the run snapshot. It is a ceiling: fewer stories are better than unsupported filler.
- Feedback uses the actual saved article identity and reaches the curator prompt.
  Repetition history includes only sent briefings, so failed drafts do not suppress
  stories the reader has never received.
- HTML email now has restrained editorial styling, concise takeaways, visible
  source domains, safe text/links, honest dates, and a plain-text MIME alternative.
- Dispatch revalidates the complete source set before SES. Sequential replay skips
  an acknowledged send and repairs timestamp-idempotent delivery bookkeeping.

## Checks performed

- Backend: 160 offline regression tests passed. Network connections are disabled
  by the test fixture; provider, database and SES calls are mocked.
- Synthetic email regressions cover trailing inline `**Takeaway:**` text with and
  without a separate takeaway field: HTML formatting and plain text are readable.
- Python compilation and `git diff --check`: passed.
- Frontend TypeScript/production build: passed.
- ESLint: zero errors, with 65 existing-style warnings in auth/dashboard/common
  code (unused declarations, broad types, hook dependencies, fast-refresh exports).
- Ten Playwright desktop/mobile tests are provided and discover correctly.
  They cover responsive width, sample focus/Escape/reopening, Back navigation,
  section links, mobile-menu dismissal, and reduced motion.
- Browser execution/visual QA is **not verified**. The execution sandbox prevents
  Chromium's Unix sockets, and the separate cloud browser cannot open this local
  server. No screenshots or email-client rendering checks are claimed.
- No production authentication, live LLM calls, live email sends, merge, or
  deployment was performed. Publishing this review branch and draft pull request
  was approved separately after the local checks above.

## Run locally

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt pytest
.venv/bin/python -m pytest -q
.venv/bin/python scripts/email_preview.py --output ./email-preview

cd frontend
npm ci
npm run build
npm run lint
npx playwright install chromium
npm run test:e2e
npm run dev
```

Open the local URL printed by Vite. The public landing can be reviewed without
credentials. Authentication requires the project's actual Cognito configuration;
no account flows should be tested against production without approval.
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` can select an already-installed Chromium.
The browser suite blocks external requests, including fonts, to test the fallback
layout without touching production APIs.

The email preview script uses only local code and a historical fixture. Open
`email-preview/index.html`; `index.txt` is its plain-text counterpart.

## Important boundaries before release

1. Citation identity is **not independent claim-level fact-checking** or HTTP page
   availability verification. A model can still misstate a cited source. The next
   quality step is retrieved article evidence plus claim checking and measured
   editorial evaluation, including quiet-news days.
2. Unknown-date sources can be included with an unavailable-date label. Their
   recency is not established by this gate.
3. Existing in-flight curator/editor records without the new provenance must be
   recurated. Do not invent provenance by backfilling from old generated JSON.
4. SES acceptance and the saved sent flag are not atomic. A crash in that gap, an
   ambiguous SES timeout, or concurrent dispatcher invocation still needs a durable
   outbox/dispatch-lock design. This change does not promise exactly-once delivery.
5. Verify desktop/mobile layout, real keyboard flow, signup navigation, and Gmail,
   Apple Mail, and Outlook rendering before release. The included browser tests
   are an executable checklist, not evidence that these checks already passed.
6. Review on a non-production environment first, then separately approve any
   live end-to-end generation/send test and deployment.
