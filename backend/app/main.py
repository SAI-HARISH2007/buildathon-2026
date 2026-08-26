"""Reclaim API. Run from repo root:  uvicorn app.main:app --app-dir backend --reload"""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db, engine, simclock

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

app = FastAPI(title="Reclaim", description="Failed-payment recovery agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def conn():
    return db.connect()


class IngestBody(BaseModel):
    events: list[dict]


class AdvanceBody(BaseModel):
    minutes: int


@app.post("/api/ingest")
def ingest(body: IngestBody):
    # network-bound prep (LLM + payment links) fans out in parallel;
    # SQLite writes stay sequential on one connection. Test-mode keys only
    # allow a ~5-link burst, so a batch spends a small real-link budget and
    # the rest are labeled budget-mocks (see razorpay_client).
    from concurrent.futures import ThreadPoolExecutor
    budget = 4
    allows = []
    for event in body.events:
        _, policy = engine.policy_for(event["failure_reason"])
        real = policy.send_payment_link and budget > 0
        if real:
            budget -= 1
        allows.append(real)
    with ThreadPoolExecutor(max_workers=8) as pool:
        preps = list(pool.map(engine.prepare_event, body.events, allows))
    c = conn()
    try:
        for event, prep in zip(body.events, preps):
            engine.ingest_event(c, event, prep)
        c.commit()
        executed = engine.run_due(c)
        return {"ingested": len(body.events), "immediately_executed": executed}
    finally:
        c.close()


@app.post("/api/webhook/razorpay")
def razorpay_webhook(envelope: dict):
    """Accepts Razorpay's real `payment.failed` webhook shape, so Reclaim can
    plug into a live merchant account with zero adapters."""
    if envelope.get("event") != "payment.failed":
        return {"ignored": envelope.get("event")}
    try:
        p = envelope["payload"]["payment"]["entity"]
    except KeyError:
        raise HTTPException(400, "malformed payload: expected payload.payment.entity")
    from datetime import datetime, timezone
    notes = p.get("notes") or {}
    email = p.get("email") or "unknown@example.com"
    event = {
        "payment_id": p["id"],
        "order_id": p.get("order_id"),
        "amount": p["amount"],
        "currency": p.get("currency", "INR"),
        "method": p.get("method", "card"),
        "failure_reason": p.get("error_reason") or "payment_failed",
        "customer": {
            "name": notes.get("name") or email.split("@")[0].title(),
            "email": email,
            "contact": p.get("contact", ""),
        },
        "failed_at": datetime.fromtimestamp(p["created_at"], tz=timezone.utc).isoformat()[:19],
    }
    c = conn()
    try:
        engine.ingest_event(c, event)
        c.commit()
        engine.run_due(c)
        return {"ingested": p["id"], "classified_as": engine.policy_for(event["failure_reason"])[0].value}
    finally:
        c.close()


@app.post("/api/ingest/demo")
def ingest_demo(limit: int = 200):
    """One-click demo: ingest the bundled synthetic batch."""
    import json
    events = json.loads((Path(__file__).resolve().parents[2] / "data" / "events.json").read_text())
    return ingest(IngestBody(events=events[:limit]))


@app.post("/api/reset")
def reset():
    """Wipe all state for a fresh demo run."""
    c = conn()
    try:
        for table in ("payments", "actions", "schedule", "clock"):
            c.execute(f"DELETE FROM {table}")
        c.commit()
        return {"reset": True}
    finally:
        c.close()


@app.post("/api/clock/advance")
def advance(body: AdvanceBody):
    if not 1 <= body.minutes <= 30 * 24 * 60:
        raise HTTPException(400, "minutes must be between 1 and 43200 (30 days)")
    c = conn()
    try:
        now = simclock.advance(c, body.minutes)
        c.commit()
        executed = engine.run_due(c)
        return {"now": simclock.fmt(now), "retries_executed": executed}
    finally:
        c.close()


@app.get("/api/clock")
def clock():
    c = conn()
    try:
        return {"now": simclock.fmt(simclock.get_now(c))}
    finally:
        c.close()


@app.get("/api/payments")
def payments(status: str | None = None, limit: int = 200):
    c = conn()
    try:
        q = "SELECT * FROM payments"
        args: list = []
        if status:
            q += " WHERE status=?"
            args.append(status)
        q += " ORDER BY failed_at LIMIT ?"
        args.append(min(limit, 1000))
        return [dict(r) for r in c.execute(q, args).fetchall()]
    finally:
        c.close()


@app.get("/api/payments/{payment_id}")
def payment_detail(payment_id: str):
    c = conn()
    try:
        p = c.execute("SELECT * FROM payments WHERE payment_id=?", (payment_id,)).fetchone()
        if p is None:
            raise HTTPException(404, "unknown payment")
        actions = c.execute(
            "SELECT at, kind, source, rationale, detail FROM actions WHERE payment_id=? ORDER BY at, id",
            (payment_id,)).fetchall()
        return {**dict(p), "timeline": [dict(a) for a in actions]}
    finally:
        c.close()


class ReviewBody(BaseModel):
    action: str  # approve_retry | dismiss


@app.post("/api/payments/{payment_id}/review")
def review(payment_id: str, body: ReviewBody):
    """Human-in-the-loop resolution for payments the agent refuses to touch.
    approve_retry grants exactly ONE supervised attempt; dismiss closes it."""
    if body.action not in ("approve_retry", "dismiss"):
        raise HTTPException(400, "action must be approve_retry or dismiss")
    c = conn()
    try:
        p = c.execute("SELECT * FROM payments WHERE payment_id=?", (payment_id,)).fetchone()
        if p is None:
            raise HTTPException(404, "unknown payment")
        if p["status"] not in ("manual_review", "merchant_alert"):
            raise HTTPException(409, f"payment is '{p['status']}', not awaiting review")
        from datetime import timedelta
        from . import db as _db
        now = simclock.get_now(c)
        if body.action == "dismiss":
            c.execute("UPDATE payments SET status='dismissed' WHERE payment_id=?", (payment_id,))
            _db.log_action(c, payment_id, simclock.fmt(now), "dismissed", "human",
                           "operator closed the case — no recovery attempted")
        else:
            due = now + timedelta(minutes=5)
            c.execute("INSERT INTO schedule (payment_id, due_at, attempt_no) VALUES (?,?,1)",
                      (payment_id, simclock.fmt(due)))
            c.execute("UPDATE payments SET status='scheduled' WHERE payment_id=?", (payment_id,))
            _db.log_action(c, payment_id, simclock.fmt(now), "scheduled", "human",
                           f"operator approved ONE supervised retry, due {simclock.fmt(due)}")
        c.commit()
        return {"payment_id": payment_id, "action": body.action}
    finally:
        c.close()


@app.get("/api/stats")
def stats():
    c = conn()
    try:
        return engine.stats(c)
    finally:
        c.close()


# Single-service deploys: serve the built dashboard when it exists.
# API routes above always win; this only catches non-/api paths.
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="dashboard")
