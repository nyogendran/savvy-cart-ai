"""Plans API acceptance tests (SC-004)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from savvycart.http import NullModelClient, app


def test_empty_lines_do_not_call_the_model():
    client = NullModelClient()
    app.state.model_client = client
    try:
        with TestClient(app) as http:
            response = http.post(
                "/v1/plans",
                json={
                    "line_ids": [],
                    "day": {"weekday": "saturday", "date": "2026-10-17"},
                    "card_product_id": "commercial_bank_credit",
                    "usual_store": "keells",
                },
            )
        assert response.status_code == 400
        assert client.calls == 0
    finally:
        app.state.model_client = None
