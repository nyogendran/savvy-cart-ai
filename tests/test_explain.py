"""Explain API — only optimizer numbers may appear in the text."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from savvycart.http import app

FIX = Path(__file__).resolve().parents[1] / "fixtures"
NUMBER_RE = re.compile(r"\d+")


class FakeExplainClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], str]] = []

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("unused")

    def extract(self, image_bytes: bytes, schema: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("unused")

    def explain(self, plan_json: dict[str, Any], instruction: str) -> str:
        self.calls.append((plan_json, instruction))
        return "You save 99999."


def test_explanation_includes_discount_and_no_other_numbers():
    capped = json.loads((FIX / "baskets/capped.json").read_text(encoding="utf-8"))
    client = FakeExplainClient()
    app.state.model_client = client
    try:
        with TestClient(app) as http:
            response = http.post(
                "/v1/explain",
                json={
                    "line_ids": capped["lines"],
                    "day": {"weekday": "saturday", "date": "2026-10-17"},
                    "card_product_id": "commercial_bank_credit",
                    "usual_store": "keells",
                    "store_id": "keells",
                    "discount": 99999,
                },
            )
        assert response.status_code == 200
        body = response.json()
        text = body["text"]
        assert "1000" in text
        assert "99999" not in text
        numbers = NUMBER_RE.findall(text)
        assert numbers == ["1000"]
        assert len(client.calls) == 1
        assert client.calls[0][0]["discount"] == 1000
    finally:
        app.state.model_client = None
