"""Simulated clock. Recovery plays span minutes to days ("retry tomorrow
evening"), which is undemoable in real time — so the scheduler runs against a
clock the operator fast-forwards. Swapping get_now() for datetime.now() is the
only change needed to run against wall-clock time in production."""

from datetime import datetime, timedelta

ISO = "%Y-%m-%dT%H:%M:%S"


def get_now(conn) -> datetime:
    row = conn.execute("SELECT now FROM clock WHERE id = 1").fetchone()
    if row is None:
        start = datetime(2026, 8, 20, 6, 0, 0)
        conn.execute("INSERT INTO clock (id, now) VALUES (1, ?)", (start.strftime(ISO),))
        return start
    return datetime.strptime(row["now"], ISO)


def advance(conn, minutes: int) -> datetime:
    now = get_now(conn) + timedelta(minutes=minutes)
    conn.execute("UPDATE clock SET now = ? WHERE id = 1", (now.strftime(ISO),))
    return now


def fmt(dt: datetime) -> str:
    return dt.strftime(ISO)
