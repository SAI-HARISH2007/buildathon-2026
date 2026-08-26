# Bug log

Everything that broke while building Reclaim, and how I got out. Newest first.

Format per entry:

```
## YYYY-MM-DD — short title
**What broke:** what I saw (error, wrong behavior)
**Why:** root cause once found
**How I got out:** the fix, and what I'd do differently
```

---

## 2026-08-26 — the eval harness caught Gemini harassing customers
**What broke:** Nothing crashed — worse, something worked wrong quietly. The first eval run scored live Gemini 10/12: on both repeat-failure cases (attempts 1 and 2) it chose to send the customer *another* payment link and message, where the right behavior is backing off. The keyless heuristic scored 12/12 on the same rubric.
**Why:** The prompt's "repeated failures deserve give_up" was a soft rule of thumb, and a recovery-eager model read it as optional. Code bounds capped the damage (max 2 attempts regardless), but the *decision quality* was wrong and only measurement exposed it.
**How I got out:** Promoted it to a HARD RULE in the prompt (attempts >= 2 MUST give_up; attempts == 1 prefers backing off) and re-ran: 12/12. Kept the finding in the eval docstring — the harness now exists precisely to catch this class of silent regression.

## 2026-08-24 — Razorpay rejects reused reference_ids across demo resets
**What broke:** After a dashboard reset + fresh ingest, almost every "real" payment link silently degraded to a mock fallback. First run was fine.
**Why:** Payment links were created with `reference_id = payment_id`. Resetting the local DB doesn't reset Razorpay's — the same synthetic payment ids arrived again and Razorpay (correctly) rejected the duplicates. Confirmed with a two-call test: first 200, second 4xx.
**How I got out:** `reference_id` is now `payment_id` plus a random suffix per attempt. Local resets and remote state no longer collide.

## 2026-08-24 — parallelizing ingest ran head-first into both rate limits
**What broke:** Made batch ingest ~3× faster with an 8-worker prep pool — and link fallbacks went UP (35 of 40 mocked). Measured Razorpay test mode directly: ~5 link creations per burst, then 429s refilling at roughly one slot per 5–10 seconds. Gemini's free tier (~10 req/min) also started dropping parallel calls to the heuristic.
**Why:** Parallelism doesn't create throughput the provider won't give you. A 60-event batch wanting ~40 links can never be all-real on a test key, no matter the concurrency.
**How I got out:** Stopped fighting the limit and designed around it: each batch spends a small **real-link budget** (first few link-needing payments, within the burst allowance, with patient 429 retries) and the rest are explicitly labeled `mock-rate-budget` in the audit trail; Gemini calls go through a 2-lane semaphore plus a retry-after-429. Single webhook events always get real links — which is the actual production shape, since real failures arrive one at a time, not 60 at once.

## 2026-08-23 — Vite silently serves stale code on WSL2 /mnt/c
**What broke:** Fixed a table-clipping bug in the dashboard, re-screenshotted — pixel-identical to before the fix. The edit was on disk; the browser got old code.
**Why:** The project lives on a Windows-mounted path (`/mnt/c`) under WSL2, where inotify file-watching doesn't work — Vite never saw the change and kept serving its cached transform.
**How I got out:** Restarted Vite with `--force` and run the dev server with `CHOKIDAR_USEPOLLING=1` so the watcher polls instead of waiting for events that never come.

## 2026-08-23 — one flaky SSL handshake killed a whole ingest batch
**What broke:** `POST /api/ingest/demo` returned 500 mid-batch. Traceback: `httpx.ConnectTimeout` — a single Razorpay payment-link call's TLS handshake timed out and the exception propagated up through the whole 60-event ingest.
**Why:** The LLM client had a graceful fallback from day one; the Razorpay client didn't. Any synchronous external call without a fallback is a batch-killer.
**How I got out:** Wrapped link creation so a gateway failure degrades to a clearly-labeled `mock-fallback` link, with the error class recorded in the audit trail. The batch completes; the trail tells the truth about what degraded.

## 2026-08-23 — the LLM's message had a dangling "[Payment Link]" placeholder
**What broke:** First live Gemini test drafted a great customer message ending in "…using this secure link: [Payment Link]" — and nothing ever substituted a real URL. Customers would have received a literal placeholder.
**Why:** The prompt asked for a message but the link doesn't exist yet at drafting time, and the engine never reconciled the two.
**How I got out:** The prompt now instructs an exact `[LINK]` placeholder, the engine substitutes the real short URL after link creation, and a safety net appends the link if the model ignored the placeholder convention.

## 2026-08-23 — Razorpay error-reason docs are JS-rendered
**What broke:** Wanted the official list of payment failure `reason` values to seed the rule engine; the docs pages return only a JS shell to non-browser fetchers, and two obvious doc URLs 404'd.
**Why:** razorpay.com/docs renders content client-side.
**How I got out:** Found Razorpay ships the full list as a downloadable spreadsheet (`payments_error_reasons.xlsx`) linked from the docs. Parsed the xlsx (raw OOXML — no Excel libs installed) into `data/razorpay_error_reasons.json`: 114 documented reasons with explanations and recommended next steps. The rule table is now grounded in Razorpay's own documentation instead of invented codes.
