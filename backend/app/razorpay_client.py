"""Razorpay test-mode integration (Payment Links).

With RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET set, recovery links are created for
real against api.razorpay.com in test mode. Without keys, a clearly-labeled
mock link is issued so the system stays runnable end-to-end — every link
records which mode produced it.
"""

import os
import uuid

import httpx

API = "https://api.razorpay.com/v1"


def create_payment_link(amount: int, currency: str, description: str,
                        customer: dict, reference_id: str) -> dict:
    key_id = os.environ.get("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()

    if not (key_id and key_secret):
        return {"mode": "mock", "id": f"plink_mock_{uuid.uuid4().hex[:12]}",
                "short_url": f"https://rzp.io/mock/{uuid.uuid4().hex[:8]}", "status": "created"}

    payload = {
        "amount": amount, "currency": currency, "description": description,
        "reference_id": reference_id,
        "customer": {"name": customer.get("name", ""), "email": customer.get("email", "")},
        "notify": {"sms": False, "email": False},  # synthetic contacts — never actually notify
    }
    try:
        resp = httpx.post(f"{API}/payment_links", json=payload,
                          auth=(key_id, key_secret), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return {"mode": "test", "id": data["id"], "short_url": data["short_url"], "status": data["status"]}
    except Exception as exc:
        # A flaky gateway call must never take down ingestion — degrade to a
        # mock link and record why, so the audit trail shows the truth.
        return {"mode": "mock-fallback", "id": f"plink_mock_{uuid.uuid4().hex[:12]}",
                "short_url": f"https://rzp.io/mock/{uuid.uuid4().hex[:8]}",
                "status": "created", "error": type(exc).__name__}
