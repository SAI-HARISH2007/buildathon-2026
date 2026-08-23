# Reclaim — failed-payment recovery agent

Every day, a slice of legitimate payments fail — wrong OTP, bank downtime, insufficient funds, expired cards. Most merchants let that revenue die silently. **Reclaim** ingests failed-payment events, works out *why* each one failed, and runs the right recovery play for each cause — automatically, with hard safety bounds and a full audit trail.

Built for the Razorpay AI Buildathon, Track 03: AI Revenue Recovery.

## How it decides

The core design principle: **AI only where judgment is needed, rules everywhere correctness is knowable.**

1. **Ingest** — failed-payment events (payment id, method, amount, Razorpay failure `reason`, customer contact, timestamp).
2. **Classify — deterministic.** Razorpay documents [114 failure reasons](data/razorpay_error_reasons.json). Mapping `insufficient_funds` or `bank_not_available` to a recovery category is a lookup, not a judgment call — so it's a rule table (`backend/app/rules.py`): auditable, testable, free, and never hallucinates.
3. **Decide — rules first, LLM for the ambiguous tail.** Clear-cut categories get fixed policies (bank timeout → backoff retry; insufficient funds → scheduled retry next day + payment link). Genuinely ambiguous reasons (`payment_failed`, `card_declined` — where banks share nothing) go to an LLM that weighs amount, method, history, and time-of-day to pick an intervention and draft the customer-facing recovery message.
4. **Execute — bounded.** Recovery actions go through Razorpay test-mode APIs (Payment Links). Hard stops enforced in code, not prompts: max attempts per payment, cool-down windows, no retries on risk/compliance failures, ever.
5. **Audit + dashboard.** Every decision is logged: what failed, why, what the agent chose, what happened. Dashboard shows the batch in → recovered count, ₹ recovered, and the exceptions queue for humans.

## Stack

- **Backend:** FastAPI + SQLite (zero-setup, judge can run it with one command)
- **Frontend:** React (Vite) dashboard
- **Payments:** Razorpay test-mode API
- **AI:** one LLM call site, for the ambiguous-classification + message-drafting step only
- **Sim clock:** retries scheduled "in 10 minutes" or "tomorrow 7 pm" run against a simulated clock so a full multi-day recovery lifecycle can be demonstrated in a 5-minute video

## Run it

```bash
# 1. Backend (Python 3.11+)
pip install -r backend/requirements.txt
python3 -m uvicorn app.main:app --app-dir backend --port 8000

# 2. Dashboard
cd frontend && npm install && npm run dev   # -> http://localhost:5173
```

In the dashboard: **Reset + ingest demo batch**, then fast-forward the sim clock and watch recovery happen. Click any payment row for its full decision audit trail.

No keys needed — without a `.env`, the LLM step runs a deterministic heuristic and payment links are mocked (each decision records which engine produced it). Copy `.env.example` to `.env` and add keys to go live: Gemini for real AI triage, Razorpay test-mode for real payment links.

Zero-setup CLI demo (no server, no npm):

```bash
python3 scripts/demo.py
```

## What broke

An honest log of everything that went wrong building this lives in [BUGLOG.md](BUGLOG.md).
