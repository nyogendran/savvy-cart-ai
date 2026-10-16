"""Receipt extract API — model call, no image persistence, rate limit."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from savvycart.http import app
from savvycart.receipts import RECEIPT_LINES_SCHEMA, MemoryStorage


class FakeReceiptClient:
    def __init__(self, lines: list[dict[str, Any]]) -> None:
        self.lines = lines
        self.calls: list[tuple[bytes, dict[str, Any]]] = []

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("plans generate must not be used by receipts")

    def extract(self, image_bytes: bytes, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((image_bytes, schema))
        return {"lines": self.lines}


def test_extract_calls_model_and_drops_image_bytes():
    sample = b"\x89PNG\r\n\x1a\n" + b"fake-receipt-bytes"
    expected_lines = [
        {"raw": "RICE 5KG", "sku_id": "rice_5kg", "qty": 1, "confidence": 0.9},
        {"raw": "CHICKEN 1KG", "sku_id": "chicken_1kg", "qty": 1, "confidence": 0.9},
    ]
    client = FakeReceiptClient(expected_lines)
    storage = MemoryStorage()
    # Clock fixed inside one minute so calls 1..30 succeed and 31 is 429.
    app.state.model_client = client
    app.state.storage = storage
    app.state.clock = lambda: 1_700_000_000.0  # fixed epoch second
    app.state.extract_rate_limiter = None  # rebuild with injected clock

    try:
        with TestClient(app) as http:
            response = http.post(
                "/v1/receipts",
                content=sample,
                headers={"content-type": "application/octet-stream"},
            )
            assert response.status_code == 200
            assert response.json() == {"lines": expected_lines}
            assert len(client.calls) == 1
            assert client.calls[0][0] == sample
            assert client.calls[0][1] == RECEIPT_LINES_SCHEMA
            assert storage.writes == []

            for _ in range(29):
                ok = http.post(
                    "/v1/receipts",
                    content=sample,
                    headers={"content-type": "application/octet-stream"},
                )
                assert ok.status_code == 200

            limited = http.post(
                "/v1/receipts",
                content=sample,
                headers={"content-type": "application/octet-stream"},
            )
            assert limited.status_code == 429
            assert len(client.calls) == 30
            assert storage.writes == []

            too_big = http.post(
                "/v1/receipts",
                content=b"x" * (4 * 1024 * 1024 + 1),
                headers={"content-type": "application/octet-stream"},
            )
            assert too_big.status_code == 413
            assert len(client.calls) == 30
            assert storage.writes == []
    finally:
        app.state.model_client = None
        app.state.storage = None
        app.state.clock = None
        app.state.extract_rate_limiter = None
