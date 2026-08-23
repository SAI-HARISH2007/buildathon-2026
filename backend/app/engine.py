"""The recovery engine: classify -> decide -> schedule -> execute, fully audited.

Retry OUTCOMES are simulated (seeded per-category success rates) because the
input data is synthetic — there is no real customer to complete a real retry.
The simulator is quarantined in simulate_retry_outcome() and clearly labeled in
the audit trail; everything upstream of it (classification, policy, scheduling,
link creation) is the real production path.
"""

import random
from datetime import datetime, timedelta

from . import llm, razorpay_client
from .db import log_action
from .rules import Category, POLICIES, policy_for
from .simclock import fmt, get_now

# Simulated probability that a due retry actually recovers the payment.
RECOVERY_PROBS = {
    Category.TRANSIENT: 0.70,
    Category.INSUFFICIENT_FUNDS: 0.45,
    Category.CUSTOMER_FUMBLE: 0.55,
    Category.INSTRUMENT_INVALID: 0.30,
    Category.LIMIT_EXCEEDED: 0.60,
    Category.AMBIGUOUS: 0.40,
}

MESSAGES = {
    Category.INSUFFICIENT_FUNDS: "Hi {name}, your payment of INR {rupees:.2f} could not be completed. We'll retry tomorrow, or you can pay now: {link}",
    Category.CUSTOMER_FUMBLE: "Hi {name}, your payment of INR {rupees:.2f} didn't go through at the last step. Complete it here whenever convenient: {link}",
    Category.INSTRUMENT_INVALID: "Hi {name}, your payment method for INR {rupees:.2f} couldn't be used. Pay with another method here: {link}",
    Category.LIMIT_EXCEEDED: "Hi {name}, your payment of INR {rupees:.2f} hit a bank transaction limit. It usually works after the limit resets — or pay here: {link}",
}


def _rng(payment_id: str) -> random.Random:
    return random.Random(payment_id)  # deterministic per payment -> reproducible demos


def ingest_event(conn, event: dict) -> None:
    now = get_now(conn)
    pid = event["payment_id"]
    reason = event["failure_reason"]
    cat, policy = policy_for(reason)

    conn.execute(
        """INSERT OR IGNORE INTO payments
           (payment_id, order_id, amount, currency, method, failure_reason, category,
            customer_name, customer_email, customer_contact, failed_at, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (pid, event.get("order_id"), event["amount"], event.get("currency", "INR"),
         event["method"], reason, cat.value,
         event["customer"]["name"], event["customer"]["email"], event["customer"]["contact"],
         event["failed_at"][:19], "failed"),
    )
    log_action(conn, pid, fmt(now), "classified", "rule",
               f"reason '{reason}' -> {cat.value} (max {policy.max_attempts} attempts)")

    if cat is Category.DO_NOT_RETRY:
        conn.execute("UPDATE payments SET status='manual_review' WHERE payment_id=?", (pid,))
        log_action(conn, pid, fmt(now), "escalated", "rule",
                   "risk/compliance/duplicate class — never auto-retried, human review only")
        return
    if cat is Category.MERCHANT_CONFIG:
        conn.execute("UPDATE payments SET status='merchant_alert' WHERE payment_id=?", (pid,))
        log_action(conn, pid, fmt(now), "escalated", "rule",
                   "merchant-side misconfiguration — alerting merchant, customer not contacted")
        return

    if policy.needs_llm:
        decision = llm.decide({"amount": event["amount"], "method": event["method"],
                               "reason": reason, "failed_at": event["failed_at"],
                               "attempts": 0, "name": event["customer"]["name"]})
        wait = min(decision["wait_minutes"], policy.cooldown_minutes[0]) \
            if decision["action"] == "retry_soon" else decision["wait_minutes"]
        wait = max(1, min(wait, 7 * 24 * 60))  # clamp: 1 min .. 7 days, code-enforced
        log_action(conn, pid, fmt(now), "llm_decision", "llm", decision["reasoning"],
                   {"action": decision["action"], "wait_minutes": wait, "engine": decision["engine"]})
        if decision["action"] == "give_up":
            conn.execute("UPDATE payments SET status='abandoned' WHERE payment_id=?", (pid,))
            log_action(conn, pid, fmt(now), "abandoned", "llm", decision["reasoning"])
            return
        due = now + timedelta(minutes=wait)
        message = decision.get("message", "")
    else:
        due = now + timedelta(minutes=policy.cooldown_minutes[0])
        message = ""

    if policy.send_payment_link:
        link = razorpay_client.create_payment_link(
            event["amount"], event.get("currency", "INR"),
            f"Payment retry for order {event.get('order_id')}", event["customer"], pid)
        log_action(conn, pid, fmt(now), "link_created", "system",
                   f"recovery link issued ({link['mode']} mode)", link)
        if message:
            # the LLM writes a [LINK] placeholder; the real URL is substituted here
            for placeholder in ("[LINK]", "[Payment Link]", "[payment link]"):
                message = message.replace(placeholder, link["short_url"])
            if link["short_url"] not in message:
                message = f"{message.rstrip()} Pay here: {link['short_url']}"
        elif cat in MESSAGES:
            message = MESSAGES[cat].format(name=event["customer"]["name"],
                                           rupees=event["amount"] / 100, link=link["short_url"])
    if policy.notify_customer and message:
        log_action(conn, pid, fmt(now), "message_drafted",
                   "llm" if policy.needs_llm else "rule", "", {"message": message})

    conn.execute("INSERT INTO schedule (payment_id, due_at, attempt_no) VALUES (?,?,1)",
                 (pid, fmt(due), ))
    conn.execute("UPDATE payments SET status='scheduled' WHERE payment_id=?", (pid,))
    log_action(conn, pid, fmt(now), "scheduled", "rule" if not policy.needs_llm else "llm",
               f"attempt 1 due {fmt(due)}")


def simulate_retry_outcome(payment_row, attempt_no: int) -> bool:
    """SIMULATION BOUNDARY: synthetic data has no real customer, so retry
    outcomes are drawn from per-category success rates, seeded per payment."""
    prob = RECOVERY_PROBS.get(Category(payment_row["category"]), 0.4)
    prob *= 0.8 ** (attempt_no - 1)  # later attempts recover less often
    return _rng(payment_row["payment_id"] + str(attempt_no)).random() < prob


def run_due(conn) -> int:
    """Execute every scheduled retry that is due at the current sim time."""
    now = get_now(conn)
    due = conn.execute(
        "SELECT * FROM schedule WHERE done=0 AND due_at <= ? ORDER BY due_at", (fmt(now),)
    ).fetchall()
    for item in due:
        conn.execute("UPDATE schedule SET done=1 WHERE id=?", (item["id"],))
        p = conn.execute("SELECT * FROM payments WHERE payment_id=?",
                         (item["payment_id"],)).fetchone()
        if p is None or p["status"] not in ("scheduled",):
            continue
        cat, policy = policy_for(p["failure_reason"])
        attempt = item["attempt_no"]
        conn.execute("UPDATE payments SET attempts=? WHERE payment_id=?", (attempt, p["payment_id"]))

        recovered = simulate_retry_outcome(p, attempt)
        log_action(conn, p["payment_id"], fmt(now), "retry_attempted", "system",
                   f"attempt {attempt}/{policy.max_attempts} (outcome simulated)",
                   {"recovered": recovered})
        if recovered:
            conn.execute("UPDATE payments SET status='recovered', recovered_at=? WHERE payment_id=?",
                         (fmt(now), p["payment_id"]))
            log_action(conn, p["payment_id"], fmt(now), "recovered", "system",
                       f"INR {p['amount']/100:.2f} recovered on attempt {attempt}")
        elif attempt < policy.max_attempts:
            next_due = now + timedelta(minutes=policy.cooldown_minutes[attempt])
            conn.execute("INSERT INTO schedule (payment_id, due_at, attempt_no) VALUES (?,?,?)",
                         (p["payment_id"], fmt(next_due), attempt + 1))
            log_action(conn, p["payment_id"], fmt(now), "scheduled", "rule",
                       f"attempt {attempt + 1} due {fmt(next_due)}")
        else:
            conn.execute("UPDATE payments SET status='abandoned' WHERE payment_id=?", (p["payment_id"],))
            log_action(conn, p["payment_id"], fmt(now), "abandoned", "rule",
                       f"max attempts ({policy.max_attempts}) reached — hard stop")
    conn.commit()
    return len(due)


def stats(conn) -> dict:
    rows = conn.execute(
        "SELECT status, COUNT(*) n, SUM(amount) amt FROM payments GROUP BY status").fetchall()
    by_status = {r["status"]: {"count": r["n"], "amount": r["amt"] or 0} for r in rows}
    total = sum(v["count"] for v in by_status.values())
    total_amt = sum(v["amount"] for v in by_status.values())
    rec = by_status.get("recovered", {"count": 0, "amount": 0})
    by_cat = conn.execute(
        """SELECT category, COUNT(*) n,
                  SUM(CASE WHEN status='recovered' THEN 1 ELSE 0 END) rec
           FROM payments GROUP BY category""").fetchall()
    return {
        "total_failed": total, "total_amount": total_amt,
        "recovered": rec["count"], "recovered_amount": rec["amount"],
        "recovery_rate": round(rec["count"] / total, 3) if total else 0.0,
        "by_status": by_status,
        "by_category": {r["category"]: {"count": r["n"], "recovered": r["rec"]} for r in by_cat},
    }
