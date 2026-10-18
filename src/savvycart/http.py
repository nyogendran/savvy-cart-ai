"""FastAPI app: v2 guided guest flow, plus the v1 plans, approve, receipt, and explain API."""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import html
import json
import logging
import os
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, quote

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from savvycart.explain import ensure_discount_sentence, explain_plan, numbers_in_plan
from savvycart.gemini import ModelResponseError, UnsupportedImage
from savvycart.optimizer import optimize
from savvycart.receipts import (
    EXTRACTS_PER_MINUTE,
    MAX_RECEIPT_BYTES,
    RECEIPT_LINES_SCHEMA,
    RECEIPT_LINES_SCHEMA_V2,
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
logger = logging.getLogger("savvycart")


class ModelClient(Protocol):
    """Model client for plans, receipts, and explain."""

    def generate(self, *args: Any, **kwargs: Any) -> Any: ...

    def extract(self, image_bytes: bytes, schema: dict[str, Any]) -> dict[str, Any] | str: ...

    def explain(self, plan_json: dict[str, Any], instruction: str) -> str: ...


class ModelNotConfigured(RuntimeError):
    pass


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
        raise ModelNotConfigured("no receipt model is configured")

    def explain(self, plan_json: dict[str, Any], instruction: str) -> str:
        self.calls += 1
        raise ModelNotConfigured("no explain model is configured")


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


class ExplainRequest(BaseModel):
    line_ids: list[LineId]
    day: Day
    card_product_id: str
    usual_store: str
    store_id: str
    # Client-supplied discount is ignored if present.
    discount: int | None = None


@lru_cache(maxsize=1)
def _load_catalog() -> dict[str, Any]:
    return json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_offers() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "offers.json").read_text(encoding="utf-8"))["offers"]


def _model_configured() -> bool:
    model = os.environ.get("GEMINI_MODEL", "")
    has_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    # Agent Platform (formerly Vertex AI) authenticates with the runtime service account; no key.
    enterprise = any(
        os.environ.get(flag, "").lower() == "true"
        for flag in ("GOOGLE_GENAI_USE_ENTERPRISE", "GOOGLE_GENAI_USE_VERTEXAI")
    )
    return bool(model and (has_key or enterprise))


def _default_model_client() -> ModelClient:
    if _model_configured():
        from savvycart.gemini import GeminiModelClient

        return GeminiModelClient(os.environ["GEMINI_MODEL"])
    return NullModelClient()


def get_model_client(request: Request) -> ModelClient:
    client = getattr(request.app.state, "model_client", None)
    if client is None:
        client = _default_model_client()
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
        clock = getattr(request.app.state, "clock", None) or time.time
        limiter = ExtractRateLimiter(clock=clock, limit=EXTRACTS_PER_MINUTE)
        request.app.state.extract_rate_limiter = limiter
    return limiter


MODEL_EXPLANATIONS_PER_MINUTE = 20


def model_rate_limiter(app_: FastAPI) -> ExtractRateLimiter:
    """Process-wide cap on Gemini explanation runs, so a public URL cannot run up model cost."""
    limiter = getattr(app_.state, "model_rate_limiter", None)
    if limiter is None:
        clock = getattr(app_.state, "clock", None) or time.time
        limiter = ExtractRateLimiter(clock=clock, limit=MODEL_EXPLANATIONS_PER_MINUTE)
        app_.state.model_rate_limiter = limiter
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
        "lines": [
            {
                "sku_id": line["sku_id"],
                "qty": line["qty"],
                "status": line["status"],
                "shelf_lkr": line["shelf_lkr"],
            }
            for line in plan["lines"]
        ],
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

    tools: list[str] = []
    catalog = _load_catalog()
    tools.append("catalog")
    offers = _load_offers()
    tools.append("offers")
    lines = [line.model_dump() for line in body.line_ids]
    day = body.day.model_dump()

    result = optimize(catalog, offers, lines, day, body.usual_store)
    tools.append("optimizer")
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
        "tools": tools,
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
    catalog: str = "v1",
) -> dict[str, Any]:
    image_bytes = await request.body()
    if len(image_bytes) > MAX_RECEIPT_BYTES:
        raise HTTPException(status_code=413, detail="receipt image exceeds 4 MB")
    try:
        return await asyncio.to_thread(
            extract_receipt,
            image_bytes,
            model_client=model_client,
            storage=storage,
            rate_limiter=rate_limiter,
            schema=RECEIPT_LINES_SCHEMA_V2 if catalog == "v2" else RECEIPT_LINES_SCHEMA,
        )
    except PayloadTooLarge:
        raise HTTPException(status_code=413, detail="receipt image exceeds 4 MB") from None
    except RateLimited:
        raise HTTPException(status_code=429, detail="extract rate limit exceeded") from None
    except UnsupportedImage:
        raise HTTPException(status_code=415, detail="send a PNG or JPEG receipt image") from None
    except ModelNotConfigured:
        raise HTTPException(status_code=503, detail="receipt model not configured") from None
    except ModelResponseError:
        raise HTTPException(status_code=502, detail="the receipt model did not return usable lines") from None


@app.post("/v1/explain")
def explain(
    body: ExplainRequest,
    request: Request,
    model_client: ModelClient = Depends(get_model_client),
) -> dict[str, Any]:
    _ = body.discount  # never trusted — optimizer is the source of truth
    catalog = _load_catalog()
    offers = _load_offers()
    lines = [line.model_dump() for line in body.line_ids]
    day = body.day.model_dump()
    result = optimize(catalog, offers, lines, day, body.usual_store)
    plan = next((p for p in result["plans"] if p["store_id"] == body.store_id), None)
    if plan is None or not plan["complete"]:
        raise HTTPException(status_code=400, detail="no complete plan for store_id")
    summary = _plan_summary(plan)
    assert summary is not None
    source = "model"
    try:
        if not model_rate_limiter(request.app).allow():
            raise ModelResponseError("explanation rate limit reached")
        explained = explain_plan(summary, model_client=model_client)
    except (ModelNotConfigured, ModelResponseError):
        source = "engine"
        explained = {"text": ensure_discount_sentence("", int(summary["discount"])), "cited_fields": ["discount"]}
    return {
        "text": explained["text"],
        "cited_fields": explained["cited_fields"],
        "source": source,
    }


# --- Guest flow v2: Pantry -> Wallet -> Plan -> Why -> Approve (server-rendered, no login) ---

import difflib
import re as _re
from datetime import date as _date
from datetime import timedelta as _timedelta
from math import ceil as _ceil
from math import floor as _floor

from fastapi.staticfiles import StaticFiles

from savvycart import offercheck
from savvycart.guardrails import clean_text, grounding_view, result_grounds, session_state
from savvycart.pantry import pantry as compute_pantry
from savvycart.partners import router as partners_router
from itertools import combinations

from savvycart.planner import MAX_QTY, MAX_STORES, WEEKDAYS, day_sweep
from savvycart.planner import _best_promotion as best_promotion
from savvycart.planner import _lkr as planner_lkr
from savvycart.planner import plan_day as engine_plan_day

V2 = FIXTURES / "v2"
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(partners_router)

V2_BANNER = (
    "Sample data, not live; savings are simulated. Keells prices come from one shopper's real receipts. Purchase history is 26 real "
    "Keells bills plus 17 fictional Cargills and Glomark bills. Nations Trust Bank and Commercial Bank offers are their published "
    "headlines from 18 Oct 2026 with assumed terms. Other prices, store promotions, and HNB offers are fictional demo shapes."
)
STEPS = ["Pantry", "Wallet", "Plan", "Why", "Approve"]
STEP_ACTIONS = ["pantry", "wallet", "plan", "why", "approve"]
STORE_NAMES = {"keells": "Keells", "cargills": "Cargills", "spar": "SPAR", "glomark": "Glomark"}
WALLET_CARDS = [("Commercial Bank", "credit"), ("Nations Trust Bank", "credit"), ("HNB", "credit")]
V2_DEFAULTS = {"today": "2026-10-22", "usual_store": "keells", "max_stores": "2", "trip_cost": "250", "budget": "12000",
               "delivery_fee": "350"}
PLAN_DATES = [(_date(2026, 10, 17) + _timedelta(days=n)) for n in range(15)]
SUGGEST_DAYS = 14
TERMS_NOTE = "Minimum and cap are assumptions; check the bank's terms."
NO_DELIVERY_INTEGRATION = "No booking is made. Savvy Cart is not integrated with Uber, PickMe, or any store."
SAMPLE_RECEIPT_V2 = ROOT / "samples" / "receipts" / "keells-2026-10-17.expected.json"
RECEIPT_TYPES = {"image/jpeg", "image/png"}
STATUS_TEXT = {"due": "Due", "soon": "Soon", "ok": "OK", "unknown": "Not enough history", "stale": "Not bought for a while",
               "added": "Added by you"}
AGENT_TIMEOUT_SECONDS = 100
MAX_QUESTION = 300
SAMPLE_QUESTIONS = ("Would one store be enough if I drop the extra trip?", "What if I only use my Commercial Bank card?",
                    "Is Sunday cheaper than the day you picked?")
AGENT_QUESTION_V2 = (
    "Explain to the shopper, in a few short sentences, why this is the cheapest way to buy these groceries: "
    "which store and card for which items, and what they save against their usual store. "
    "If another day or fewer stores would change the answer, you may compare with plan_day and say so."
)


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _money(value: Any) -> str:
    return f"LKR {int(value):,}" if isinstance(value, (int, float)) else "n/a"


def _v2_json(name: str) -> Any:
    return json.loads((V2 / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _v2_catalog() -> dict[str, Any]:
    return _v2_json("catalog.json")


@lru_cache(maxsize=None)
def _v2_offers() -> dict[str, Any]:
    return _v2_json("offers.json")


@lru_cache(maxsize=None)
def _v2_history_map() -> dict[str, str]:
    return _v2_json("history-map.json")


@lru_cache(maxsize=None)
def _v2_history() -> tuple[dict[str, Any], ...]:
    real = json.loads((ROOT / "samples" / "purchase-history.json").read_text(encoding="utf-8"))["bills"]
    return tuple(real + _v2_json("history-fictional.json")["bills"])


def _canonical_raw(raw: str) -> str | None:
    """Map receipt text to a known history description, exact first, then a close match."""
    history_map = _v2_history_map()
    text = " ".join(str(raw).upper().split())
    if text in history_map:
        return text
    close = difflib.get_close_matches(text, list(history_map), n=1, cutoff=0.85)
    return close[0] if close else None


def _form_date(value: Any) -> _date | None:
    """An ISO date from untrusted form state, kept far from the calendar limits the pantry arithmetic would overflow."""
    try:
        day = _date.fromisoformat(str(value))
    except ValueError:
        return None
    return day if _date(2000, 1, 1) <= day <= _date(2100, 12, 31) else None


def _clean_added(value: Any) -> list[dict[str, Any]]:
    """Purchases added this session from receipts; the hidden field is untrusted."""
    if not isinstance(value, list):
        return []
    cleaned = []
    for row in value[:60]:
        if not isinstance(row, dict):
            continue
        raw = _canonical_raw(row.get("raw", ""))
        day = _form_date(row.get("date", ""))
        try:
            qty = float(row.get("qty", 1))
        except (TypeError, ValueError):
            continue
        if raw and day and 0 < qty <= MAX_QTY:
            cleaned.append({"raw": raw, "qty": qty, "date": day.isoformat()})
    return cleaned


def _added_bills(added: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bills: dict[str, dict[str, Any]] = {}
    for row in added:
        bill = bills.setdefault(row["date"], {"date": row["date"], "chain": "keells", "source": "receipt", "lines": [],
                                              "promotions": [], "card_offers": [], "gross_lkr": 0, "net_lkr": 0})
        bill["lines"].append({"line": len(bill["lines"]) + 1, "raw": row["raw"], "qty": row["qty"], "unit_lkr": 0, "amount_lkr": 0})
    return list(bills.values())


MATCH_CONFIDENCE = 0.6


def _raw_for_sku(sku_id: Any) -> str | None:
    """A known history description for a catalog item, so a Gemini catalog match enters the pantry history."""
    return next((raw for raw, sku in _v2_history_map().items() if sku == sku_id), None)


def _receipt_rows(lines: list[dict[str, Any]], today: str) -> tuple[list[dict[str, Any]], list[str]]:
    rows, left_out = [], []
    for line in lines:
        raw = _canonical_raw(line.get("raw", ""))
        if raw is None:
            try:
                confident = float(line.get("confidence", 0)) >= MATCH_CONFIDENCE
            except (TypeError, ValueError):
                confident = False
            raw = _raw_for_sku(line.get("sku_id")) if confident else None
        try:
            qty = float(line.get("qty", 1))
        except (TypeError, ValueError):
            qty = 0
        if raw and 0 < qty <= MAX_QTY:
            rows.append({"raw": raw, "qty": qty, "date": today})
        else:
            left_out.append(str(line.get("raw", "")))
    return rows, left_out


def _is_stale(item: dict[str, Any]) -> bool:
    return item["status"] == "due" and item.get("days_left", 0) < -item.get("cadence_days", 0)


async def _internal_post(request: Request, path: str, **kwargs: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=request.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://savvycart.internal") as client:
        return await client.post(path, **kwargs)


def _parse_state(form: dict[str, list[str]]) -> dict[str, Any]:
    def get(key: str, default: str) -> str:
        return form.get(key, [default])[0]

    def bounded_int(key: str, default: str, low: int, high: int) -> int:
        try:
            value = int(float(get(key, default)))
        except (OverflowError, ValueError):
            value = int(default)
        return min(max(value, low), high)

    today = _form_date(get("today", V2_DEFAULTS["today"]))
    if today not in PLAN_DATES:
        today = _date.fromisoformat(V2_DEFAULTS["today"])
    max_stores = get("max_stores", V2_DEFAULTS["max_stores"])
    sku_ids = {sku["id"] for sku in _v2_catalog()["skus"]}
    banks_known = [bank for bank, _ in WALLET_CARDS]
    if "wallet_set" in form:
        banks = [b for b in banks_known if b in form.get("bank", [])]
    else:
        banks = banks_known
    try:
        added = _clean_added(json.loads(get("receipt_json", "[]")))
    except json.JSONDecodeError:
        added = []
    usual = get("usual_store", V2_DEFAULTS["usual_store"])
    return {
        "today": today,
        "usual_store": usual if usual in STORE_NAMES else V2_DEFAULTS["usual_store"],
        "max_stores": int(max_stores) if max_stores in {str(n) for n in range(1, MAX_STORES + 1)} else int(V2_DEFAULTS["max_stores"]),
        "trip_cost": bounded_int("trip_cost", V2_DEFAULTS["trip_cost"], 0, 5000),
        "budget": bounded_int("budget", V2_DEFAULTS["budget"], 0, 1_000_000),
        "banks": banks,
        "wallet_set": "wallet_set" in form,
        "day": get("day", ""),
        "added": added,
        "pantry_set": "pantry_set" in form,
        "checked": set(form.get("sku", [])) & sku_ids,
        "extra": [s for s in dict.fromkeys(form.get("extra", [])) if s in sku_ids],
        "qty": {key[4:]: get(key, "") for key in form if key.startswith("qty_") and key[4:] in sku_ids},
        "fulfilment": "delivery" if get("fulfilment", "pickup") == "delivery" else "pickup",
        "delivery_fee": bounded_int("delivery_fee", V2_DEFAULTS["delivery_fee"], 0, 5000),
        "question": " ".join((get("question_chip", "") or get("question", "")).split())[:MAX_QUESTION],
        "held_raw": get("held_offer", "")[:4000],
    }


def _half_kilos(kg: float) -> float:
    """Loose produce is bought in half kilos: nearest 0.5 kg, halves rounded up, at least 0.5."""
    return max(0.5, _floor(kg / 0.5 + 0.5) * 0.5)


def _pantry_view(state: dict[str, Any]) -> list[dict[str, Any]]:
    bills = list(_v2_history()) + _added_bills(state["added"])
    items = compute_pantry(bills, _v2_catalog(), _v2_history_map(), state["today"])
    for item in items:
        upcoming = item["status"] in ("due", "soon")
        added_by_shopper = item["sku_id"] in state["extra"] and not upcoming
        item["display_status"] = "stale" if _is_stale(item) else ("added" if added_by_shopper else item["status"])
        default_on = (upcoming and not _is_stale(item)) or added_by_shopper
        item["checked"] = (item["sku_id"] in state["checked"]) if state["pantry_set"] else default_on
        try:
            qty = float(state["qty"].get(item["sku_id"], ""))
        except ValueError:
            qty = 0
        usual = item.get("usual_qty") or 1
        chosen = qty if 0 < qty <= MAX_QTY else usual
        # A pack, tin, or carton is a whole unit; only produce priced by weight keeps a fraction.
        item["qty"] = _half_kilos(chosen) if item.get("divisible") else max(1, _ceil(chosen))
    return items


def _lines(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"sku_id": i["sku_id"], "qty": i["qty"]} for i in items if i["checked"]]


def _deadline(items: list[dict[str, Any]], today: _date) -> str:
    dues = [i["next_due"] for i in items if i["checked"] and i.get("next_due") and not _is_stale(i)]
    earliest = min(dues) if dues else (today + _timedelta(days=6)).isoformat()
    return max(earliest, today.isoformat())


CHECKED_PREFIX = "Checked offer ("
_HELD: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("held_offer", default=None)


def _rule_raw(rule: dict[str, Any]) -> dict[str, Any]:
    """A checked rule as the terms the shopper confirmed, so it can travel in a hidden field and be validated again."""
    return {"bank": rule["bank"], "card_products": rule["card_products"], "headline": rule["headline"], "store_id": rule["store_id"],
            "percent_off": rule["rate_bps"] / 100, "days": rule["days"], "minimum_bill_lkr": rule["min_bill_lkr"],
            "minimum_applies_to": "whole_bill" if rule["minimum_basis"] == "bill" else "eligible_items",
            "max_discount_lkr": rule["cap_lkr"], "excluded_items": rule["excluded_items"],
            "applies_only_to": [c for c in rule.get("include_categories", []) if c != "none"] or rule.get("applies_only_to", []),
            "max_units_per_item": rule["max_units_per_item"],
            "combines_with_store_offers": rule["stacks_with_promotions"] if rule.get("stacks_stated", True) else None,
            "valid_until": rule["valid_to"], "is_up_to": rule["is_up_to"], "exclude_sku_ids": rule["exclude_sku_ids"]}


def _held_from(raw_json: str, today: _date) -> dict[str, Any] | None:
    """The hidden field's terms, validated exactly like a fresh read; anything malformed means no checked offer."""
    try:
        raw = json.loads(raw_json) if raw_json else None
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    rule, _ = offercheck.validate_rule(raw, _v2_catalog(), "checked", today)
    if rule is None:
        return None
    sku_ids = {s["id"] for s in _v2_catalog()["skus"]}
    marked = raw.get("exclude_sku_ids")
    if isinstance(marked, list):
        rule["exclude_sku_ids"] = sorted({str(s) for s in marked} & sku_ids)
    return rule


def _held_notice(plan: dict[str, Any]) -> str:
    if _HELD.get() is None:
        return ""
    used = any(str((b["card"] or {}).get("bank", "")).startswith(CHECKED_PREFIX) for b in plan["stores"])
    lead = ("<strong>This plan uses the offer you checked</strong>, with the terms as you confirmed them; the bank has not confirmed them."
            if used else "<strong>The offer you checked was considered</strong>, but your own cards cost less for this plan, so no bill uses it.")
    return (f'<div class="callout"><div>{lead}</div>'
            '<button type="submit" name="action" value="drop_offer">Remove the checked offer</button></div>')


def _held_offer() -> dict[str, Any] | None:
    """The offer the shopper checked and chose to plan with, in the planner's shape, for this request only."""
    rule = _HELD.get()
    if rule is None:
        return None
    # Its own key, so holding it never unlocks that bank's other offers.
    return {**offercheck.planner_offer(rule), "id": "checked_offer", "bank": f"{CHECKED_PREFIX}{rule['bank']})", "source": "checked"}


def _plan_inputs(banks: list[str]) -> tuple[dict[str, Any], list[str]]:
    held = _held_offer()
    if held is None:
        return _v2_offers(), banks
    offers = _v2_offers()
    return {**offers, "card_offers": offers["card_offers"] + [held]}, banks + [held["bank"]]


@lru_cache(maxsize=256)
def _engine_cached(kind: str, key: str) -> str:
    args = json.loads(key)
    offers, banks = _v2_offers(), args["banks"]
    if args["held"]:
        offers = {**offers, "card_offers": offers["card_offers"] + [args["held"]]}
    if kind == "sweep":
        result = day_sweep(_v2_catalog(), offers, args["lines"], args["start"], args["deadline"], banks,
                           args["max_stores"], args["trip_cost"], args["usual_store"])
    else:
        result = engine_plan_day(_v2_catalog(), offers, args["lines"], args["day"], banks, args["max_stores"], args["trip_cost"],
                                 args["usual_store"], _with_baselines=args["baselines"])
    return json.dumps(result)


def _engine(kind: str, lines: list[dict[str, Any]], banks: list[str], max_stores: int, trip_cost: int, usual_store: str,
            **extra: Any) -> dict[str, Any]:
    """The day sweep or one day's plan, cached by its inputs; each caller gets its own copy."""
    _, all_banks = _plan_inputs(banks)
    # The engine functions' identity is part of the key, so a swapped engine (a test double) never reads another's results.
    key = json.dumps({"lines": lines, "banks": all_banks, "max_stores": max_stores, "trip_cost": trip_cost, "usual_store": usual_store,
                      "held": _held_offer(), "baselines": True, "engine": [id(engine_plan_day), id(day_sweep)], **extra}, sort_keys=True)
    return json.loads(_engine_cached(kind, key))


def _engine_plan(state: dict[str, Any], items: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    lines = _lines(items)
    common = (lines, state["banks"], state["max_stores"], state["trip_cost"], state["usual_store"])
    deadline = _deadline(items, state["today"])
    if _HELD.get() is not None and state["day"] > deadline:
        deadline = state["day"]  # the checked offer's day stays in reach
    sweep = _engine("sweep", *common, start=state["today"].isoformat(), deadline=deadline)
    days = {d["date"] for d in sweep["days"]}
    day = state["day"] if state["day"] in days else sweep["best"]["date"]
    plan = _engine("day", *common, day=day)
    return plan, sweep


def _step_nav(current: int) -> str:
    items = []
    for index, name in enumerate(STEPS):
        attrs = ' aria-current="step"' if index == current else ""
        cls = ' class="done"' if index < current else ""
        if index < current:
            label = f'<button type="submit" class="linklike" name="action" value="{STEP_ACTIONS[index]}">{name}</button>'
        else:
            label = f"<span>{name}</span>"
        items.append(f"<li{cls}{attrs}>{label}</li>")
    return f'<nav class="steps" aria-label="Steps"><ol>{"".join(items)}</ol></nav>'


def _nav(back: str | None, buttons: list[tuple[str, str, bool]]) -> str:
    """Back on the left; forward actions on the right, the primary one last."""
    back_html = f'<button type="submit" name="action" value="{back}" class="back">Back</button>' if back else "<span></span>"
    primary_class = ' class="primary"'
    forward = "".join(
        f'<button type="submit" name="action" value="{value}"{primary_class if primary else ""}>{_e(label)}</button>'
        for value, label, primary in buttons
    )
    return f'<div class="wizard-nav">{back_html}<div class="actions">{forward}</div></div>'


def _short_date(iso: str) -> str:
    day = _date.fromisoformat(iso)
    return f"{day.day} {day:%b}"


def _reason_text(item: dict[str, Any]) -> str:
    """Plain-language version of the pantry reason, built from the same fields."""
    if item["status"] == "unknown":
        return item["reason"]
    left = item["days_left"]
    when = "today" if left == 0 else (f"in {left} day{'s' if left != 1 else ''}" if left > 0 else f"overdue by {-left} day{'s' if left != -1 else ''}")
    text = (f"Bought on {item['purchase_dates']} days, about every {item['cadence_days']} days. "
            f"Last bought {_short_date(item['last_bought'])}, so due {_short_date(item['next_due'])} ({when}).")
    if _is_stale(item):
        text += " Not bought for a while, so it starts unchecked."
    return text


def _timing_text(item: dict[str, Any]) -> str:
    left = item["days_left"]
    if left == 0:
        return "Due today"
    days = f"{abs(left)} day{'s' if abs(left) != 1 else ''}"
    return f"Due in {days}" if left > 0 else f"Overdue by {days}"


def _qty_text(qty: Any) -> str:
    return f"{float(qty):g}"


def _render_pantry(items: list[dict[str, Any]], state: dict[str, Any], note: str | None) -> str:
    def row(item: dict[str, Any]) -> str:
        sku = _e(item["sku_id"])
        status = item["display_status"]
        if status == "added":
            reason = '<span class="reason">You added this item.</span>'
        elif item["status"] == "unknown":
            reason = f'<span class="reason">{_e(item["reason"])}</span>'
        else:
            reason = (f'<details class="reason"><summary>{_e(_timing_text(item))}'
                      f'<span class="sr-only">: {_e(item["name"])}</span></summary>'
                      f"<p>{_e(_reason_text(item))}</p></details>")
        divisible = item.get("divisible")
        step, mn = ("0.5", "0.5") if divisible else ("1", "1")
        unit = "kg" if divisible else "pack" if "pack" in item["name"].lower() else ""
        unit_html = f'<span class="unit" aria-hidden="true">{unit}</span>'
        return (
            '<div class="item">'
            f'<input type="checkbox" id="sku_{sku}" name="sku" value="{sku}"{" checked" if item["checked"] else ""}>'
            f'<label class="name" for="sku_{sku}">{_e(item["name"])} <span class="status {_e(status)}">{_e(STATUS_TEXT[status])}</span></label>'
            f'<span class="qty"><label class="sr-only" for="qty_{sku}">Quantity of {_e(item["name"])}{" in kg" if divisible else ""}</label>'
            f'<input type="number" id="qty_{sku}" name="qty_{sku}" min="{mn}" max="{MAX_QTY}" step="{step}" value="{_qty_text(item["qty"])}">{unit_html}</span>'
            f"{reason}"
            "</div>"
        )

    upcoming = [i for i in items if i["display_status"] in ("due", "soon", "stale", "added")]
    later = [i for i in items if i["display_status"] in ("ok", "unknown")]
    dates = "".join(
        f'<option value="{d.isoformat()}"{" selected" if d == state["today"] else ""}>{d:%a} {d.day} {d:%b} {d.year}</option>'
        for d in PLAN_DATES
    )
    addable = "".join(f'<option value="{_e(i["sku_id"])}">{_e(i["name"])}</option>' for i in later)
    add_html = (
        '<div class="field add-item"><label for="add_sku">Add an item</label>'
        f'<div class="inline"><select id="add_sku" name="add_sku">{addable}</select>'
        '<label class="sr-only" for="add_qty">Quantity to add</label>'
        f'<input type="number" id="add_qty" name="add_qty" min="0.5" max="{MAX_QTY}" step="0.5" value="1">'
        '<button type="submit" name="action" value="add">Add</button></div>'
        '<p class="source">Only items in the catalog can be added, because only they have prices. '
        "Packs are whole numbers, so a half pack is rounded up; loose produce is in half kilos.</p></div>"
    ) if later else ""
    return (
        '<section class="step" id="pantry" aria-labelledby="pantry-h">'
        '<h2 id="pantry-h">1. Pantry: what is running low</h2>'
        '<p class="lead"><strong>Check what you need for your next shop.</strong> '
        "Estimated from purchase history: the usual gap between buys, and the last purchase date. No guessing model.</p>"
        f"{note or ''}"
        '<div class="grid two">'
        '<div class="field"><label for="today">Planning date (17 to 31 Oct 2026)</label>'
        f'<div class="inline"><select id="today" name="today">{dates}</select>'
        '<button type="submit" name="action" value="pantry" id="date-update">Update</button></div></div>'
        '<div class="field"><label for="receipt_photo">Add a receipt to the history (JPEG or PNG photo)</label>'
        '<input type="file" id="receipt_photo" name="receipt_photo" accept="image/jpeg,image/png">'
        '<div class="actions tight"><button type="submit" name="action" value="upload">Upload a receipt photo</button>'
        '<button type="submit" name="action" value="sample">Use sample receipt</button></div>'
        '<p class="source">Photos go to Gemini to read the items, and are never stored. Only regular items are kept.</p></div>'
        "</div>"
        f'<h3>Due or soon ({len(upcoming)})</h3>{"".join(row(i) for i in upcoming) or "<p>Nothing runs out within 7 days.</p>"}'
        f'<details><summary>Later or not enough history ({len(later)})</summary>{"".join(row(i) for i in later)}</details>'
        f"{add_html}"
        '<input type="hidden" name="pantry_set" value="1">'
        f'{_nav(None, [("wallet", "Next: wallet", True)])}'
        "</section>"
        '<script>document.getElementById("today").addEventListener("change",function(){document.getElementById("date-update").click();});</script>'
    )


def _render_wallet(state: dict[str, Any]) -> str:
    cards = "".join(
        f'<div class="check"><input type="checkbox" id="bank_{i}" name="bank" value="{_e(bank)}"{" checked" if bank in state["banks"] else ""}>'
        f'<label for="bank_{i}">{_e(bank)} {_e(product)}</label></div>'
        for i, (bank, product) in enumerate(WALLET_CARDS)
    )
    stores = "".join(
        f'<option value="{s}"{" selected" if s == state["usual_store"] else ""}>{_e(name)}</option>' for s, name in STORE_NAMES.items()
    )
    store_counts = "".join(
        f'<option value="{n}"{" selected" if state["max_stores"] == n else ""}>{"One store" if n == 1 else f"Up to {n} stores"}</option>'
        for n in range(1, MAX_STORES + 1)
    )
    return (
        '<section class="step" id="wallet" aria-labelledby="wallet-h">'
        '<h2 id="wallet-h">2. Wallet and trip</h2>'
        '<p class="lead">Cards are an issuer and product only. Savvy Cart never asks for a card number.</p>'
        '<div class="grid two">'
        f'<fieldset><legend>Cards you hold</legend>{cards}</fieldset>'
        "<fieldset><legend>Trip</legend>"
        f'<div class="field"><label for="usual_store">Usual store</label><select id="usual_store" name="usual_store">{stores}</select></div>'
        f'<div class="field"><label for="max_stores">Stores in one day</label><select id="max_stores" name="max_stores">{store_counts}</select></div>'
        f'<div class="field"><label for="trip_cost">Cost of an extra store visit (LKR, your estimate)</label>'
        f'<input type="number" id="trip_cost" name="trip_cost" min="0" max="5000" step="10" value="{state["trip_cost"]}"></div>'
        f'<div class="field"><label for="budget">Budget (LKR, shown only)</label>'
        f'<input type="number" id="budget" name="budget" min="0" step="100" value="{state["budget"]}"></div>'
        "</fieldset></div>"
        '<input type="hidden" name="wallet_set" value="1">'
        '<div class="callout"><div><strong>Got a bank offer by SMS?</strong> See what it really pays on this basket before you shop.</div>'
        '<button type="submit" name="action" value="offer">Check a card offer</button></div>'
        f'{_nav("pantry", [("refused", "Show a basket this offer refuses", False), ("plan", "Next: plan my shopping", True)])}'
        "</section>"
    )


def _offer(offer_id: str) -> dict[str, Any]:
    held = _held_offer()
    if held is not None and offer_id == held["id"]:
        return held
    return next(o for o in _v2_offers()["card_offers"] if o["id"] == offer_id)


def _render_bill(bill: dict[str, Any]) -> str:
    store = bill["store_id"]
    skus = {sku["id"]: sku for sku in _v2_catalog()["skus"]}
    sources = {l["price_source"] for l in bill["lines"]}
    mixed = len(sources) > 1

    def row(l: dict[str, Any]) -> str:
        sku = skus[l["sku_id"]]
        mark = " *" if mixed and l["price_source"] != "receipt" else ""
        unit = " kg" if sku.get("unit") == "kg" else ""
        promo = f'{l["promo_saving_lkr"]:,}' if l["promo_saving_lkr"] else "-"
        return (f'<tr><td>{_e(l["name"])}{mark}</td><td class="num">{_qty_text(l["qty"])}{unit}</td>'
                f'<td class="num">{sku["prices"][store]["amount_lkr"]:,}</td><td class="num">{l["shelf_lkr"]:,}</td>'
                f'<td class="num">{promo}</td></tr>')

    rows = "".join(row(l) for l in bill["lines"])
    if mixed:
        prices = "Prices from receipts except those marked * (fictional)."
    elif sources == {"receipt"}:
        prices = f"Prices from {STORE_NAMES[store]} receipts."
    else:
        prices = "Fictional demo prices."
    terms = ""
    if bill["card"]:
        card = f'<span class="card-used">{_e(_card_label(bill["card"]))}</span>'
        offer = _offer(bill["card"]["offer_id"])
        if offer.get("source") == "checked":
            terms = (f'<p class="source">Offer you checked: &ldquo;{_e(offer["headline"])}&rdquo;; '
                     "terms as you confirmed them, not confirmed by the bank.</p>")
        elif offer.get("source") == "published":
            terms = (f'<p class="source">Offer: &ldquo;{_e(offer["headline"])}&rdquo; '
                     f'(<a href="{_e(offer["source_url"])}" rel="noopener noreferrer">bank page</a>, captured {_e(offer["captured_on"])}). '
                     f"{_e(TERMS_NOTE)}</p>")
        else:
            terms = '<p class="source">Offer: fictional demo shape.</p>'
    else:
        card = '<span class="source">No card offer applies</span>'
    return (
        f'<article class="bill" data-store="{_e(bill["store_id"])}">'
        f'<header><h3>{_e(STORE_NAMES[bill["store_id"]])}</h3>{card}</header>'
        '<div class="scroll"><table><thead><tr><th>Item</th><th class="num">Qty</th><th class="num">Unit price (LKR)</th>'
        '<th class="num">Shelf (LKR)</th><th class="num">Promotion (LKR)</th></tr></thead>'
        f"<tbody>{rows}</tbody><tfoot>"
        f'<tr><td colspan="4">Card discount</td><td class="num">{_money(bill["card_discount_lkr"])}</td></tr>'
        f'<tr><td colspan="4">Bill total</td><td class="num">{_money(bill["bill_lkr"])}</td></tr>'
        f'</tfoot></table></div><p class="source">{_e(prices)}</p>{terms}</article>'
    )


def _missed_offers(plan: dict[str, Any], banks: list[str]) -> list[tuple[dict[str, Any], dict[str, Any], int]]:
    """(bill, offer, eligible subtotal) for card offers active at a bill's store and day that paid nothing."""
    missed = []
    the_day = _date.fromisoformat(plan["day"]["date"])
    for bill in plan["stores"]:
        for offer in _v2_offers()["card_offers"]:
            if offer["bank"] not in banks or offer["store_id"] != bill["store_id"]:
                continue
            if WEEKDAYS[the_day.weekday()] not in offer["days"] or the_day > _date.fromisoformat(offer["valid_to"]):
                continue
            if bill["card"] and bill["card"]["offer_id"] == offer["id"]:
                continue
            eligible = sum(l["promoted_lkr"] for l in bill["lines"] if _offer_covers(offer, l["category"]))
            if eligible < offer["min_bill_lkr"]:
                missed.append((bill, offer, eligible))
    return missed


def _offer_covers(offer: dict[str, Any], category: str) -> bool:
    include = offer.get("include_categories") or []
    return (not include or category in include) and category not in (offer.get("exclude_categories") or [])


def _offer_bank(offer: dict[str, Any]) -> str:
    return offer["bank"] if offer.get("source") == "published" else f'{offer["bank"]} (fictional demo offer)'


def _near_misses(plan: dict[str, Any], banks: list[str]) -> list[str]:
    """Card offers that were active for a bill but paid nothing, and why (facts only)."""
    return [
        f'{_offer_bank(offer)} at {STORE_NAMES[bill["store_id"]]}: needs {_money(offer["min_bill_lkr"])} of '
        f'{", ".join(offer.get("include_categories") or []) or "eligible"} items; this bill has {_money(eligible)}, so it pays 0.'
        for bill, offer, eligible in _missed_offers(plan, banks)
    ]


def _suggestions(plan: dict[str, Any], state: dict[str, Any], items: list[dict[str, Any]],
                 lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For a missed minimum: the cheapest set of at most three of the shopper's own soon-due items that reaches it.

    An entry with no names means nothing the shopper needs soon would reach that minimum.
    """
    basket = {line["sku_id"] for line in lines}
    horizon = (state["today"] + _timedelta(days=SUGGEST_DAYS)).isoformat()
    candidates = [i for i in items if i["sku_id"] not in basket and i.get("next_due") and i["next_due"] <= horizon and not _is_stale(i)]
    skus = {sku["id"]: sku for sku in _v2_catalog()["skus"]}
    the_day = _date.fromisoformat(plan["day"]["date"])
    found = []
    for bill, offer, eligible in _missed_offers(plan, state["banks"])[:3]:
        store = bill["store_id"]
        pool = []
        for item in candidates:
            sku = skus[item["sku_id"]]
            price = sku["prices"].get(store)
            if price and _offer_covers(offer, sku["category"]):
                qty = float(item["qty"])
                shelf = planner_lkr(price["amount_lkr"] * qty)
                _, saving = best_promotion(_v2_offers().get("store_promotions", []), sku, store, the_day, shelf, price["amount_lkr"], qty)
                pool.append((item, shelf, shelf - saving))
        # The minimum counts promoted prices, exactly as the planner does.
        gap = offer["min_bill_lkr"] - eligible
        ranked = sorted(
            (combo for size in (1, 2, 3) for combo in combinations(pool, size) if sum(p for _, _, p in combo) >= gap),
            key=lambda combo: (sum(s for _, s, _ in combo), [c[0]["sku_id"] for c in combo]),
        )
        entry = {"bank": _offer_bank(offer), "store_id": store, "minimum": offer["min_bill_lkr"], "names": []}
        for combo in ranked[:5]:
            shelf_cost = sum(s for _, s, _ in combo)
            added = [{"sku_id": item["sku_id"], "qty": item["qty"]} for item, _, _ in combo]
            replan = _engine("day", lines + added, state["banks"], plan["max_stores"], plan["trip_cost_lkr"], state["usual_store"],
                             day=plan["day"]["date"], baselines=False)
            fires = any(b["store_id"] == store and b["card"] and b["card"]["offer_id"] == offer["id"] for b in replan["stores"])
            if fires and replan["effective_cost_lkr"] < plan["effective_cost_lkr"] + shelf_cost:
                entry.update({"names": [item["name"] for item, _, _ in combo], "shelf_lkr": shelf_cost,
                              "replanned_lkr": replan["effective_cost_lkr"], "current_lkr": plan["effective_cost_lkr"]})
                break
        found.append(entry)
    return found


def _render_suggestion(s: dict[str, Any]) -> str:
    if not s["names"]:
        return (f'<p class="source">{_e(s["bank"])} at {_e(STORE_NAMES[s["store_id"]])}: none of your eligible items due within '
                f'{SUGGEST_DAYS} days would reach the {_money(s["minimum"])} minimum, so Savvy Cart suggests nothing.</p>')
    extra = s["replanned_lkr"] - s["current_lkr"]
    if extra < 0:
        outcome = f"so you would pay {_money(-extra)} less in total and get those items too."
    else:
        outcome = f'so those items would cost you {_money(extra)} instead of {_money(s["shelf_lkr"])}.'
    return (
        '<div class="suggestion">'
        f'<p><strong>{_e(s["bank"])} at {_e(STORE_NAMES[s["store_id"]])}:</strong> adding {_e(", ".join(s["names"]))} '
        f'({_money(s["shelf_lkr"])} at shelf price) reaches the {_money(s["minimum"])} minimum. '
        f'The engine&#39;s plan with them is {_money(s["replanned_lkr"])}, against {_money(s["current_lkr"])} now, {outcome}</p>'
        "<p>Only if you need these soon. Savvy Cart does not add them.</p></div>"
    )


def _render_plan(plan: dict[str, Any], sweep: dict[str, Any] | None, state: dict[str, Any], title_note: str = "",
                 suggestions: list[dict[str, Any]] | None = None) -> str:
    usual = plan.get("baseline_usual", {})
    single = plan.get("baseline_single", {})
    weekday = plan["day"]["weekday"].title()
    pct = 100 if not usual.get("total_lkr") else max(5, min(100, round(100 * plan["effective_cost_lkr"] / usual["total_lkr"])))
    over = plan["effective_cost_lkr"] - state["budget"]
    budget_note = (f"Within your {_money(state['budget'])} budget." if over <= 0 else f"{_money(over)} over your {_money(state['budget'])} budget.")
    sweep_html = ""
    if sweep:
        days = "".join(
            f'<li class="{"best" if d["date"] == sweep["best"]["date"] else ""}">'
            f'{_e(d["weekday"].title())} {_e(d["date"][5:])}: {_money(d["effective_cost_lkr"])}'
            f'{" (cheapest)" if d["date"] == sweep["best"]["date"] else ""}</li>'
            for d in sweep["days"]
        )
        choices = "".join(
            f'<option value="{_e(d["date"])}"{" selected" if d["date"] == plan["day"]["date"] else ""}>{_e(d["weekday"].title())} {_e(d["date"])}</option>'
            for d in sweep["days"]
        )
        sweep_html = (
            f'<h3>Best day before the estimated next purchase date (by {_e(sweep["window_end"])})</h3><ul class="sweep">{days}</ul>'
            f'<div class="field"><label for="day">Shop on</label><div class="inline"><select id="day" name="day">{choices}</select>'
            '<button type="submit" name="action" value="plan">Update plan</button></div></div>'
        )
    else:
        sweep_html = f'<input type="hidden" name="day" value="{_e(state["day"])}">'
    misses = "".join(f'<p class="notice">{_e(n)}</p>' for n in _near_misses(plan, state["banks"]))
    ideas = "".join(_render_suggestion(s) for s in suggestions or [])
    if ideas:
        ideas = f'<h3>Reach a card minimum with items you need soon?</h3>{ideas}'
    unpriced = f'<p class="notice">Not priced at any store: {_e(", ".join(plan["unpriced"]))}.</p>' if plan["unpriced"] else ""
    extra = f' plus {_money(plan["extra_trip_cost_lkr"])} for extra trips' if plan["extra_trip_cost_lkr"] else ""
    allowed = "" if title_note else f' (you allowed up to {plan["max_stores"]})'
    control = "Control basket, priced with every demo card, one store, and Keells as the usual store: " if title_note else ""
    unproven = ("" if plan["solver_status"] == "OPTIMAL" else
                f'<p class="notice">The optimizer stopped before proving this is the cheapest plan (status {_e(plan["solver_status"])}).</p>')
    return (
        '<section class="step" id="plan" aria-labelledby="plan-h">'
        f'<h2 id="plan-h">3. Plan for {_e(weekday)} {_e(plan["day"]["date"])}{_e(title_note)}</h2>'
        f'<p class="recommendation" id="plan-recommendation">{_e(control)}{_e(_recommendation(plan))}</p>'
        f"{unproven}{'' if title_note else _held_notice(plan)}"
        f'<p class="lead">{len(plan["stores"])} store{"s" if len(plan["stores"]) != 1 else ""}{allowed}. '
        "Store promotions apply first, then at most one card offer per bill.</p>"
        '<div class="summary">'
        f'<div class="metric highlight"><div class="value">{_money(plan["effective_cost_lkr"])}</div><div class="label">Plan total{_e(extra)}</div></div>'
        f'<div class="metric"><div class="value">{_money(plan.get("saving_vs_usual_lkr"))}</div>'
        f'<div class="label">Saved against {_e(STORE_NAMES[usual.get("store_id", "keells")])} at shelf price ({_money(usual.get("total_lkr"))})</div></div>'
        f'<div class="metric"><div class="value">{_money(plan.get("saving_vs_single_lkr"))}</div>'
        f'<div class="label">Saved against the best single store ({_e(STORE_NAMES.get(single.get("store_id") or "", "none"))}, {_money(single.get("total_lkr"))})</div></div>'
        "</div>"
        '<p class="source simulated">Simulated saving on sample data: competitor prices and store promotions are fictional, '
        "and bank minimums and caps are assumptions.</p>"
        f'<div class="bar" role="img" aria-label="Plan total is {pct} percent of the usual-store shelf total"><span style="width:{pct}%"></span></div>'
        f'<p class="bar-label">Plan total as a share of buying everything at your usual store at shelf price. {_e(budget_note)}</p>'
        f'<div class="bills">{"".join(_render_bill(b) for b in plan["stores"])}</div>'
        f"{misses}{ideas}{unpriced}{sweep_html}"
        '<div class="callout"><div><strong>These bank terms are assumptions.</strong> Paste a real offer and check what it pays on this basket.</div>'
        '<button type="submit" name="action" value="offer">Check a card offer</button></div>'
        '<details class="how"><summary>How this was calculated</summary>'
        f'<p class="source">Stores chosen by an exact optimizer (OR-Tools CP-SAT, status {_e(plan["solver_status"])}). '
        "Engine steps: pantry (purchase history), catalog and offers, planner (OR-Tools CP-SAT). "
        f'Trip cost {_money(plan["trip_cost_lkr"])} per extra store.</p></details>'
        f'{_nav("wallet", [("approve", "Approve plan", False), ("why", "Next: explain this plan", True)])}'
        "</section>"
    )


def _fictional(card: dict[str, Any] | None) -> bool:
    return bool(card) and _offer(card["offer_id"]).get("source") not in ("published", "checked")


def _fictional_note() -> str:
    """Shown whether or not the shopper holds the card: the agent's tools can describe any offer."""
    banks = sorted({o["bank"] for o in _v2_offers()["card_offers"] if o.get("source") != "published"})
    if not banks:
        return ""
    return f'<p class="notice">{_e(" and ".join(banks))} card offers in this demo are fictional, not published by the bank.</p>'


def _recommendation(plan: dict[str, Any]) -> str:
    bills = plan["stores"]
    if not bills:
        return "No store can price this basket."
    names = [STORE_NAMES[b["store_id"]] for b in bills]
    where = names[0] if len(names) == 1 else f'{", ".join(names[:-1])} and {names[-1]}'
    cards = [f'{_card_label(b["card"])} at {STORE_NAMES[b["store_id"]]}'
             f'{" (fictional demo offer)" if _fictional(b["card"]) else ""}.'
             for b in bills if b["card"]]
    shop = f'Shop on {plan["day"]["weekday"].title()} {_short_date(plan["day"]["date"])} at {where}.'
    return " ".join([shop] + (cards or ["No card offer applies to this basket."]))


def _engine_summary(plan: dict[str, Any]) -> str:
    parts = []
    for bill in plan["stores"]:
        card = f' with {_card_label(bill["card"])[len("Pay with "):]}' if bill["card"] else ""
        parts.append(f'{STORE_NAMES[bill["store_id"]]}{card} for {len(bill["lines"])} items ({bill["bill_lkr"]} LKR)')
    return (
        f'Shop on {plan["day"]["weekday"].title()} {plan["day"]["date"]}: ' + "; ".join(parts) + ". "
        f'Plan total {plan["effective_cost_lkr"]} LKR, saving {plan.get("saving_vs_usual_lkr", 0)} LKR against your usual store at shelf price.'
    )


def _confirmed(plan: dict[str, Any], state: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    return {"lines": lines, "day": plan["day"]["date"], "banks": _plan_inputs(state["banks"])[1], "max_stores": state["max_stores"],
            "trip_cost_lkr": state["trip_cost"], "usual_store": state["usual_store"]}


def _qty_key(value: Any) -> str:
    try:
        return repr(value) if isinstance(value, bool) else f"{float(value):.3f}"
    except (TypeError, ValueError):
        return repr(value)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _scalar_key(value: Any) -> str:
    """2, 2.0 and "2" are the same request; a day or store name stays text."""
    number = _number(value)
    return f"{number:.3f}" if number is not None else str(value)


def _lines_key(lines: Any) -> list[tuple[str, str]]:
    """Rows for the same item are one line, summed before rounding as the planner merges them."""
    totals: dict[str, float] = {}
    odd = []
    for line in lines if isinstance(lines, list) else [lines]:
        qty = _number(line.get("qty")) if isinstance(line, dict) else None
        if qty is None:
            odd.append(("", repr(line)))
        else:
            sku = str(line.get("sku_id"))
            totals[sku] = totals.get(sku, 0.0) + qty
    return sorted([(sku, f"{qty:.3f}") for sku, qty in totals.items()] + odd)


def _banks_asked(value: Any) -> list[str]:
    return sorted({str(b) for b in (value if isinstance(value, list) else [value]) if b is not None})


def _replan_differences(call_args: dict[str, Any], confirmed: dict[str, Any]) -> list[str]:
    """What a model's plan_day call changed; its arguments are untrusted JSON of any shape."""
    def say(key: str, asked: Any, mine: Any) -> str:
        if key == "max_stores":
            return f"at most {asked} store{'' if _number(asked) == 1 else 's'} instead of {mine}"
        if key == "trip_cost_lkr":
            return f"extra trip cost LKR {asked} instead of LKR {mine}"
        if key == "usual_store":
            return f"usual store {STORE_NAMES.get(str(asked), asked)} instead of {STORE_NAMES.get(str(mine), mine)}"
        return f"{key} {asked} instead of {mine}"

    diffs = []
    for key in ("day", "max_stores", "trip_cost_lkr", "usual_store"):
        if key in call_args and _scalar_key(call_args[key]) != _scalar_key(confirmed[key]):
            diffs.append(say(key, call_args[key], confirmed[key]))
    if "banks" in call_args:
        asked = _banks_asked(call_args["banks"])
        if asked != sorted(confirmed["banks"]):
            diffs.append(f"cards {', '.join(asked) or 'none'} instead of {', '.join(sorted(confirmed['banks'])) or 'none'}")
    if "lines" in call_args and _lines_key(call_args["lines"]) != _lines_key(confirmed["lines"]):
        diffs.append("a different basket")
    return diffs


def _call_key(call_args: dict[str, Any], confirmed: dict[str, Any]) -> str:
    """Identity of a plan_day request, so a retry matches the call it repeats; a missing argument means the shopper's."""
    def get(key: str) -> str:
        return _scalar_key(call_args.get(key, confirmed[key]))
    return json.dumps([get("day"), get("max_stores"), get("trip_cost_lkr"), get("usual_store"),
                       _banks_asked(call_args.get("banks", confirmed["banks"])), _lines_key(call_args.get("lines", confirmed["lines"]))],
                      default=str)


ANSWER_STYLE = "Plain sentences, no Markdown, at most 120 words."
ANSWER_TTL_SECONDS = 15 * 60
ANSWER_CACHE_SIZE = 64
_answers: dict[str, tuple[float, Any, dict[str, Any]]] = {}


def _engine_explanation(plan: dict[str, Any]) -> dict[str, Any]:
    return {"text": _engine_summary(plan), "calls": [], "replans": [], "refused": [],
            "source": "Engine explanation. Ask the agent below for Gemini's view; it can take up to a minute."}


def _answer_key(question: str, context: dict[str, Any], extra: Any) -> str:
    return hashlib.sha256(json.dumps([question, context, extra], sort_keys=True, default=str).encode()).hexdigest()


def _cached_answer(key: str, owner: Any) -> dict[str, Any] | None:
    hit = _answers.get(key)
    if hit and hit[1] is owner and time.time() - hit[0] < ANSWER_TTL_SECONDS:
        return hit[2]
    return None


def _remember_answer(key: str, owner: Any, answer: dict[str, Any]) -> None:
    if key not in _answers and len(_answers) >= ANSWER_CACHE_SIZE:
        _answers.pop(min(_answers, key=lambda k: _answers[k][0]))
    _answers[key] = (time.time(), owner, answer)


def _answer_html(text: str) -> str:
    """The answer, escaped, with the few Markdown marks a model still sends turned into plain emphasis and bullets."""
    html_text = _e(text)
    html_text = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_text)
    html_text = _re.sub(r"`([^`]+)`", r"<code>\1</code>", html_text)
    html_text = _re.sub(r"(^|\s)#{1,6}\s+", r"\1", html_text)
    html_text = _re.sub(r"(^|\s)[*-]\s+(?=\S)", lambda m: "<br>• " if m.start() else "• ", html_text)
    return html_text


async def _explain_v2(request: Request, plan: dict[str, Any], state: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    confirmed = _confirmed(plan, state, lines)
    runner = getattr(request.app.state, "agent_runner", None)
    if runner is None and _model_configured():
        from functools import partial

        from savvycart.agent import ask_agent

        held = _held_offer()
        runner = partial(ask_agent, extra_bills=_added_bills(state["added"]), extra_offers=[held] if held else None)
    fallback = {"text": _engine_summary(plan), "calls": [], "replans": []}
    if runner is None:
        return {**fallback, "source": "Model not configured: engine explanation."}
    window_start = state["today"].isoformat()
    window_end = (state["today"] + _timedelta(days=7)).isoformat()
    context = {"confirmed": confirmed, "engine_plan": plan, "window": {"start": window_start, "end": window_end},
               "answer_style": ANSWER_STYLE}
    question = f"The shopper asks: {state['question']}" if state["question"] else AGENT_QUESTION_V2
    # A scripted runner is its own cache owner, so a different runner never sees another's answer.
    owner = getattr(request.app.state, "agent_runner", None) or "agent"
    key = _answer_key(question, context, _added_bills(state["added"]))
    if not model_rate_limiter(request.app).allow():
        return {**fallback, "source": "Too many explanations this minute. Showing the engine explanation."}
    answer = _cached_answer(key, owner)
    if answer is None:
        try:
            answer = await asyncio.wait_for(runner(question, context), timeout=AGENT_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("agent call failed: %s: %.200s", type(exc).__name__, exc)
            return {**fallback, "source": "The agent call failed. Showing the engine explanation."}
        if isinstance(answer, dict) and answer.get("text"):
            _remember_answer(key, owner, answer)
    calls = [c for c in answer.get("calls", []) if isinstance(c, dict)]
    # The same rules as the agent's own callbacks, applied again on the way to the page.
    guard_state = session_state(context, window_start, window_end, state["question"])
    allowed = numbers_in_plan(context)
    for result in answer.get("results", []):
        if isinstance(result, dict) and result_grounds(result.get("name"), result.get("response"), guard_state):
            allowed |= numbers_in_plan(grounding_view(result["name"], result["response"]))
    text = clean_text(str(answer.get("text", "")), allowed, plan["effective_cost_lkr"], plan.get("saving_vs_usual_lkr", 0))
    saving = str(plan.get("saving_vs_usual_lkr", 0))
    if saving not in text:
        text = f"{text} Engine total {plan['effective_cost_lkr']} LKR, saving {saving} LKR against your usual store.".strip()
    # Calls and responses arrive in event order; a refused or failed plan_day re-planned nothing.
    plan_responses = [r.get("response") for r in answer.get("results", []) if isinstance(r, dict) and r.get("name") == "plan_day"]
    completed, failed = [], []
    for index, call in enumerate(c for c in calls if c.get("name") == "plan_day"):
        response = plan_responses[index] if index < len(plan_responses) else None
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        (failed if isinstance(response, dict) and "error" in response else completed).append(args)
    replans = [diffs for diffs in (_replan_differences(args, confirmed) for args in completed) if diffs]
    done = {_call_key(args, confirmed) for args in completed}
    refused = []
    for args in failed:
        diffs = _replan_differences(args, confirmed)
        # A request a retry completed did re-plan; one sentence per refused change, however often the agent retried it.
        if diffs and _call_key(args, confirmed) not in done and diffs not in refused:
            refused.append(diffs)
    return {"text": text, "calls": calls, "replans": replans, "refused": refused,
            "source": "Answer from the ADK agent (Gemini). Numbers are checked against the engine plan and the agent's own tool results."}


def _call_args(args: Any, limit: int = 2000) -> str:
    text = json.dumps(args or {}, sort_keys=True)
    return text if len(text) <= limit else f"{text[:limit]} … ({len(text) - limit} more characters not shown)"


def _render_ask(question: str) -> str:
    chips = "".join(f'<button type="submit" class="chip" name="question_chip" value="{_e(q)}">{_e(q)}</button>'
                    for q in SAMPLE_QUESTIONS)
    return (
        '<div class="ask"><label for="question">Ask the agent about this plan</label>'
        f'<div class="inline"><input type="text" id="question" name="question" maxlength="{MAX_QUESTION}" value="{_e(question)}" '
        'placeholder="For example: what if I skip the second store?">'
        '<button type="submit" name="action" value="explain" class="primary">Ask</button></div>'
        f'<div class="chips" role="group" aria-label="Sample questions">{chips}</div></div>'
        '<script>document.getElementById("question").addEventListener("keydown",function(e){'
        'if(e.key==="Enter"){e.preventDefault();this.form.querySelector(\'.ask button[value="explain"]\').click();}});</script>'
    )


def _render_why(explanation: dict[str, Any], plan: dict[str, Any], question: str = "") -> str:
    asked = f'<p class="asked">You asked: {_e(question)}</p>' if question else ""
    calls = "".join(
        f'<li><code>{_e(c.get("name"))}({_e(_call_args(c.get("args")))})</code></li>' for c in explanation["calls"][:20]
    ) or "<li>No tool calls.</li>"
    if len(explanation["calls"]) > 20:
        calls += f'<li>{len(explanation["calls"]) - 20} more tool calls not shown.</li>'
    replan = "".join(f'<p class="notice">The agent re-planned with different inputs: {_e("; ".join(d))}. Its comparison is not the plan above.</p>'
                     for d in explanation["replans"])
    replan += "".join(f'<p class="notice">The agent tried to re-plan with different inputs ({_e("; ".join(d))}); '
                      "the call was refused, so nothing was re-planned.</p>" for d in explanation.get("refused", []))
    unchanged = '<p class="ok-note">The agent did not change your inputs.</p>' if explanation["calls"] and not replan else ""
    count = len(explanation["calls"])
    count_text = "no agent tool calls" if not count else "1 agent tool call" if count == 1 else f"{count} agent tool calls"
    return (
        '<section class="step" id="why" aria-labelledby="why-h">'
        '<h2 id="why-h">4. Why this plan</h2>'
        f'<p class="recap"><strong>Engine figures:</strong> {_e(_engine_summary(plan))}</p>{_fictional_note()}{_held_notice(plan)}'
        f"{_render_ask(question)}"
        f"{asked}"
        f'<p class="source" id="explanation-source">{_e(explanation["source"])}</p>'
        f'<p id="explanation-text">{_answer_html(explanation["text"])}</p>'
        f"{replan}"
        f'<details class="how"><summary>How this was calculated: {count_text}</summary>'
        f'{unchanged}<ul class="tools" id="agent-tools">{calls}</ul></details>'
        f'{_nav("plan", [("approve", "Next: approve", True)])}'
        "</section>"
    )


def _card_label(card: dict[str, Any] | None) -> str:
    if not card:
        return "No card offer applies"
    if str(card.get("bank", "")).startswith(CHECKED_PREFIX):
        return f'Pay with {card["product"]} (the offer you checked)'
    return f'Pay with {card["bank"]} {card["product"]}'


def _render_cart(plan: dict[str, Any], state: dict[str, Any]) -> str:
    """One MOCK cart per store bill, and the same list as plain text for Copy and Share."""
    skus = {sku["id"]: sku for sku in _v2_catalog()["skus"]}
    delivery = state["fulfilment"] == "delivery"
    fee = state["delivery_fee"] if delivery else 0
    carts, text = [], [f'Savvy Cart list for {plan["day"]["weekday"].title()} {_short_date(plan["day"]["date"])} (MOCK, no order sent)']
    for bill in plan["stores"]:
        store = STORE_NAMES[bill["store_id"]]
        rows = []
        text.append(f"\n{store}: {_card_label(bill['card'])}")
        for line in bill["lines"]:
            sku = skus[line["sku_id"]]
            qty = f'{_qty_text(line["qty"])}{" kg" if sku.get("unit") == "kg" else ""}'
            unit_price = sku["prices"][bill["store_id"]]["amount_lkr"]
            rows.append(f'<tr><td>{_e(line["name"])}</td><td class="num">{_e(qty)}</td><td class="num">{unit_price:,}</td>'
                        f'<td class="num">{line["promoted_lkr"]:,}</td></tr>')
            text.append(f'- {line["name"]} x {qty}: LKR {line["promoted_lkr"]:,}')
        total = bill["bill_lkr"] + fee
        foot = (f'<tr><td colspan="3">Card discount</td><td class="num">LKR {bill["card_discount_lkr"]:,}</td></tr>'
                f'<tr><td colspan="3">Bill total</td><td class="num">LKR {bill["bill_lkr"]:,}</td></tr>')
        if delivery:
            foot += (f'<tr><td colspan="3">Delivery fee (assumption)</td><td class="num">LKR {fee:,}</td></tr>'
                     f'<tr><td colspan="3">Store total</td><td class="num">LKR {total:,}</td></tr>')
        text.append(f"Card discount LKR {bill['card_discount_lkr']:,}; bill LKR {bill['bill_lkr']:,}"
                    + (f"; delivery LKR {fee:,}; total LKR {total:,}" if delivery else ""))
        carts.append(f'<article class="cart" data-store="{_e(bill["store_id"])}"><header><h3>{_e(store)}</h3>'
                     f'<span class="card-used">{_e(_card_label(bill["card"]))}</span></header>'
                     '<div class="scroll"><table><thead><tr><th>Item</th><th class="num">Qty</th><th class="num">Unit price (LKR)</th>'
                     f'<th class="num">Amount (LKR)</th></tr></thead><tbody>{"".join(rows)}</tbody><tfoot>{foot}</tfoot></table></div></article>')
    grand = sum(b["bill_lkr"] for b in plan["stores"]) + fee * len(plan["stores"])
    trips = "" if delivery or not plan.get("extra_trip_cost_lkr") else (
        f' plus {_money(plan["extra_trip_cost_lkr"])} for the extra trip, your estimate')
    text.append(f"\nTotal LKR {grand:,}{trips}")
    plain = "\n".join(text)
    return (
        f'<h3>Your cart ({"delivery" if delivery else "pickup"}, MOCK)</h3>{"".join(carts)}'
        f'<p class="grand">Total {_money(grand)}{_e(trips)}</p>'
        f'<textarea id="cart-text" class="sr-only" readonly aria-label="Cart as text" tabindex="-1">{_e(plain)}</textarea>'
        '<div class="cart-actions"><button type="button" id="copy-cart">Copy list</button>'
        f'<a href="https://wa.me/?text={_e(quote(plain))}" target="_blank" rel="noopener noreferrer">Share on WhatsApp</a>'
        '<span id="copy-done" class="source" role="status"></span></div>'
    )


def _render_approve(preview: dict[str, Any] | None, plan: dict[str, Any], state: dict[str, Any]) -> str:
    body = (f'<p>Cart reference (<strong>MOCK</strong>): {_e(preview["preview_id"])}.</p>' if preview
            else "<p><strong>MOCK</strong> cart reference unavailable.</p>")
    delivery = state["fulfilment"] == "delivery"
    choice = "".join(
        f'<div class="check"><input type="radio" id="fulfilment_{value}" name="fulfilment" value="{value}"{" checked" if state["fulfilment"] == value else ""}>'
        f'<label for="fulfilment_{value}">{label}</label></div>'
        for value, label in (("pickup", "Pickup: I shop at the stores myself"), ("delivery", "Delivery (MOCK)"))
    )
    fees = ""
    if delivery:
        rows = "".join(
            f'<li>{_e(STORE_NAMES[b["store_id"]])}: bill {_money(b["bill_lkr"])}, delivery {_money(state["delivery_fee"])} (assumption)</li>'
            for b in plan["stores"]
        )
        total = plan["effective_cost_lkr"] + state["delivery_fee"] * len(plan["stores"])
        fees = (f'<ul class="sweep">{rows}</ul><p>Total with delivery: <strong>{_money(total)}</strong>.</p>'
                f"<p>{_e(NO_DELIVERY_INTEGRATION)}</p>")
    return (
        '<section class="step" id="approve" aria-labelledby="approve-h">'
        '<h2 id="approve-h">5. Approve</h2>'
        f'<p class="recap">{_e(_engine_summary(plan))}</p>{_fictional_note()}{_held_notice(plan)}'
        f'<fieldset><legend>How you get the groceries</legend>{choice}'
        '<div class="field"><label for="delivery_fee">Delivery fee per store bill (LKR, an assumption you can change)</label>'
        f'<input type="number" id="delivery_fee" name="delivery_fee" min="0" max="5000" step="10" value="{state["delivery_fee"]}"></div>'
        "</fieldset>"
        f"{fees}"
        f"{_render_cart(plan, state)}"
        f'<div class="mock">{body}<p>No order is sent. Savvy Cart does not contact any store or bank.</p></div>'
        f'{_nav("why", [("approve", "Update my cart", True)])}'
        "</section>"
    )


def _hidden_state(state: dict[str, Any], items: list[dict[str, Any]], step: int) -> str:
    """Every choice made on other steps travels in hidden fields, so Back and Next keep it."""
    fields: list[tuple[str, str]] = [("extra", s) for s in state["extra"]]
    if step != 0:
        fields += [("today", state["today"].isoformat()), ("pantry_set", "1")]
        fields += [("sku", i["sku_id"]) for i in items if i["checked"]]
        fields += [(f"qty_{i['sku_id']}", _qty_text(i["qty"])) for i in items]
    if step != 1:
        fields += [("wallet_set", "1")] + [("bank", b) for b in state["banks"]]
        fields += [("usual_store", state["usual_store"]), ("max_stores", str(state["max_stores"])),
                   ("trip_cost", str(state["trip_cost"])), ("budget", str(state["budget"]))]
    if step != 2 and state["day"]:
        fields.append(("day", state["day"]))
    if step != 4:
        fields += [("fulfilment", state["fulfilment"]), ("delivery_fee", str(state["delivery_fee"]))]
    if _HELD.get() is not None:
        fields.append(("held_offer", json.dumps(_rule_raw(_HELD.get()), sort_keys=True)))
    return "".join(f'<input type="hidden" name="{_e(k)}" value="{_e(v)}">' for k, v in fields)


AVATAR_SVG = (
    '<svg viewBox="0 0 56 56" aria-hidden="true" focusable="false">'
    '<defs><clipPath id="avatar-clip"><circle cx="28" cy="28" r="28"/></clipPath></defs>'
    '<circle cx="28" cy="28" r="28" fill="#e3f1ec"/>'
    '<g clip-path="url(#avatar-clip)">'
    '<path d="M9 58c0-13 8-20 19-20s19 7 19 20z" fill="#0b6e4f"/>'
    '<rect x="24.5" y="31" width="7" height="8" rx="3" fill="#8d5a3b"/>'
    '<circle cx="28" cy="24" r="10" fill="#8d5a3b"/>'
    '<path d="M18 23c0-7 4.5-10.5 10-10.5S38 16 38 23c-2.5-3.5-6-5-10-5s-7.5 1.5-10 5z" fill="#1d1d1b"/>'
    '<circle cx="24.4" cy="25" r="1.2" fill="#1d1d1b"/><circle cx="31.6" cy="25" r="1.2" fill="#1d1d1b"/>'
    '<path d="M24.6 28.6q3.4 2.8 6.8 0" fill="none" stroke="#1d1d1b" stroke-width="1.3" stroke-linecap="round"/>'
    "</g>"
    '<path d="M39.5 38.5v-2a3 3 0 0 1 6 0v2" fill="none" stroke="#0b6e4f" stroke-width="1.6"/>'
    '<rect x="36.5" y="38.5" width="12" height="11" rx="2" fill="#9fd3bf" stroke="#0b6e4f" stroke-width="1.4"/>'
    "</svg>"
)


def _card_count(banks: list[str]) -> str:
    return "no cards" if not banks else "1 card" if len(banks) == 1 else f"{len(banks)} cards"


def _render_profile(state: dict[str, Any], compact: bool) -> str:
    facts = (f'{_money(state["budget"])} budget · {_card_count(state["banks"])} · '
             f'Usually shops at {_e(STORE_NAMES[state["usual_store"]])}')
    return (
        f'<aside class="profile{" compact" if compact else ""}" aria-label="Demo household">{AVATAR_SVG}'
        "<div><p class=\"who\"><strong>Karuppan's household · Colombo</strong> <span class=\"tag\">Fictional demo profile</span></p>"
        f'<p class="profile-facts">{facts}</p></div></aside>'
    )


def _layout(current: int, inner: str, state: dict[str, Any], items: list[dict[str, Any]], message: str | None,
            hidden_step: int | None = None) -> str:
    alert = f'<p class="notice" role="status">{_e(message)}</p>' if message else ""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Savvy Cart AI</title>"
        f'<link rel="stylesheet" href="/static/app.css?v={CSS_VERSION}"></head><body>'
        '<a class="skip-link" href="#main">Skip to the current step</a>'
        '<div class="banner" id="banner"><div class="wrap"><strong>Sample data, not live; savings are simulated.</strong>'
        f'<details><summary>What is real in this demo?</summary><p>{_e(V2_BANNER)}</p>'
        "<p>The planning date runs from 17 to 31 Oct 2026 because the sample purchase history ends on 17 Oct 2026.</p></details></div></div>"
        '<header class="site"><div class="wrap"><h1>Savvy Cart AI</h1>'
        "<p class=\"tagline\">Karuppan's next shop: when to buy, where, and with which card.</p></div></header>"
        '<main id="main"><div class="wrap">'
        '<form method="post" action="/ui" enctype="multipart/form-data">'
        f"{_render_profile(state, compact=current != 0 or hidden_step == OFFER_STEP)}"
        f"{_step_nav(current)}{alert}"
        f'<input type="hidden" name="receipt_json" value="{_e(json.dumps(state["added"]))}">'
        f"{_hidden_state(state, items, current if hidden_step is None else hidden_step)}"
        f"{inner}</form></div></main>"
        '<div id="busy" class="busy" role="status" aria-live="polite" hidden><span class="spinner" aria-hidden="true"></span>'
        '<span id="busy-text"></span></div>'
        '<footer class="site"><div class="wrap">Prototype for the Google Cloud AI Builder Cup. Pricing runs in code; Gemini explains it. '
        f'No login, no card numbers, no real orders.</div></footer><script src="/static/app.js?v={JS_VERSION}" defer></script></body></html>'
    )


CSS_VERSION = hashlib.sha256((STATIC_DIR / "app.css").read_bytes()).hexdigest()[:10]
JS_VERSION = hashlib.sha256((STATIC_DIR / "app.js").read_bytes()).hexdigest()[:10]


def _mask_digits(text: str) -> str:
    return _re.sub(r"\d{4,}", "####", text)[:40]


def _receipt_note(rows: list[dict[str, Any]], left_out: list[str], label: str, today: str) -> str:
    names = {sku["id"]: sku["name"] for sku in _v2_catalog()["skus"]}
    added = "".join(f"<li>{_e(names.get(_v2_history_map().get(r['raw'], ''), r['raw']))} x {_qty_text(r['qty'])}</li>" for r in rows)
    left = "".join(f"<li>{_e(_mask_digits(raw))}</li>" for raw in left_out[:20])
    return (
        '<div class="ok-note" role="status">'
        f"<p>Added {len(rows)} lines from {_e(label)} as purchases on {_e(today)}.</p>"
        f'{f"<ul>{added}</ul>" if added else ""}'
        f'{f"<p>Left out ({len(left_out)}, not regular items):</p><ul>{left}</ul>" if left_out else ""}'
        "</div>"
    )


async def _read_form(request: Request) -> tuple[dict[str, list[str]], dict[str, Any]]:
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        data = await request.form()
        form: dict[str, list[str]] = {}
        uploads: dict[str, Any] = {}
        for key, value in data.multi_items():
            if isinstance(value, str):
                form.setdefault(key, []).append(value)
            elif key in ("receipt_photo", "offer_photo"):
                uploads[key] = value
        return form, uploads
    return parse_qs((await request.body()).decode("utf-8", errors="replace"), keep_blank_values=True), {}


async def _extract_upload(request: Request, upload: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Forward an uploaded photo to /v1/receipts; the bytes are never written anywhere."""
    if upload is None or not getattr(upload, "filename", ""):
        return None, "Choose a receipt photo first, or use the sample receipt."
    if upload.content_type not in RECEIPT_TYPES:
        return None, "Upload a JPEG or PNG photo."
    data = await upload.read(MAX_RECEIPT_BYTES + 1)
    if len(data) > MAX_RECEIPT_BYTES:
        return None, "That photo is larger than 4 MB. Nothing was added."
    response = await _internal_post(request, "/v1/receipts?catalog=v2", content=data, headers={"content-type": upload.content_type})
    if response.status_code == 200:
        return response.json().get("lines", []), None
    if response.status_code == 503:
        return None, "The live extract is unavailable here (no model is configured). Nothing was added; use the sample receipt instead."
    if response.status_code == 429:
        return None, "Too many receipt extracts this minute. Nothing was added; try again shortly."
    return None, "The live extract failed. Nothing was added; use the sample receipt instead."


# --- Offer Reality Check: Gemini reads the offer, the shopper confirms it, the engine prices it ---

OFFER_ACTIONS = {"offer", "offer_sample", "offer_read", "offer_check"}
CHECKED_OFFER_KEY = "__checked_offer__"
OFFER_STEP = 5  # not a wizard step: every wizard choice travels in hidden fields
SAMPLE_OFFER = V2 / "offer-sample-seylan.json"


@lru_cache(maxsize=1)
def _sample_offer() -> dict[str, Any]:
    return json.loads(SAMPLE_OFFER.read_text(encoding="utf-8"))


def _form_rule(form: dict[str, list[str]], today: _date | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    """The confirm form, as the shopper left it, validated exactly like model output."""
    def get(key: str) -> str:
        return form.get(key, [""])[0].strip()

    try:
        terms = [str(t) for t in json.loads(get("o_terms") or "[]") if isinstance(t, str)][:30]
    except (json.JSONDecodeError, TypeError):
        terms = []
    units = get("o_units")
    raw = {
        "bank": get("o_bank"), "card_products": get("o_products"), "headline": get("o_headline"), "store_id": get("o_store"),
        "percent_off": get("o_rate") or None, "days": form.get("o_days", []), "minimum_bill_lkr": get("o_min") or None,
        "minimum_applies_to": "eligible_items" if get("o_basis") == "eligible" else "whole_bill",
        "max_discount_lkr": get("o_cap") or None, "excluded_items": terms,
        "applies_only_to": [c for c in form.get("o_incl", []) if c in offercheck.CATEGORY_WORDS],
        "max_units_per_item": int(units) if units.isdigit() else None,
        # Still unstated while the shopper leaves the box as read; unticking it is their statement.
        "combines_with_store_offers": None if "o_stack_unstated" in form and "o_stack" in form else "o_stack" in form,
        "valid_until": get("o_valid_to") or None,
        "is_up_to": "o_upto" in form,
    }
    rule, notes = offercheck.validate_rule(raw, _v2_catalog(), get("o_source") or "edited", today)
    if rule is not None and "o_marked" in form:
        sku_ids = {s["id"] for s in _v2_catalog()["skus"]}
        rule["exclude_sku_ids"] = sorted(set(form.get("o_excl", [])) & sku_ids)
    return rule, notes


async def _read_offer(request: Request, text: str, photo: Any, today: _date) -> tuple[dict[str, Any] | None, list[str], str | None]:
    client = get_model_client(request)
    extract = getattr(client, "extract_offer", None)
    if extract is None:
        return None, [], ("Reading an offer needs Gemini, which is not configured here. "
                          "Use the sample offer, or type the terms in the form below.")
    image = None
    if photo is not None and getattr(photo, "filename", ""):
        if photo.content_type not in RECEIPT_TYPES:
            return None, [], "Upload the offer screenshot as a JPEG or PNG."
        image = await photo.read(MAX_RECEIPT_BYTES + 1)
        if len(image) > MAX_RECEIPT_BYTES:
            return None, [], "That screenshot is larger than 4 MB."
    if not text and not image:
        return None, [], "Paste the offer text or choose a screenshot first."
    if not get_rate_limiter(request).allow():
        return None, [], "Too many reads this minute; try again shortly."
    try:
        raw = await asyncio.wait_for(asyncio.to_thread(extract, text, image, offercheck.OFFER_SCHEMA, offercheck.OFFER_PROMPT),
                                     timeout=AGENT_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning("offer read failed: %s", type(exc).__name__)
        return None, [], "Gemini could not read that offer. Try the text instead of a photo, or type the terms below."
    rule, notes = offercheck.validate_rule(raw, _v2_catalog(), "gemini", today)
    return rule, notes, None


def _held_plan(rule: dict[str, Any], state: dict[str, Any], lines: list[dict[str, Any]], day: str) -> tuple[int, int]:
    """Engine best plan on the offer's day with the shopper's cards, then also holding this card."""
    args = (_v2_catalog(), _v2_offers(), lines, day)
    now = engine_plan_day(*args, state["banks"], state["max_stores"], state["trip_cost"], state["usual_store"], _with_baselines=False)
    # Hold only this offer: keying it on its bank name would also unlock that bank's other offers the shopper did not pick.
    checked = {**offercheck.planner_offer(rule), "bank": CHECKED_OFFER_KEY}
    offers = {**_v2_offers(), "card_offers": _v2_offers()["card_offers"] + [checked]}
    held = engine_plan_day(_v2_catalog(), offers, lines, day, state["banks"] + [CHECKED_OFFER_KEY], state["max_stores"],
                           state["trip_cost"], state["usual_store"], _with_baselines=False)
    return now["effective_cost_lkr"], held["effective_cost_lkr"]


def _verdict(rule: dict[str, Any], check: dict[str, Any]) -> str:
    store = STORE_NAMES[check["store_id"]]
    if not check["min_met"]:
        basis = "bill" if rule["minimum_basis"] == "bill" else "eligible part of your bill"
        return (f"This offer pays nothing on your basket. Your {basis} at {store} is {_money(check['minimum_base_lkr'])}, "
                f"{_money(check['gap_lkr'])} short of the {_money(rule['min_bill_lkr'])} minimum.")
    excluded = sum(1 for line in check["lines"] if not line["counts"])
    parts = []
    if excluded:
        parts.append(f"{excluded} of your {len(check['lines'])} items do not count")
    if check["capped"]:
        parts.append(f"the discount stops at {_money(rule['cap_lkr'])}")
    reason = " and ".join(parts) if parts else "every item counts"
    return f"This offer pays {_money(check['paid_lkr'])}, not {_money(check['headline_lkr'])}: {reason}."


def _also_excluded(rule: dict[str, Any], check: dict[str, Any]) -> str:
    in_basket = {line["sku_id"] for line in check["lines"]}
    names = {s["id"]: s["name"] for s in _v2_catalog()["skus"]}
    others = [names[s] for s in rule["exclude_sku_ids"] if s not in in_basket and s in names]
    if not others:
        return ""
    return (f'<p class="notice">These terms also exclude {_e(", ".join(others))}, which this household buys. '
            f"Add {'it' if len(others) == 1 else 'them'} to the basket and {'it' if len(others) == 1 else 'they'} would not count either.</p>")


def _render_offer_result(rule: dict[str, Any], check: dict[str, Any], held: tuple[int, int]) -> str:
    rows = "".join(
        f'<tr class="{"counts" if l["counts"] else "refused"}"><td>{_e(l["name"])}</td><td class="num">{_money(l["promoted_lkr"])}</td>'
        f'<td class="num">{_money(l["eligible_lkr"]) if l["counts"] else "-"}</td>'
        f'<td><span class="mark" aria-hidden="true">{"&#10003;" if l["counts"] else "&#10007;"}</span> {_e(l["why"])}</td></tr>'
        for l in check["lines"]
    )
    cap = _money(rule["cap_lkr"]) if rule["cap_lkr"] is not None else "none stated"
    basis = "whole bill" if rule["minimum_basis"] == "bill" else "eligible items"
    now, with_card = held
    if with_card < now:
        held_text = (f"Holding this card, the engine's best plan for {_e(check['weekday'].title())} {_e(check['day'])} is "
                     f"<strong>{_money(with_card)}</strong>, {_money(now - with_card)} less than {_money(now)} with your cards.")
    else:
        held_text = (f"Holding this card would not lower your plan for {_e(check['weekday'].title())} {_e(check['day'])}: "
                     f"the engine's best stays <strong>{_money(now)}</strong> with the cards you already hold.")
    headline = rule["headline"] or f"{rule['rate_bps'] / 100:g}% off"
    return (
        '<div class="reality" id="reality">'
        '<div class="versus">'
        f'<div class="claim"><div class="label">The headline says</div><div class="quote">&ldquo;{_e(headline)}&rdquo;</div>'
        f'<div class="value struck">{_money(check["headline_lkr"])}</div>'
        f'<div class="label">{rule["rate_bps"] / 100:g}% of your {_money(check["shelf_total_lkr"])} basket at {_e(STORE_NAMES[check["store_id"]])}</div></div>'
        f'<div class="truth{" zero" if check["paid_lkr"] == 0 else ""}"><div class="label">The terms pay you</div><div class="value">{_money(check["paid_lkr"])}</div>'
        f'<div class="label">on {_e(check["weekday"].title())} {_e(check["day"])}, computed by the engine</div></div>'
        "</div>"
        f'<p class="verdict">{_e(_verdict(rule, check))}</p>'
        '<ul class="facts">'
        f'<li><span>Counts toward the discount</span><strong>{_money(check["eligible_lkr"])} of {_money(check["bill_lkr"])}</strong></li>'
        f'<li><span>Minimum ({_e(basis)})</span><strong>{_money(rule["min_bill_lkr"])} {"met" if check["min_met"] else "not met"}</strong></li>'
        f'<li><span>Maximum discount</span><strong>{_e(cap)}</strong></li>'
        f'<li><span>Combines with store promotions</span><strong>{"yes" if rule["stacks_with_promotions"] else "no"}'
        f'{"" if rule.get("stacks_stated", True) else " (not stated in the offer)"}</strong></li>'
        + (f'<li><span>Applies only to</span><strong>{_e(", ".join(rule["applies_only_to"]))}</strong></li>' if rule.get("applies_only_to") else "")
        + ""
        "</ul>"
        '<div class="scroll"><table class="lines"><thead><tr><th>Item</th><th class="num">Price</th><th class="num">Counts</th><th>Why</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
        f"{_also_excluded(rule, check)}"
        '<p class="source">Store promotions in this demo are fictional shapes; the offer terms are as read and confirmed above.</p>'
        f'<p class="ok-note">{held_text}</p>'
        '<div class="actions"><button type="submit" name="action" value="plan" class="primary">Go to my shopping plan</button></div>'
        f'<div class="actions"><button type="submit" name="action" value="offer_plan">Plan with this card on '
        f'{_e(check["weekday"].title())} {_e(_short_date(check["day"]))}</button></div>'
        "</div>"
    )


def _render_rule_form(rule: dict[str, Any] | None) -> str:
    r = rule or {"bank": "", "card_products": "", "headline": "", "store_id": "keells", "rate_bps": 0, "days": [], "min_bill_lkr": 0,
                 "minimum_basis": "bill", "cap_lkr": None, "excluded_items": [], "exclude_sku_ids": [], "max_units_per_item": None,
                 "stacks_with_promotions": True, "valid_to": None, "source": "edited", "is_up_to": False}
    stores = "".join(f'<option value="{s}"{" selected" if s == r["store_id"] else ""}>{_e(n)}</option>' for s, n in STORE_NAMES.items())
    days = "".join(
        f'<label class="day"><input type="checkbox" name="o_days" value="{d}"{" checked" if d in r["days"] else ""}> {d[:3].title()}</label>'
        for d in WEEKDAYS
    )
    excl = "".join(
        f'<label class="day"><input type="checkbox" name="o_excl" value="{_e(s["id"])}"{" checked" if s["id"] in r["exclude_sku_ids"] else ""}> '
        f"{_e(s['name'])}</label>"
        for s in _v2_catalog()["skus"]
    )
    incl = "".join(
        f'<label class="day"><input type="checkbox" name="o_incl" value="{c}"{" checked" if c in r.get("include_categories", []) else ""}> '
        f"{c.title()} items</label>"
        for c in offercheck.CATEGORY_WORDS
    )
    rate = f"{r['rate_bps'] / 100:g}" if r["rate_bps"] else ""
    terms = ", ".join(r["excluded_items"]) or "none read"
    return (
        '<details class="rule-form"' + (" open" if rule is None else "") + '><summary>Check or correct the terms</summary>'
        '<div class="grid two">'
        f'<div class="field"><label for="o_bank">Bank</label><input type="text" id="o_bank" name="o_bank" maxlength="60" value="{_e(r["bank"])}"></div>'
        f'<div class="field"><label for="o_store">Store</label><select id="o_store" name="o_store">{stores}</select></div>'
        f'<div class="field"><label for="o_rate">Percent off</label><input type="number" id="o_rate" name="o_rate" min="0" max="90" step="0.5" value="{rate}"></div>'
        f'<div class="field"><label for="o_min">Minimum bill (LKR)</label><input type="number" id="o_min" name="o_min" min="0" step="100" value="{r["min_bill_lkr"]}"></div>'
        f'<div class="field"><label for="o_cap">Maximum discount (LKR, blank if none)</label>'
        f'<input type="number" id="o_cap" name="o_cap" min="0" step="50" value="{r["cap_lkr"] if r["cap_lkr"] is not None else ""}"></div>'
        f'<div class="field"><label for="o_units">Units of the same item that count (blank if no limit)</label>'
        f'<input type="number" id="o_units" name="o_units" min="1" max="50" value="{r["max_units_per_item"] or ""}"></div>'
        f'<div class="field"><label for="o_basis">The minimum counts</label><select id="o_basis" name="o_basis">'
        f'<option value="bill"{" selected" if r["minimum_basis"] == "bill" else ""}>the whole bill</option>'
        f'<option value="eligible"{" selected" if r["minimum_basis"] == "eligible" else ""}>only items that count</option></select></div>'
        f'<div class="field"><label for="o_valid_to">Valid until</label><input type="date" id="o_valid_to" name="o_valid_to" value="{_e(r["valid_to"] or "")}"></div>'
        "</div>"
        f'<fieldset><legend>Valid on</legend><div class="days">{days}</div></fieldset>'
        f'<fieldset><legend>Only these count (leave all unticked for the whole bill)</legend><div class="days">{incl}</div></fieldset>'
        f'<fieldset><legend>Excluded items in this catalog</legend><p class="source">The terms list: {_e(terms)}.</p><div class="days">{excl}</div></fieldset>'
        f'<div class="check"><input type="checkbox" id="o_stack" name="o_stack"{" checked" if r["stacks_with_promotions"] else ""}>'
        '<label for="o_stack">Can be combined with store promotions</label></div>'
        + ('<input type="hidden" name="o_stack_unstated" value="1">' if not r.get("stacks_stated", True) else "")
        + ""
        f'<input type="hidden" name="o_terms" value="{_e(json.dumps(r["excluded_items"]))}">'
        f'<input type="hidden" name="o_headline" value="{_e(r["headline"])}"><input type="hidden" name="o_products" value="{_e(r["card_products"])}">'
        f'<input type="hidden" name="o_source" value="{_e(r["source"])}"><input type="hidden" name="o_marked" value="1">'
        + ('<input type="hidden" name="o_upto" value="1">' if r.get("is_up_to") else "")
        + '<div class="actions"><button type="submit" name="action" value="offer_check">Recheck with these terms</button></div></details>'
    )


async def _offer_view(request: Request, action: str, form: dict[str, list[str]], photo: Any,
                      state: dict[str, Any], items: list[dict[str, Any]]) -> str:
    text = " ".join(form.get("o_text", [""])[0].split())[: offercheck.MAX_OFFER_TEXT]
    rule, notes, problem, source_note = None, [], None, ""
    if action == "offer_sample":
        sample = _sample_offer()
        text = sample["text"]
        rule, notes = offercheck.validate_rule(sample["extracted"], _v2_catalog(), "sample", state["today"])
        source_note = (f'Sample: published terms from <a href="{_e(sample["source_url"])}" rel="noopener noreferrer">the bank&#39;s page</a>, '
                       f'captured {_e(sample["captured_on"])}; the reading is checked in so it works without a model. '
                       "Press <strong>Read it with Gemini</strong> to read the same text live.")
    elif action == "offer_read":
        rule, notes, problem = await _read_offer(request, text, photo, state["today"])
        if rule:
            source_note = "Read by Gemini into a fixed schema, then checked by code. Confirm the terms below."
    elif action == "offer_check":
        rule, notes = _form_rule(form, state["today"])
        source_note = "Checked with the terms in the form."
    lines = _lines(items)
    result = ""
    if rule is not None and lines:
        day = offercheck.next_offer_day(rule, state["today"])
        if day is None:
            ended = rule["valid_to"] and rule["valid_to"] < state["today"].isoformat()
            result = (f'<p class="notice">This offer {"ended on " + _e(rule["valid_to"]) if ended else "has no valid day in the next 7 days"}, '
                      "so it pays nothing for this shop.</p>")
        else:
            check = offercheck.reality_check(rule, _v2_catalog(), _v2_offers()["store_promotions"], lines, day)
            result = _render_offer_result(rule, check, _held_plan(rule, state, lines, day.isoformat()))
    elif rule is None and notes and action != "offer":
        problem = problem or " ".join(notes)
        notes = []
    note_html = "".join(f"<li>{_e(n)}</li>" for n in notes)
    return (
        '<section class="step" id="offer" aria-labelledby="offer-h">'
        '<h2 id="offer-h">Offer Reality Check</h2>'
        '<p class="lead">Got a card offer by SMS or on a bank page? Paste it. Gemini reads the terms, you confirm them, '
        "and the engine shows what the headline promises against what the terms pay on <em>your</em> basket.</p>"
        + (f'<p class="notice" role="status">{_e(problem)}</p>' if problem else "")
        + '<div class="grid two">'
        f'<div class="field"><label for="o_text">Offer text</label><textarea id="o_text" name="o_text" rows="5" maxlength="{offercheck.MAX_OFFER_TEXT}" '
        f'placeholder="For example: 10% off your total bill every Saturday with your card. Minimum bill Rs. 8,000...">{_e(text)}</textarea></div>'
        '<div class="field"><label for="offer_photo">Or a screenshot (JPEG or PNG)</label>'
        '<input type="file" id="offer_photo" name="offer_photo" accept="image/jpeg,image/png">'
        '<p class="source">Screenshots go to Gemini to read the terms and are never stored.</p>'
        '<div class="actions tight"><button type="submit" name="action" value="offer_read" class="primary">Read it with Gemini</button>'
        '<button type="submit" name="action" value="offer_sample">Use the sample offer</button></div></div>'
        "</div>"
        + (f'<p class="source">{source_note}</p>' if source_note else "")
        + (f'<ul class="notes">{note_html}</ul>' if note_html else "")
        + result
        + _render_rule_form(rule)
        + _nav("wallet", [("plan", "Next: plan my shopping", True)])
        + "</section>"
    )


@app.get("/", response_class=HTMLResponse)
def guest_page() -> str:
    state = _parse_state({})
    items = _pantry_view(state)
    return _layout(0, _render_pantry(items, state, None), state, items, None)


STEP_OF = {"pantry": 0, "sample": 0, "upload": 0, "add": 0, "wallet": 1, "plan": 2, "refused": 2, "offer_plan": 2, "drop_offer": 2,
           "why": 3, "explain": 3, "approve": 4}


@app.post("/ui", response_class=HTMLResponse)
async def guest_action(request: Request) -> str:
    form, uploads = await _read_form(request)
    upload = uploads.get("receipt_photo")
    state = _parse_state(form)
    action = form.get("action", ["explain" if "question_chip" in form else "pantry"])[0]
    step = STEP_OF.get(action, 0)
    message: str | None = None
    note: str | None = None
    held = None if action == "drop_offer" else _held_from(state["held_raw"], state["today"])
    if action == "offer_plan":
        rule, _ = _form_rule(form, state["today"])
        offer_day = offercheck.next_offer_day(rule, state["today"]) if rule else None
        if rule and offer_day:
            held, state["day"] = rule, offer_day.isoformat()
        else:
            message = "That offer has no valid day in the next 7 days, so there is nothing to plan with it."
    _HELD.set(held)

    if action in ("sample", "upload"):
        if action == "sample":
            lines, problem, label = json.loads(SAMPLE_RECEIPT_V2.read_text(encoding="utf-8"))["lines"], None, "the sample receipt"
        else:
            (lines, problem), label = await _extract_upload(request, upload), "your receipt photo"
        if problem:
            message = problem
        else:
            rows, left_out = _receipt_rows(lines or [], state["today"].isoformat())
            state["added"] = state["added"] + rows
            state["pantry_set"] = False
            note = _receipt_note(rows, left_out, label, state["today"].isoformat())
    if action == "add":
        sku = form.get("add_sku", [""])[0]
        if sku in {s["id"] for s in _v2_catalog()["skus"]}:
            state["extra"] = list(dict.fromkeys(state["extra"] + [sku]))
            state["checked"].add(sku)
            state["qty"][sku] = form.get("add_qty", ["1"])[0]
        else:
            message = "Only items in the catalog can be added."

    items = _pantry_view(state)
    plan = None
    if step >= 2 and action != "refused":
        if not _lines(items):
            message, step = "Pick at least one item in the pantry to plan a shop.", 0
        else:
            plan, sweep = _engine_plan(state, items)

    if action in OFFER_ACTIONS:
        if not _lines(items):
            message = "Pick at least one item in the pantry first; the offer is checked on your basket."
        inner = await _offer_view(request, action, form, uploads.get("offer_photo"), state, items)
        return _layout(1, inner, state, items, message, hidden_step=OFFER_STEP)
    if step == 0:
        inner = _render_pantry(items, state, note)
    elif step == 1:
        inner = _render_wallet(state)
    elif action == "refused":
        today = state["today"]
        saturday = today + _timedelta(days=(5 - today.weekday()) % 7)
        control_lines = [{"sku_id": "banana_ambul", "qty": 1}, {"sku_id": "tomatoes", "qty": 0.5}]
        control = engine_plan_day(_v2_catalog(), _v2_offers(), control_lines, saturday.isoformat(), [b for b, _ in WALLET_CARDS], 1,
                                  state["trip_cost"], "keells")
        inner = _render_plan(control, None, state, " (control basket)", _suggestions(control, state, items, control_lines))
        message = "Control basket: two fresh items at Keells. The card offers have minimum bills, so this basket earns no card discount."
    elif step == 2:
        inner = _render_plan(plan, sweep, state, suggestions=_suggestions(plan, state, items, _lines(items)))
    elif step == 3:
        explanation = (_engine_explanation(plan) if action == "why"
                       else await _explain_v2(request, plan, state, _lines(items)))
        inner = _render_why(explanation, plan, state["question"] if action == "explain" else "")
    else:
        lines = [{"sku_id": l["sku_id"], "qty": max(1, round(l["qty"]))} for l in _lines(items)]
        try:
            preview = approve_plan(ApproveRequest(
                line_ids=lines, day={"weekday": plan["day"]["weekday"], "date": plan["day"]["date"]},
                card_product_id=",".join(state["banks"]) or "none", usual_store=state["usual_store"],
                store_id=plan["stores"][0]["store_id"] if plan["stores"] else None))
        except (HTTPException, ValueError) as exc:
            logger.warning("approve preview failed: %s", type(exc).__name__)
            preview = None
        inner = _render_approve(preview, plan, state)
    return _layout(step, inner, state, items, message)
