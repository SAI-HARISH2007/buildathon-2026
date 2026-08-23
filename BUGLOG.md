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
