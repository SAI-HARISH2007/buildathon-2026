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

## 2026-08-23 — Razorpay error-reason docs are JS-rendered
**What broke:** Wanted the official list of payment failure `reason` values to seed the rule engine; the docs pages return only a JS shell to non-browser fetchers, and two obvious doc URLs 404'd.
**Why:** razorpay.com/docs renders content client-side.
**How I got out:** Found Razorpay ships the full list as a downloadable spreadsheet (`payments_error_reasons.xlsx`) linked from the docs. Parsed the xlsx (raw OOXML — no Excel libs installed) into `data/razorpay_error_reasons.json`: 114 documented reasons with explanations and recommended next steps. The rule table is now grounded in Razorpay's own documentation instead of invented codes.
