from __future__ import annotations

import hmac
import hashlib
import time
import json

from fastapi import status

from app.core.config import settings
from tests.conftest import auth_headers, register_and_login  # type: ignore


def test_stripe_webhook_signature_verification(client, monkeypatch):
    # Configure a temporary webhook secret
    secret = "whsec_testsecret"
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)
    # Force settings reload if necessary (settings is cached; for tests, assume it's read once on startup)
    settings.stripe_webhook_secret = secret

    # Build a minimal Stripe-like event
    payload = {"type": "invoice.payment_succeeded", "data": {"object": {"id": "evt_test_123"}}}
    raw = json.dumps(payload)
    t = str(int(time.time()))
    signed_payload = f"{t}.{raw}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    headers = {"Stripe-Signature": f"t={t},v1={sig}"}

    resp = client.post(f"{settings.api_v1_str}/billing/webhook/stripe", data=raw, headers=headers)
    assert resp.status_code == status.HTTP_200_OK, resp.text

    # Tamper signature
    bad_headers = {"Stripe-Signature": f"t={t},v1=deadbeef"}
    resp_bad = client.post(f"{settings.api_v1_str}/billing/webhook/stripe", data=raw, headers=bad_headers)
    assert resp_bad.status_code == status.HTTP_400_BAD_REQUEST
