"""FastAPI app: v2 guided guest flow, plus the v1 plans, approve, receipt, and explain API."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from savvycart.explain import drop_unallowed_number_tokens, ensure_discount_sentence, explain_plan, numbers_in_plan
from savvycart.gemini import ModelResponseError, UnsupportedImage
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
    except UnsupportedImage:
        raise HTTPException(status_code=415, detail="send a PNG or JPEG receipt image") from None
    except ModelNotConfigured:
        raise HTTPException(status_code=503, detail="receipt model not configured") from None
    except ModelResponseError:
        raise HTTPException(status_code=502, detail="the receipt model did not return usable lines") from None


@app.post("/v1/explain")
def explain(
    body: ExplainRequest,
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

from fastapi.staticfiles import StaticFiles

from savvycart.pantry import pantry as compute_pantry
from savvycart.planner import MAX_QTY, WEEKDAYS, day_sweep
from savvycart.planner import plan_day as engine_plan_day

V2 = FIXTURES / "v2"
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

V2_BANNER = (
    "Sample data, not live. Keells prices come from one shopper's real receipts; "
    "Cargills, SPAR and Glomark prices and every card offer are fictional demo shapes."
)
STEPS = ["Pantry", "Wallet", "Plan", "Why", "Approve"]
STORE_NAMES = {"keells": "Keells", "cargills": "Cargills", "spar": "SPAR", "glomark": "Glomark"}
WALLET_CARDS = [("Commercial Bank", "credit"), ("Nations Trust Bank", "credit"), ("HNB", "credit")]
V2_DEFAULTS = {"today": "2026-10-22", "usual_store": "keells", "max_stores": "2", "trip_cost": "250", "budget": "12000"}
SAMPLE_RECEIPT_V2 = ROOT / "samples" / "receipts" / "keells-2026-10-17.expected.json"
SAMPLE_PHOTO_V2 = ROOT / "samples" / "receipts" / "keells-2026-10-17-redacted.jpg"
STATUS_TEXT = {"due": "Due", "soon": "Soon", "ok": "OK", "unknown": "Not enough history", "stale": "Not bought for a while"}
AGENT_TIMEOUT_SECONDS = 60
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


def _clean_added(value: Any) -> list[dict[str, Any]]:
    """Purchases added this session from receipts; the hidden field is untrusted."""
    if not isinstance(value, list):
        return []
    cleaned = []
    for row in value[:60]:
        if not isinstance(row, dict):
            continue
        raw = _canonical_raw(row.get("raw", ""))
        try:
            qty = float(row.get("qty", 1))
            day = _date.fromisoformat(str(row.get("date", "")))
        except (TypeError, ValueError):
            continue
        if raw and 0 < qty <= MAX_QTY:
            cleaned.append({"raw": raw, "qty": qty, "date": day.isoformat()})
    return cleaned


def _added_bills(added: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bills: dict[str, dict[str, Any]] = {}
    for row in added:
        bill = bills.setdefault(row["date"], {"date": row["date"], "chain": "keells", "source": "receipt", "lines": [],
                                              "promotions": [], "card_offers": [], "gross_lkr": 0, "net_lkr": 0})
        bill["lines"].append({"line": len(bill["lines"]) + 1, "raw": row["raw"], "qty": row["qty"], "unit_lkr": 0, "amount_lkr": 0})
    return list(bills.values())


def _receipt_rows(lines: list[dict[str, Any]], today: str) -> tuple[list[dict[str, Any]], int]:
    rows, skipped = [], 0
    for line in lines:
        raw = _canonical_raw(line.get("raw", ""))
        try:
            qty = float(line.get("qty", 1))
        except (TypeError, ValueError):
            qty = 0
        if raw and 0 < qty <= MAX_QTY:
            rows.append({"raw": raw, "qty": qty, "date": today})
        else:
            skipped += 1
    return rows, skipped


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
        except ValueError:
            value = int(default)
        return min(max(value, low), high)

    try:
        today = _date.fromisoformat(get("today", V2_DEFAULTS["today"]))
    except ValueError:
        today = _date.fromisoformat(V2_DEFAULTS["today"])
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
        "max_stores": 2 if get("max_stores", V2_DEFAULTS["max_stores"]) == "2" else 1,
        "trip_cost": bounded_int("trip_cost", V2_DEFAULTS["trip_cost"], 0, 5000),
        "budget": bounded_int("budget", V2_DEFAULTS["budget"], 0, 1_000_000),
        "banks": banks,
        "day": get("day", ""),
        "added": added,
        "pantry_set": "pantry_set" in form,
        "checked": set(form.get("sku", [])),
        "qty": {key[4:]: get(key, "") for key in form if key.startswith("qty_")},
    }


def _pantry_view(state: dict[str, Any]) -> list[dict[str, Any]]:
    bills = list(_v2_history()) + _added_bills(state["added"])
    items = compute_pantry(bills, _v2_catalog(), _v2_history_map(), state["today"])
    for item in items:
        item["display_status"] = "stale" if _is_stale(item) else item["status"]
        default_on = item["status"] in ("due", "soon") and not _is_stale(item)
        item["checked"] = (item["sku_id"] in state["checked"]) if state["pantry_set"] else default_on
        try:
            qty = float(state["qty"].get(item["sku_id"], ""))
        except ValueError:
            qty = 0
        usual = item.get("usual_qty") or 1
        item["qty"] = qty if 0 < qty <= MAX_QTY else usual
    return items


def _lines(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"sku_id": i["sku_id"], "qty": i["qty"]} for i in items if i["checked"]]


def _deadline(items: list[dict[str, Any]], today: _date) -> str:
    dues = [i["next_due"] for i in items if i["checked"] and i.get("next_due") and not _is_stale(i)]
    earliest = min(dues) if dues else (today + _timedelta(days=6)).isoformat()
    return max(earliest, today.isoformat())


def _engine_plan(state: dict[str, Any], items: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    lines = _lines(items)
    args = (_v2_catalog(), _v2_offers(), lines)
    sweep = day_sweep(*args, state["today"].isoformat(), _deadline(items, state["today"]), state["banks"],
                      state["max_stores"], state["trip_cost"], state["usual_store"])
    days = {d["date"] for d in sweep["days"]}
    day = state["day"] if state["day"] in days else sweep["best"]["date"]
    plan = engine_plan_day(*args, day, state["banks"], state["max_stores"], state["trip_cost"], state["usual_store"])
    return plan, sweep


def _near_misses(plan: dict[str, Any], banks: list[str]) -> list[str]:
    """Card offers that were active for a bill but paid nothing, and why (facts only)."""
    notes = []
    the_day = _date.fromisoformat(plan["day"]["date"])
    for bill in plan["stores"]:
        for offer in _v2_offers()["card_offers"]:
            if offer["bank"] not in banks or offer["store_id"] != bill["store_id"]:
                continue
            if WEEKDAYS[the_day.weekday()] not in offer["days"] or the_day > _date.fromisoformat(offer["valid_to"]):
                continue
            if bill["card"] and bill["card"]["offer_id"] == offer["id"]:
                continue
            include = offer.get("include_categories") or []
            exclude = offer.get("exclude_categories") or []
            eligible = sum(l["promoted_lkr"] for l in bill["lines"] if (not include or l["category"] in include) and l["category"] not in exclude)
            if eligible < offer["min_bill_lkr"]:
                notes.append(
                    f'{offer["bank"]} at {STORE_NAMES[bill["store_id"]]}: needs {_money(offer["min_bill_lkr"])} of '
                    f'{", ".join(include) or "eligible"} items; this bill has {_money(eligible)}, so it pays 0.'
                )
    return notes


def _step_nav(current: int) -> str:
    items = []
    for index, name in enumerate(STEPS):
        attrs = ' aria-current="step"' if index == current else ""
        cls = ' class="done"' if index < current else ""
        label = f'<a href="#{name.lower()}">{name}</a>' if index <= current else name
        items.append(f"<li{cls}{attrs}>{label}</li>")
    return f'<nav class="steps" aria-label="Steps"><ol>{"".join(items)}</ol></nav>'


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


def _render_pantry(items: list[dict[str, Any]], state: dict[str, Any], note: str | None) -> str:
    def row(item: dict[str, Any]) -> str:
        sku = _e(item["sku_id"])
        status = item["display_status"]
        reason = _reason_text(item)
        return (
            '<div class="item">'
            f'<input type="checkbox" id="sku_{sku}" name="sku" value="{sku}"{" checked" if item["checked"] else ""}>'
            f'<label class="name" for="sku_{sku}">{_e(item["name"])} <span class="status {_e(status)}">{_e(STATUS_TEXT[status])}</span></label>'
            f'<span><label class="sr-only" for="qty_{sku}">Quantity of {_e(item["name"])}</label>'
            f'<input type="number" id="qty_{sku}" name="qty_{sku}" min="0.001" max="{MAX_QTY}" step="any" value="{_e(item["qty"])}"></span>'
            f'<span class="reason">{_e(reason)}</span>'
            "</div>"
        )

    upcoming = [i for i in items if i["display_status"] in ("due", "soon", "stale")]
    later = [i for i in items if i["display_status"] in ("ok", "unknown")]
    added = f'<p class="ok-note">{_e(note)}</p>' if note else ""
    return (
        '<section class="step" id="pantry" aria-labelledby="pantry-h">'
        '<h2 id="pantry-h">1. Pantry: what is running low</h2>'
        '<p class="lead">Estimated from purchase history: the usual gap between buys, and the last purchase date. No guessing model.</p>'
        f"{added}"
        '<div class="grid two">'
        f'<div class="field"><label for="today">Planning date (demo control; the history ends 17 Oct 2026)</label>'
        f'<input type="date" id="today" name="today" value="{_e(state["today"].isoformat())}"></div>'
        '<div class="field"><span>Add a receipt to the history</span><div class="actions" style="margin-top:0">'
        '<button type="submit" name="action" formaction="/ui#pantry" value="sample">Use sample receipt</button>'
        '<button type="submit" name="action" formaction="/ui#pantry" value="extract">Extract this image</button></div></div>'
        "</div>"
        f'<h3>Due or soon ({len(upcoming)})</h3>{"".join(row(i) for i in upcoming) or "<p>Nothing runs out within 7 days.</p>"}'
        f'<details><summary>Later or not enough history ({len(later)})</summary>{"".join(row(i) for i in later)}</details>'
        '<input type="hidden" name="pantry_set" value="1">'
        '<div class="actions"><button class="primary" type="submit" name="action" formaction="/ui#wallet" value="wallet">Continue to wallet</button></div>'
        "</section>"
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
    return (
        '<section class="step" id="wallet" aria-labelledby="wallet-h">'
        '<h2 id="wallet-h">2. Wallet and trip</h2>'
        '<p class="lead">Cards are an issuer and product only. Savvy Cart never asks for a card number.</p>'
        '<div class="grid two">'
        f'<fieldset><legend>Cards you hold</legend>{cards}</fieldset>'
        "<fieldset><legend>Trip</legend>"
        f'<div class="field"><label for="usual_store">Usual store</label><select id="usual_store" name="usual_store">{stores}</select></div>'
        '<div class="field"><label for="max_stores">Stores in one day</label><select id="max_stores" name="max_stores">'
        f'<option value="1"{" selected" if state["max_stores"] == 1 else ""}>One store</option>'
        f'<option value="2"{" selected" if state["max_stores"] == 2 else ""}>Up to two stores</option></select></div>'
        f'<div class="field"><label for="trip_cost">Cost of an extra store visit (LKR, your estimate)</label>'
        f'<input type="number" id="trip_cost" name="trip_cost" min="0" max="5000" step="10" value="{state["trip_cost"]}"></div>'
        f'<div class="field"><label for="budget">Budget (LKR, shown only)</label>'
        f'<input type="number" id="budget" name="budget" min="0" step="100" value="{state["budget"]}"></div>'
        "</fieldset></div>"
        '<input type="hidden" name="wallet_set" value="1">'
        '<div class="actions"><button class="primary" type="submit" name="action" formaction="/ui#plan" value="plan">Plan my shopping</button>'
        '<button type="submit" name="action" formaction="/ui#plan" value="refused">Show a basket this offer refuses</button></div>'
        "</section>"
    )


def _render_bill(bill: dict[str, Any]) -> str:
    rows = "".join(
        "<tr>"
        f'<td>{_e(l["name"])} <span class="source">({_e("receipt price" if l["price_source"] == "receipt" else "fictional price")})</span></td>'
        f'<td class="num">{_e(l["qty"])}</td><td class="num">{_money(l["shelf_lkr"])}</td>'
        f'<td class="num">{_money(l["promo_saving_lkr"]) if l["promo_saving_lkr"] else "-"}</td>'
        "</tr>"
        for l in bill["lines"]
    )
    card = (
        f'<span class="card-used">Pay with {_e(bill["card"]["bank"])} {_e(bill["card"]["product"])}</span>'
        if bill["card"] else '<span class="source">No card offer applies</span>'
    )
    return (
        f'<article class="bill" data-store="{_e(bill["store_id"])}">'
        f'<header><h3>{_e(STORE_NAMES[bill["store_id"]])}</h3>{card}</header>'
        '<table><thead><tr><th>Item</th><th class="num">Qty</th><th class="num">Shelf</th><th class="num">Promotion</th></tr></thead>'
        f"<tbody>{rows}</tbody><tfoot>"
        f'<tr><td colspan="3">Card discount</td><td class="num">{_money(bill["card_discount_lkr"])}</td></tr>'
        f'<tr><td colspan="3">Bill total</td><td class="num">{_money(bill["bill_lkr"])}</td></tr>'
        "</tfoot></table></article>"
    )


def _render_plan(plan: dict[str, Any], sweep: dict[str, Any] | None, state: dict[str, Any], title_note: str = "") -> str:
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
            f'<h3>Best day before items run out (by {_e(sweep["window_end"])})</h3><ul class="sweep">{days}</ul>'
            f'<div class="field"><label for="day">Shop on</label><select id="day" name="day">{choices}</select></div>'
        )
    misses = "".join(f'<p class="notice">{_e(n)}</p>' for n in _near_misses(plan, state["banks"]))
    unpriced = f'<p class="notice">Not priced at any store: {_e(", ".join(plan["unpriced"]))}.</p>' if plan["unpriced"] else ""
    extra = f' plus {_money(plan["extra_trip_cost_lkr"])} for the extra trip' if plan["extra_trip_cost_lkr"] else ""
    return (
        '<section class="step" id="plan" aria-labelledby="plan-h">'
        f'<h2 id="plan-h">3. Plan for {_e(weekday)} {_e(plan["day"]["date"])}{_e(title_note)}</h2>'
        f'<p class="lead">{len(plan["stores"])} store{"s" if len(plan["stores"]) != 1 else ""}, chosen by an exact optimizer '
        f'(OR-Tools CP-SAT, status {_e(plan["solver_status"])}). Store promotions apply first, then at most one card offer per bill.</p>'
        '<div class="summary">'
        f'<div class="metric highlight"><div class="value">{_money(plan["effective_cost_lkr"])}</div><div class="label">Plan total{_e(extra)}</div></div>'
        f'<div class="metric"><div class="value">{_money(plan.get("saving_vs_usual_lkr"))}</div>'
        f'<div class="label">Saved against {_e(STORE_NAMES[usual.get("store_id", "keells")])} at shelf price ({_money(usual.get("total_lkr"))})</div></div>'
        f'<div class="metric"><div class="value">{_money(plan.get("saving_vs_single_lkr"))}</div>'
        f'<div class="label">Saved against the best single store ({_e(STORE_NAMES.get(single.get("store_id") or "", "none"))}, {_money(single.get("total_lkr"))})</div></div>'
        "</div>"
        f'<div class="bar" role="img" aria-label="Plan total is {pct} percent of the usual-store shelf total"><span style="width:{pct}%"></span></div>'
        f'<p class="bar-label">Plan total as a share of buying everything at your usual store at shelf price. {_e(budget_note)}</p>'
        f'<div class="grid two">{"".join(_render_bill(b) for b in plan["stores"])}</div>'
        f"{misses}{unpriced}{sweep_html}"
        f'<p class="source">Engine steps: pantry (purchase history), catalog and offers, planner (OR-Tools CP-SAT). Trip cost {_money(plan["trip_cost_lkr"])} per extra store.</p>'
        '<div class="actions"><button type="submit" name="action" formaction="/ui#plan" value="plan">Update plan</button>'
        '<button class="primary" type="submit" name="action" formaction="/ui#why" value="explain">Explain this plan</button>'
        '<button type="submit" name="action" formaction="/ui#approve" value="approve">Approve plan</button></div>'
        "</section>"
    )


def _normalize_numbers(text: str) -> str:
    text = _re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    return _re.sub(r"(?<=\d)\.00\b", "", text)


def _engine_summary(plan: dict[str, Any]) -> str:
    parts = []
    for bill in plan["stores"]:
        card = f' with {bill["card"]["bank"]} {bill["card"]["product"]}' if bill["card"] else ""
        parts.append(f'{STORE_NAMES[bill["store_id"]]}{card} for {len(bill["lines"])} items ({bill["bill_lkr"]} LKR)')
    return (
        f'Shop on {plan["day"]["weekday"].title()} {plan["day"]["date"]}: ' + "; ".join(parts) + ". "
        f'Plan total {plan["effective_cost_lkr"]} LKR, saving {plan.get("saving_vs_usual_lkr", 0)} LKR against your usual store at shelf price.'
    )


def _confirmed(plan: dict[str, Any], state: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    return {"lines": lines, "day": plan["day"]["date"], "banks": state["banks"], "max_stores": state["max_stores"],
            "trip_cost_lkr": state["trip_cost"], "usual_store": state["usual_store"]}


def _replan_differences(call_args: dict[str, Any], confirmed: dict[str, Any]) -> list[str]:
    diffs = []
    for key in ("day", "max_stores", "trip_cost_lkr", "usual_store"):
        if key in call_args and call_args[key] != confirmed[key]:
            diffs.append(f"{key} {call_args[key]} instead of {confirmed[key]}")
    if "banks" in call_args and sorted(call_args["banks"] or []) != sorted(confirmed["banks"]):
        diffs.append(f"cards {', '.join(call_args['banks'] or []) or 'none'} instead of {', '.join(confirmed['banks']) or 'none'}")
    if "lines" in call_args:
        def key_of(lines):
            return sorted((str(l.get("sku_id")), float(l.get("qty", 0))) for l in lines or [] if isinstance(l, dict))
        if key_of(call_args["lines"]) != key_of(confirmed["lines"]):
            diffs.append("a different basket")
    return diffs


async def _explain_v2(request: Request, plan: dict[str, Any], state: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    confirmed = _confirmed(plan, state, lines)
    runner = getattr(request.app.state, "agent_runner", None)
    if runner is None and _model_configured():
        from savvycart.agent import ask_agent

        runner = ask_agent
    fallback = {"text": _engine_summary(plan), "calls": [], "replans": []}
    if runner is None:
        return {**fallback, "source": "Model not configured: engine explanation."}
    context = {"confirmed": confirmed, "engine_plan": plan}
    try:
        answer = await asyncio.wait_for(runner(AGENT_QUESTION_V2, context), timeout=AGENT_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning("agent call failed: %s: %.200s", type(exc).__name__, exc)
        return {**fallback, "source": "The agent call failed. Showing the engine explanation."}
    calls = [c for c in answer.get("calls", []) if isinstance(c, dict)]
    allowed = numbers_in_plan(context)
    for result in answer.get("results", []):
        allowed |= numbers_in_plan(result if isinstance(result, (dict, list)) else {"value": result})
    text = drop_unallowed_number_tokens(_normalize_numbers(str(answer.get("text", ""))), allowed)
    saving = str(plan.get("saving_vs_usual_lkr", 0))
    if saving not in text:
        text = f"{text} Engine total {plan['effective_cost_lkr']} LKR, saving {saving} LKR against your usual store.".strip()
    replans = []
    for call in calls:
        if call.get("name") == "plan_day":
            diffs = _replan_differences(call.get("args") or {}, confirmed)
            if diffs:
                replans.append(diffs)
    return {"text": text, "calls": calls, "replans": replans,
            "source": "Answer from the ADK agent (Gemini). Numbers are checked against the engine plan and the agent's own tool results."}


def _render_why(explanation: dict[str, Any]) -> str:
    calls = "".join(
        f'<li><code>{_e(c.get("name"))}({_e(json.dumps(c.get("args") or {}, sort_keys=True)[:300])})</code></li>' for c in explanation["calls"]
    ) or "<li>No tool calls.</li>"
    if explanation["replans"]:
        replan = "".join(f'<p class="notice">The agent re-planned with different inputs: {_e("; ".join(d))}. Its comparison is not the plan above.</p>'
                         for d in explanation["replans"])
    elif explanation["calls"]:
        replan = '<p class="ok-note">The agent did not change your inputs.</p>'
    else:
        replan = ""
    return (
        '<section class="step" id="why" aria-labelledby="why-h">'
        '<h2 id="why-h">4. Why this plan</h2>'
        f'<p class="source" id="explanation-source">{_e(explanation["source"])}</p>'
        f'<p id="explanation-text">{_e(explanation["text"])}</p>'
        f"{replan}"
        f'<h3>Agent tools called</h3><ul class="tools" id="agent-tools">{calls}</ul>'
        "</section>"
    )


def _render_approve(preview: dict[str, Any] | None) -> str:
    body = (f'<p><strong>MOCK</strong> preview {_e(preview["preview_id"])}.</p>' if preview else "<p><strong>MOCK</strong> preview unavailable.</p>")
    return (
        '<section class="step" id="approve" aria-labelledby="approve-h">'
        '<h2 id="approve-h">5. Approve</h2>'
        f'<div class="mock">{body}<p>No order is sent. Savvy Cart does not contact any store or bank.</p></div>'
        "</section>"
    )


def _layout(current: int, inner: str, state: dict[str, Any], message: str | None) -> str:
    alert = f'<p class="notice" role="status">{_e(message)}</p>' if message else ""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Savvy Cart AI</title>"
        '<link rel="stylesheet" href="/static/app.css"></head><body>'
        '<a class="skip-link" href="#main">Skip to the plan</a>'
        f'<div class="banner" id="banner"><div class="wrap">{_e(V2_BANNER)}</div></div>'
        '<header class="site"><div class="wrap"><h1>Savvy Cart AI</h1>'
        "<p class=\"tagline\">Karuppan's next shop: when to buy, where, and with which card.</p></div></header>"
        f'<main id="main"><div class="wrap">{_step_nav(current)}{alert}'
        '<form method="post" action="/ui">'
        f'<input type="hidden" name="receipt_json" value="{_e(json.dumps(state["added"]))}">'
        f"{inner}</form></div></main>"
        '<footer class="site"><div class="wrap">Prototype for the Google Cloud AI Builder Cup. Pricing runs in code; Gemini explains it. '
        "No login, no card numbers, no real orders.</div></footer></body></html>"
    )


@app.get("/", response_class=HTMLResponse)
def guest_page() -> str:
    state = _parse_state({})
    items = _pantry_view(state)
    return _layout(0, _render_pantry(items, state, None), state, None)


@app.post("/ui", response_class=HTMLResponse)
async def guest_action(request: Request) -> str:
    form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    state = _parse_state(form)
    action = form.get("action", ["pantry"])[0]
    message: str | None = None
    note: str | None = None

    if action in ("sample", "extract"):
        if action == "sample":
            lines = json.loads(SAMPLE_RECEIPT_V2.read_text(encoding="utf-8"))["lines"]
            label = "the sample receipt"
        else:
            response = await _internal_post(request, "/v1/receipts", content=SAMPLE_PHOTO_V2.read_bytes(),
                                            headers={"content-type": "image/jpeg"})
            lines = response.json().get("lines", []) if response.status_code == 200 else None
            label = "the live extract"
        if lines is None:
            message = "The live extract failed. Nothing was added; use the sample receipt instead."
        else:
            rows, skipped = _receipt_rows(lines, state["today"].isoformat())
            state["added"] = state["added"] + rows
            state["pantry_set"] = False
            note = (f"Added {len(rows)} lines from {label} as purchases on {state['today'].isoformat()}; "
                    f"{skipped} lines are not regular items and were left out.")

    items = _pantry_view(state)
    sections = [_render_pantry(items, state, note)]
    current = 0
    if action in ("wallet", "plan", "explain", "approve", "refused"):
        sections.append(_render_wallet(state))
        current = 1
    if action in ("plan", "explain", "approve"):
        if not _lines(items):
            message = "Pick at least one item in the pantry to plan a shop."
        else:
            plan, sweep = _engine_plan(state, items)
            sections.append(_render_plan(plan, sweep, state))
            current = 2
            if action == "explain":
                sections.append(_render_why(await _explain_v2(request, plan, state, _lines(items))))
                current = 3
            if action == "approve":
                lines = [{"sku_id": l["sku_id"], "qty": max(1, round(l["qty"]))} for l in _lines(items)]
                approved = await _internal_post(request, "/v1/approve", json={
                    "line_ids": lines, "day": {"weekday": plan["day"]["weekday"], "date": plan["day"]["date"]},
                    "card_product_id": ",".join(state["banks"]) or "none", "usual_store": state["usual_store"],
                    "store_id": plan["stores"][0]["store_id"] if plan["stores"] else None})
                sections.append(_render_approve(approved.json() if approved.status_code == 200 else None))
                current = 4
    if action == "refused":
        today = state["today"]
        saturday = today + _timedelta(days=(5 - today.weekday()) % 7)
        control = engine_plan_day(_v2_catalog(), _v2_offers(), [{"sku_id": "banana_ambul", "qty": 1}, {"sku_id": "tomatoes", "qty": 0.5}],
                                  saturday.isoformat(), [b for b, _ in WALLET_CARDS], 1, state["trip_cost"], "keells")
        sections.append(_render_plan(control, None, state, " (control basket)"))
        current = 2
        message = "Control basket: two fresh items at Keells. The card offers have minimum bills, so this basket earns no card discount."
    return _layout(current, "".join(sections), state, message)
