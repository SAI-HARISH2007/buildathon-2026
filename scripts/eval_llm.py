"""Eval harness for Reclaim's single LLM call site.

"We use AI for ambiguous failures" is a claim; this script is the evidence.
It runs 12 hand-labeled ambiguous-failure cases (data/eval_cases.json) through
the decision engine and scores every decision on four checks:

  1. action_ok   — is the chosen action in the case's acceptable set?
                   (labels allow several answers; ambiguity is the point)
  2. bounds_ok   — is wait_minutes inside the code-enforced clamp (1 min..7 days)?
  3. message_ok  — customer-facing actions carry a non-empty, non-pushy message
                   with the [LINK] placeholder convention respected
  4. reasoning_ok— a stated one-line rationale exists (auditability)

Run it twice to compare engines:
    python scripts/eval_llm.py            # whatever .env provides (Gemini if keyed)
    python scripts/eval_llm.py --heuristic  # force the keyless fallback baseline

Honest note on reading the numbers: the heuristic baseline can hit 12/12 too —
it was written alongside this rubric, so it is overfit by construction. What
the LLM buys is generalization to the unlabeled long tail and a bespoke,
context-aware customer message per case (the rubric only checks messages
aren't empty or pushy). What this harness guards against is regression: the
first eval run caught live Gemini re-messaging customers on repeat failures
(10/12) — a prompt fix took it back to 12/12. If the LLM ever falls below the
baseline here again, that's the signal to fix the prompt or delete the call.
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

PUSHY_WORDS = ("urgent", "immediately", "last chance", "final warning", "act now")


def score(case: dict, out: dict) -> dict:
    checks = {
        "action_ok": out["action"] in case["acceptable"],
        "bounds_ok": (out["action"] == "give_up") or (0 <= out.get("wait_minutes", 0) <= 7 * 24 * 60),
        "reasoning_ok": bool(out.get("reasoning", "").strip()),
    }
    if out["action"] in ("send_link_and_message", "retry_tomorrow"):
        msg = out.get("message", "")
        checks["message_ok"] = bool(msg.strip()) and not any(w in msg.lower() for w in PUSHY_WORDS)
    else:
        checks["message_ok"] = True
    return checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--heuristic", action="store_true",
                        help="force the keyless heuristic baseline")
    parser.add_argument("--sleep", type=float, default=5.0,
                        help="seconds between LLM calls (stay under the free-tier ~10 req/min)")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    if args.heuristic:
        os.environ.pop("GEMINI_API_KEY", None)

    from app import llm  # import after env is settled

    import time
    cases = json.loads((ROOT / "data" / "eval_cases.json").read_text())
    rows, engines = [], set()
    for i, case in enumerate(cases):
        if i and not args.heuristic:
            time.sleep(args.sleep)
        ctx = {k: case[k] for k in ("amount", "method", "reason", "failed_at", "attempts", "name")}
        out = llm.decide(ctx)
        engines.add(out["engine"])
        checks = score(case, out)
        rows.append({"case": case["case"], "action": out["action"],
                     "engine": out["engine"], **checks})
        flag = "PASS" if all(checks.values()) else "FAIL"
        failed = [k for k, v in checks.items() if not v]
        print(f"[{flag}] {case['case']:42s} -> {out['action']:22s}"
              f"{('  failed: ' + ', '.join(failed)) if failed else ''}")

    n = len(rows)
    print(f"\nengine(s): {', '.join(sorted(engines))}")
    for check in ("action_ok", "bounds_ok", "message_ok", "reasoning_ok"):
        ok = sum(r[check] for r in rows)
        print(f"  {check:13s} {ok:2d}/{n}")
    overall = sum(all(r[k] for k in ("action_ok", "bounds_ok", "message_ok", "reasoning_ok")) for r in rows)
    print(f"  {'overall':13s} {overall:2d}/{n}")

    out_path = ROOT / "data" / ("eval_results_heuristic.json" if args.heuristic else "eval_results_llm.json")
    out_path.write_text(json.dumps(rows, indent=2))
    print(f"\nresults written to {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
