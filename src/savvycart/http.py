"""FastAPI app: plans, mock approve, and receipt extract."""

from __future__ import annotations

import json
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from savvycart.optimizer import optimize
from savvycart.receipts import (
    EXTRACTS_PER_MINUTE,
    MAX_RECEIPT_BYTES,
    RECEIPT_LINES_SCHEMA,
    ExtractRateLimiter,
    MemoryStorage,
    PayloadTooLarge,
    RateLimited,
    extract_receipt,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
DATA_LABEL = "Sample catalog — not live shelf prices."

app = FastAPI(title="Savvy Cart AI", version="0.1.0")


class ModelClient(Protocol):
    """Model client for plans (must not be called on empty baskets) and receipts."""

    def generate(self, *args: Any, **kwargs: Any) -> Any: ...

    def extract(self, image_bytes: bytes, schema: dict[str, Any]) -> dict[str, Any] | str: ...


class NullModelClient:
    def __init__(self) -> None:
        self.calls = 0
        self.last_extract: tuple[bytes, dict[str, Any]] | None = None

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise RuntimeError("model client must not be called from /v1/plans in SC-004")

    def extract(self, image_bytes: bytes, schema: dict[str, Any]) -> dict[str, Any] | str:
        self.calls += 1
        self.last_extract = (image_bytes, schema)
        raise RuntimeError("configure a receipt model client on app.state.model_client")


class LineId(BaseModel):
    sku_id: str
    qty: int = Field(gt=0)


class Day(BaseModel):
    weekday: str
    date: str


class PlansRequest(BaseModel):
    line_ids: list[LineId]
    day: Day
    card_product_id: str
    usual_store: str


class ApproveRequest(BaseModel):
    line_ids: list[LineId]
    day: Day
    card_product_id: str
    usual_store: str
    store_id: str | None = None


@lru_cache(maxsize=1)
def _load_catalog() -> dict[str, Any]:
    return json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_offers() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "offers.json").read_text(encoding="utf-8"))["offers"]


def get_model_client(request: Request) -> ModelClient:
    client = getattr(request.app.state, "model_client", None)
    if client is None:
        client = NullModelClient()
        request.app.state.model_client = client
    return client


def get_storage(request: Request) -> MemoryStorage:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        storage = MemoryStorage()
        request.app.state.storage = storage
    return storage


def get_rate_limiter(request: Request) -> ExtractRateLimiter:
    limiter = getattr(request.app.state, "extract_rate_limiter", None)
    if limiter is None:
        clock = getattr(request.app.state, "clock", time.time)
        limiter = ExtractRateLimiter(clock=clock, limit=EXTRACTS_PER_MINUTE)
        request.app.state.extract_rate_limiter = limiter
    return limiter


def _plan_summary(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    return {
        "store_id": plan["store_id"],
        "complete": plan["complete"],
        "shelf_total": plan["shelf_total"],
        "eligible_subtotal": plan["eligible_subtotal"],
        "discount": plan["discount"],
        "naive_discount": plan["naive_discount"],
        "deferred_value": plan["deferred_value"],
        "effective_cost": plan["effective_cost"],
        "reason": plan["reason"],
        "offer_id": plan["offer_id"],
    }


def _other_offer_weekday(weekday: str) -> str:
    if weekday == "saturday":
        return "thursday"
    if weekday == "thursday":
        return "saturday"
    return "thursday"


def _date_for_weekday(anchor_date: str, weekday: str) -> str:
    """Pick a calendar date in Oct 2026 matching weekday (demo fixtures)."""
    # Fixed demo anchors — shelf prices are snapshot-dated, not calendar-live.
    mapping = {
        "saturday": "2026-10-17",
        "thursday": "2026-10-15",
    }
    return mapping.get(weekday, anchor_date)


@app.post("/v1/plans")
def create_plans(
    body: PlansRequest,
    model_client: ModelClient = Depends(get_model_client),
) -> dict[str, Any]:
    if len(body.line_ids) == 0:
        # Must not touch the model client (Gemini) on empty baskets.
        raise HTTPException(status_code=400, detail="line_ids must not be empty")

    # Successful path still must not call the model in SC-004 (receipts are later).
    _ = model_client

    catalog = _load_catalog()
    offers = _load_offers()
    lines = [line.model_dump() for line in body.line_ids]
    day = body.day.model_dump()

    result = optimize(catalog, offers, lines, day, body.usual_store)
    baseline_result = optimize(catalog, [], lines, day, body.usual_store)
    baseline = _plan_summary(baseline_result["winner"])

    winner = result["winner"]
    naive_crossed_out = False
    if winner is not None:
        naive_crossed_out = winner["naive_discount"] > winner["discount"]

    other_weekday = _other_offer_weekday(day["weekday"])
    sweep_days = {
        day["weekday"]: day["date"],
        other_weekday: _date_for_weekday(day["date"], other_weekday),
    }
    day_sweep: dict[str, Any] = {}
    for weekday, date in sweep_days.items():
        swept = optimize(
            catalog,
            offers,
            lines,
            {"weekday": weekday, "date": date},
            body.usual_store,
        )
        keells = next((p for p in swept["plans"] if p["store_id"] == "keells"), None)
        day_sweep[weekday] = _plan_summary(keells)

    return {
        "baseline": baseline,
        "plans": [_plan_summary(p) for p in result["plans"]],
        "naive_crossed_out": naive_crossed_out,
        "day_sweep": day_sweep,
        "data_label": DATA_LABEL,
        "winner": _plan_summary(winner),
        "card_product_id": body.card_product_id,
        "usual_store": body.usual_store,
        "day": day,
    }


@app.post("/v1/approve")
def approve_plan(body: ApproveRequest) -> dict[str, Any]:
    _ = body  # identity accepted; no partner call, no URL
    return {
        "preview_id": f"preview-{uuid.uuid4().hex}",
        "mock": True,
    }


@app.post("/v1/receipts")
async def create_receipt(
    request: Request,
    model_client: ModelClient = Depends(get_model_client),
    storage: MemoryStorage = Depends(get_storage),
    rate_limiter: ExtractRateLimiter = Depends(get_rate_limiter),
) -> dict[str, Any]:
    image_bytes = await request.body()
    if len(image_bytes) > MAX_RECEIPT_BYTES:
        raise HTTPException(status_code=413, detail="receipt image exceeds 4 MB")
    try:
        return extract_receipt(
            image_bytes,
            model_client=model_client,
            storage=storage,
            rate_limiter=rate_limiter,
            schema=RECEIPT_LINES_SCHEMA,
        )
    except PayloadTooLarge:
        raise HTTPException(status_code=413, detail="receipt image exceeds 4 MB") from None
    except RateLimited:
        raise HTTPException(status_code=429, detail="extract rate limit exceeded") from None
