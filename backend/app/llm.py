"""The single LLM call site in Reclaim.

Used only for AMBIGUOUS failures (the bank shared nothing useful) — the LLM
weighs amount, method, and timing to pick an intervention and draft the
customer message. Everything else in the system is deterministic rules.

Runs in two modes:
- GEMINI_API_KEY set  -> Google Gemini (free tier) decides.
- no key              -> a deterministic heuristic stands in, so the whole
                         system runs with zero credentials (and tests are
                         reproducible). The mode is recorded on every decision.

Whatever the LLM answers is CLAMPED to the code-enforced RetryPolicy bounds in
engine.py — the model proposes, the rules dispose.
"""

import json
import os

import httpx

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

ACTIONS = ["retry_soon", "retry_tomorrow", "send_link_and_message", "give_up"]

PROMPT = """You triage failed online payments for an Indian merchant.
The bank gave an uninformative failure reason, so infer the most likely cause and best recovery move.

Payment:
- amount: INR {rupees:.2f}
- method: {method}
- failure reason (opaque): {reason}
- failed at: {failed_at} (local time)
- attempts so far: {attempts}

Pick ONE action from {actions}.
Rules of thumb: small-amount UPI failures at odd hours are often transient (retry_soon);
large card declines are often limits/funds (retry_tomorrow with a payment link);
repeated failures deserve give_up. Draft a short, polite customer SMS (max 2 sentences,
no pressure tactics, include nothing false). Where the payment link belongs in the
message, write exactly the placeholder [LINK] — the system substitutes the real URL.

Answer with ONLY this JSON:
{{"action": "...", "wait_minutes": <int>, "message": "...", "reasoning": "<one sentence>"}}"""


def _heuristic(ctx: dict) -> dict:
    """Keyless stand-in. Deliberately simple and deterministic."""
    big = ctx["amount"] >= 100000  # >= INR 1000
    if ctx["attempts"] >= 1:
        return {"action": "give_up", "wait_minutes": 0,
                "message": "", "reasoning": "heuristic: repeated opaque failure, stop bothering the customer"}
    if ctx["method"] == "upi" and not big:
        return {"action": "retry_soon", "wait_minutes": 30,
                "message": f"Hi {ctx['name']}, your payment of INR {ctx['amount']/100:.2f} didn't go through. We'll retry shortly — no action needed.",
                "reasoning": "heuristic: small UPI failure, likely transient"}
    return {"action": "retry_tomorrow", "wait_minutes": 1440,
            "message": f"Hi {ctx['name']}, your payment of INR {ctx['amount']/100:.2f} didn't complete. You can retry anytime with this link.",
            "reasoning": "heuristic: larger amount, likely funds/limits — retry next day with a link"}


def decide(ctx: dict) -> dict:
    """ctx: {amount (paise), method, reason, failed_at, attempts, name}.
    Returns {action, wait_minutes, message, reasoning, engine}."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {**_heuristic(ctx), "engine": "heuristic"}

    prompt = PROMPT.format(rupees=ctx["amount"] / 100, method=ctx["method"],
                           reason=ctx["reason"], failed_at=ctx["failed_at"],
                           attempts=ctx["attempts"], actions=ACTIONS)
    try:
        resp = httpx.post(
            GEMINI_URL, params={"key": api_key}, timeout=30,
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}},
        )
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        out = json.loads(text)
        if out.get("action") not in ACTIONS:
            raise ValueError(f"invalid action {out.get('action')!r}")
        out["wait_minutes"] = max(0, int(out.get("wait_minutes", 30)))
        out["engine"] = f"gemini:{GEMINI_MODEL}"
        return out
    except Exception as exc:  # LLM failure must never take down recovery
        fallback = _heuristic(ctx)
        fallback["reasoning"] += f" (LLM unavailable: {type(exc).__name__})"
        return {**fallback, "engine": "heuristic-fallback"}
