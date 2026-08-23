"""Generate a synthetic batch of failed-payment events for Reclaim.

All data is fake and clearly labeled as such. Failure reasons are sampled from
Razorpay's documented reason list, weighted toward what actually dominates
real-world failure traffic (customer fumbles, insufficient funds, bank issues),
and constrained to reasons that make sense for the sampled payment method.

Usage:
    python scripts/generate_synthetic_events.py [count] [seed] > data/events.json
"""

import json
import random
import sys
from datetime import datetime, timedelta

# (reason, weight, methods it can occur on)
REASON_POOL = [
    ("incorrect_otp",          10, ["card", "netbanking"]),
    ("authentication_failed",   8, ["card", "netbanking"]),
    ("payment_cancelled",      10, ["card", "upi", "netbanking"]),
    ("payment_timed_out",       8, ["card", "upi", "netbanking"]),
    ("insufficient_funds",     14, ["card", "upi", "netbanking"]),
    ("credit_limit_exceeded",   3, ["card"]),
    ("bank_not_available",      5, ["netbanking", "upi"]),
    ("bank_technical_error",    5, ["netbanking", "upi", "card"]),
    ("gateway_technical_error", 3, ["card", "upi", "netbanking"]),
    ("upi_app_technical_error", 4, ["upi"]),
    ("invalid_vpa",             4, ["upi"]),
    ("payment_collect_request_expired", 4, ["upi"]),
    ("card_expired",            4, ["card"]),
    ("card_number_invalid",     2, ["card"]),
    ("incorrect_cvv",           3, ["card"]),
    ("payment_risk_check_failed", 2, ["card", "upi"]),
    ("international_transaction_not_allowed", 1, ["card"]),
    ("transaction_daily_limit_exceeded", 2, ["upi", "netbanking"]),
    ("payment_method_not_enabled", 1, ["card", "upi", "netbanking"]),
    ("payment_failed",          8, ["card", "upi", "netbanking"]),  # ambiguous
    ("card_declined",           6, ["card"]),                        # ambiguous
    ("debit_declined",          4, ["upi", "netbanking"]),           # ambiguous
]

FIRST_NAMES = ["Aarav", "Diya", "Vihaan", "Ananya", "Kabir", "Ishita", "Rohan",
               "Meera", "Arjun", "Sneha", "Aditya", "Priya", "Karan", "Nisha"]

AMOUNT_BUCKETS = [(9900, 49900, 5), (49900, 199900, 3), (199900, 999900, 1)]  # paise


def generate(count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    base = datetime(2026, 8, 20, 6, 0, 0)
    reasons, weights = zip(*[(r, w) for r, w, _ in REASON_POOL])
    method_map = {r: m for r, _, m in REASON_POOL}

    events = []
    for i in range(count):
        reason = rng.choices(reasons, weights=weights)[0]
        method = rng.choice(method_map[reason])
        lo, hi, _ = rng.choices(AMOUNT_BUCKETS, weights=[b[2] for b in AMOUNT_BUCKETS])[0]
        name = rng.choice(FIRST_NAMES)
        ts = base + timedelta(minutes=rng.randint(0, 3 * 24 * 60))
        events.append({
            "event_id": f"evt_synthetic_{i:04d}",
            "payment_id": f"pay_FAKE{rng.randint(10**9, 10**10 - 1)}",
            "order_id": f"order_FAKE{rng.randint(10**9, 10**10 - 1)}",
            "amount": rng.randrange(lo, hi, 100),
            "currency": "INR",
            "method": method,
            "failure_reason": reason,
            "customer": {
                "name": name,
                "email": f"{name.lower()}.demo@example.com",
                "contact": f"+91-99999-{rng.randint(10000, 99999)}",
            },
            "failed_at": ts.isoformat() + "+05:30",
            "synthetic": True,
        })
    events.sort(key=lambda e: e["failed_at"])
    return events


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    json.dump(generate(count, seed), sys.stdout, indent=2)
    sys.stdout.write("\n")
