"""End-to-end CLI demo: ingest the synthetic batch, fast-forward five days,
print what Reclaim recovered. No server, no keys needed.

    python scripts/demo.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import db, engine, simclock  # noqa: E402

DEMO_DB = ROOT / "reclaim.db"


def main() -> None:
    if DEMO_DB.exists():
        DEMO_DB.unlink()
    conn = db.connect(DEMO_DB)

    events = json.loads((ROOT / "data" / "events.json").read_text())
    print(f"Ingesting {len(events)} failed payments...")
    for e in events:
        engine.ingest_event(conn, e)
    conn.commit()

    for label, minutes in [("+1 hour", 60), ("+6 hours", 300), ("+1 day", 1080),
                           ("+2 days", 1440), ("+5 days", 4320)]:
        executed = 0
        engine.run_due(conn)
        simclock.advance(conn, minutes)
        conn.commit()
        executed = engine.run_due(conn)
        s = engine.stats(conn)
        print(f"{label:>9}: {executed:3d} retries ran | recovered {s['recovered']:3d}/{s['total_failed']} "
              f"(INR {s['recovered_amount']/100:,.0f} of {s['total_amount']/100:,.0f})")

    s = engine.stats(conn)
    print("\nFinal state:")
    for status, v in sorted(s["by_status"].items()):
        print(f"  {status:15s} {v['count']:4d}  INR {v['amount']/100:>10,.0f}")
    print(f"\nRecovery rate: {s['recovery_rate']:.1%}  |  INR {s['recovered_amount']/100:,.0f} recovered")

    sample = conn.execute(
        "SELECT payment_id FROM payments WHERE status='recovered' AND category='ambiguous' LIMIT 1"
    ).fetchone()
    if sample:
        print(f"\nSample audit trail ({sample['payment_id']}, ambiguous -> recovered):")
        for a in conn.execute("SELECT at, kind, source, rationale FROM actions WHERE payment_id=? ORDER BY at, id",
                              (sample["payment_id"],)):
            print(f"  [{a['at']}] {a['kind']:16s} ({a['source']}) {a['rationale']}")


if __name__ == "__main__":
    main()
