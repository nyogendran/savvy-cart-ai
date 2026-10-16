"""Receipt image extract — call the model, never store the bytes."""

from __future__ import annotations

import json
from typing import Any, Callable, Protocol

MAX_RECEIPT_BYTES = 4 * 1024 * 1024
EXTRACTS_PER_MINUTE = 30

RECEIPT_LINES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw": {"type": "string"},
                    "sku_id": {"type": ["string", "null"]},
                    "qty": {"type": "integer"},
                    "confidence": {"type": "number"},
                },
                "required": ["raw", "sku_id", "qty", "confidence"],
            },
        }
    },
    "required": ["lines"],
}


class ReceiptModelClient(Protocol):
    def extract(self, image_bytes: bytes, schema: dict[str, Any]) -> dict[str, Any] | str: ...


class Storage(Protocol):
    def write(self, key: str, data: bytes) -> None: ...


class MemoryStorage:
    """Test double that records write attempts."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, bytes]] = []

    def write(self, key: str, data: bytes) -> None:
        self.writes.append((key, data))


class ExtractRateLimiter:
    """Process-local 30 extracts per clock minute."""

    def __init__(
        self,
        *,
        clock: Callable[[], float],
        limit: int = EXTRACTS_PER_MINUTE,
    ) -> None:
        self._clock = clock
        self._limit = limit
        self._minute: int | None = None
        self._count = 0

    def allow(self) -> bool:
        minute = int(self._clock() // 60)
        if self._minute != minute:
            self._minute = minute
            self._count = 0
        if self._count >= self._limit:
            return False
        self._count += 1
        return True


class PayloadTooLarge(Exception):
    pass


class RateLimited(Exception):
    pass


def extract_receipt(
    image_bytes: bytes,
    *,
    model_client: ReceiptModelClient,
    storage: Storage | None = None,
    rate_limiter: ExtractRateLimiter,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the model with image bytes + schema; never persist the bytes."""
    if len(image_bytes) > MAX_RECEIPT_BYTES:
        raise PayloadTooLarge(f"receipt exceeds {MAX_RECEIPT_BYTES} bytes")
    if not rate_limiter.allow():
        raise RateLimited("extract rate limit exceeded")

    schema = schema or RECEIPT_LINES_SCHEMA
    raw = model_client.extract(image_bytes, schema)
    if isinstance(raw, str):
        payload = json.loads(raw)
    else:
        payload = raw

    lines = payload["lines"]
    # Explicit non-use of storage: callers may pass a spy; we never write.
    _ = storage
    return {"lines": lines}
