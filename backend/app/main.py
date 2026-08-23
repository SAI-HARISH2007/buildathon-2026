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
    c = conn()
    try:
        for event in body.events:
            engine.ingest_event(c, event)
        c.commit()
        executed = engine.run_due(c)
        return {"ingested": len(body.events), "immediately_executed": executed}
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


@app.get("/api/stats")
def stats():
    c = conn()
    try:
        return engine.stats(c)
    finally:
        c.close()
