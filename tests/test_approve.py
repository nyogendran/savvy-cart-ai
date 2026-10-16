"""Approve API acceptance tests (SC-004)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from savvycart.http import app

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def test_approve_body_is_only_preview_id_and_mock():
    capped = json.loads((FIX / "baskets/capped.json").read_text(encoding="utf-8"))
    with TestClient(app) as http:
        response = http.post(
            "/v1/approve",
            json={
                "line_ids": capped["lines"],
                "day": {"weekday": "saturday", "date": "2026-10-17"},
                "card_product_id": "commercial_bank_credit",
                "usual_store": "keells",
                "store_id": "keells",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"preview_id", "mock"}
    assert body["mock"] is True
    assert isinstance(body["preview_id"], str) and len(body["preview_id"]) > 0
    assert "url" not in body
    assert "http" not in body["preview_id"].lower()
