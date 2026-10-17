"""FastAPI app: guest page, plans, mock approve, receipt extract, explain."""

from __future__ import annotations

import html
import json
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

from savvycart.explain import explain_plan
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
    """Model client for plans, receipts, and explain."""

    def generate(self, *args: Any, **kwargs: Any) -> Any: ...

    def extract(self, image_bytes: bytes, schema: dict[str, Any]) -> dict[str, Any] | str: ...

    def explain(self, plan_json: dict[str, Any], instruction: str) -> str: ...


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

    def explain(self, plan_json: dict[str, Any], instruction: str) -> str:
        self.calls += 1
        raise RuntimeError("configure an explain model client on app.state.model_client")


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


def _default_model_client() -> ModelClient:
    model = os.environ.get("GEMINI_MODEL", "")
    has_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true"
    if model and (has_key or vertex):
        from savvycart.gemini import GeminiModelClient

        return GeminiModelClient(model)
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
    explained = explain_plan(summary, model_client=model_client)
    return {
        "text": explained["text"],
        "cited_fields": explained["cited_fields"],
    }


# --- Guest page (server-rendered, no login) ---------------------------------

SAMPLE_LABEL = "fixture lines for the sample path"
LIVE_LABEL = "live extract"
CONFIDENCE_FLOOR = 0.6
STORES = ["keells", "cargills", "spar"]
CARD_PRODUCTS = [("commercial_bank:credit", "Commercial Bank credit")]
DEMO_DATES = {
    "monday": "2026-10-12",
    "tuesday": "2026-10-13",
    "wednesday": "2026-10-14",
    "thursday": "2026-10-15",
    "friday": "2026-10-16",
    "saturday": "2026-10-17",
    "sunday": "2026-10-18",
}
DEFAULT_PERSONA = {
    "weekday": "saturday",
    "usual_store": "keells",
    "budget": "12000",
    "card_product_id": "commercial_bank:credit",
}


@lru_cache(maxsize=None)
def _load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _sku_names() -> dict[str, str]:
    return {sku["id"]: sku["name"] for sku in _load_catalog()["skus"]}


def _substitutions() -> dict[str, str]:
    return {p["sku_id"]: p["alternate_sku_id"] for p in _load_fixture("substitutions.json")["pairs"]}


async def _internal_post(request: Request, path: str, **kwargs: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=request.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://savvycart.internal") as client:
        return await client.post(path, **kwargs)


def _clean_receipt_lines(value: Any) -> list[dict[str, Any]]:
    """Keep only well-formed receipt rows; the hidden form field is untrusted."""
    if not isinstance(value, list):
        return []
    known = set(_sku_names())
    cleaned: list[dict[str, Any]] = []
    for line in value:
        if not isinstance(line, dict):
            continue
        sku_id = line.get("sku_id")
        try:
            qty = int(float(line.get("qty", 1)))
            confidence = min(1.0, max(0.0, float(line.get("confidence", 0))))
        except (TypeError, ValueError):
            continue
        if qty < 1:
            continue
        cleaned.append(
            {
                "raw": str(line.get("raw", "")),
                "sku_id": sku_id if isinstance(sku_id, str) and sku_id in known else None,
                "qty": qty,
                "confidence": confidence,
            }
        )
    return cleaned


def _checked_receipt_ids(lines: list[dict[str, Any]]) -> list[str]:
    return [
        line["sku_id"]
        for line in lines
        if line.get("sku_id") and float(line.get("confidence", 0)) >= CONFIDENCE_FLOOR
    ]


def _basket(
    receipt_lines: list[dict[str, Any]],
    checked: set[str],
    staples_checked: set[str],
    swap: str,
) -> list[dict[str, Any]]:
    """Ordered union of confirmed receipt lines and checked staples, swap applied."""
    qty: dict[str, int] = {}
    for line in receipt_lines:
        if line.get("sku_id") in checked:
            qty.setdefault(line["sku_id"], int(line.get("qty", 1)))
    for line in _load_fixture("staples.json")["lines"]:
        if line["sku_id"] in staples_checked:
            qty.setdefault(line["sku_id"], int(line["qty"]))
    subs = _substitutions() if swap == "applied" else {}
    return [{"sku_id": subs.get(sku_id, sku_id), "qty": n} for sku_id, n in qty.items()]


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _render_persona(persona: dict[str, str]) -> str:
    weekday_opts = "".join(
        f'<option value="{d}"{" selected" if d == persona["weekday"] else ""}>{d.title()}</option>'
        for d in DEMO_DATES
    )
    store_opts = "".join(
        f'<option value="{s}"{" selected" if s == persona["usual_store"] else ""}>{s.title()}</option>'
        for s in STORES
    )
    card_opts = "".join(
        f'<option value="{_e(pid)}"{" selected" if pid == persona["card_product_id"] else ""}>{_e(label)}</option>'
        for pid, label in CARD_PRODUCTS
    )
    return (
        "<section id=\"persona\"><h2>Shopper</h2>"
        "<p>Karuppan, Saturday, Commercial Bank credit, budget about LKR 12,000.</p>"
        f'<label>Weekday <select name="weekday">{weekday_opts}</select></label> '
        f'<label>Usual store <select name="usual_store">{store_opts}</select></label> '
        f'<label>Budget (LKR) <input name="budget" type="number" min="0" value="{_e(persona["budget"])}"></label> '
        f'<label>Card (issuer and product id) <select name="card_product_id">{card_opts}</select></label>'
        "<p>The budget is shown only. It does not change the winner or the discount.</p>"
        "</section>"
    )


def _render_staples(staples_checked: set[str]) -> str:
    names = _sku_names()
    rows = "".join(
        "<li><label>"
        f'<input type="checkbox" name="staple" value="{_e(line["sku_id"])}"'
        f'{" checked" if line["sku_id"] in staples_checked else ""}> '
        f'{_e(names.get(line["sku_id"], line["sku_id"]))}'
        f'{" (running low)" if line["running_low"] else ""}'
        "</label></li>"
        for line in _load_fixture("staples.json")["lines"]
    )
    return (
        "<section id=\"staples\"><h2>Staples</h2>"
        "<p>Running low only pre-checks a row. It does not change the optimizer.</p>"
        f"<ul>{rows}</ul></section>"
    )


def _render_receipt(lines: list[dict[str, Any]], checked: set[str], label: str | None) -> str:
    if not lines:
        return "<section id=\"receipt\"><h2>Receipt</h2><p>No receipt lines yet.</p></section>"
    rows = "".join(
        "<li><label>"
        f'<input type="checkbox" name="line" value="{_e(line["sku_id"])}"'
        f'{" checked" if line["sku_id"] in checked else ""}> '
        f'{_e(line["raw"])} — {_e(line["sku_id"])} (confidence {_e(line["confidence"])})'
        "</label></li>"
        if line.get("sku_id")
        else f'<li>{_e(line["raw"])} — not matched, ignored</li>'
        for line in lines
    )
    return (
        "<section id=\"receipt\"><h2>Receipt</h2>"
        f'<p id="receipt-label">Showing {_e(label or SAMPLE_LABEL)}.</p>'
        f"<ul>{rows}</ul>"
        f'<input type="hidden" name="receipt_json" value="{_e(json.dumps(lines))}">'
        f'<input type="hidden" name="receipt_label" value="{_e(label or SAMPLE_LABEL)}">'
        "</section>"
    )


def _render_plans(plans: dict[str, Any], swap: str, basket: list[dict[str, Any]]) -> str:
    names = _sku_names()
    offers = {o["id"]: o for o in _load_offers()}
    winner_store = (plans.get("winner") or {}).get("store_id")
    rows = "".join(
        "<tr>"
        f'<td>{_e(p["store_id"].title())}{" (winner)" if p["store_id"] == winner_store else ""}</td>'
        f'<td>{_e(p["shelf_total"])} LKR</td>'
        f'<td>{_e(p["discount"])} LKR</td>'
        f'<td>{_e(p["effective_cost"])} LKR</td>'
        f'<td>{_e(p["offer_id"] or "no offer")}</td>'
        f'<td>{"complete" if p["complete"] else "incomplete (missing price)"}'
        f'{" — rule ended in this snapshot" if p["reason"] == "expired" else ""}</td>'
        "</tr>"
        for p in plans["plans"]
    )
    headline = ""
    for p in plans["plans"]:
        offer = offers.get(p["offer_id"]) if p["offer_id"] else None
        if offer is None:
            continue
        percent = f'{offer["rate_bps"] // 100}% off'
        shown = f"<s>{percent}</s>" if p["naive_discount"] > p["discount"] else percent
        headline += (
            f'<p class="headline">{_e(p["store_id"].title())} card headline: {shown}. '
            f'Legal saving: {_e(p["discount"])} LKR. Offer valid_to {_e(offer["valid_to"])}.</p>'
        )
    sweep = "".join(
        f'<li>Keells {_e(day.title())}: legal saving {_e(s["discount"])} LKR '
        f'on the same shelf total of {_e(s["shelf_total"])} LKR</li>'
        for day, s in plans["day_sweep"].items()
        if s is not None
    )
    valid_to = "".join(
        f'<li>{_e(o["id"])}: valid_to {_e(o["valid_to"])}</li>' for o in offers.values()
    )
    baseline = plans.get("baseline") or {}
    swap_note = ""
    for original, alternate in _substitutions().items():
        if swap == "applied" and any(line["sku_id"] == alternate for line in basket):
            swap_note = (
                f'<p id="swap">Swap applied: {_e(names.get(original, original))} → '
                f'{_e(names.get(alternate, alternate))}.</p>'
            )
        elif swap == "rejected":
            swap_note = f'<p id="swap">Swap rejected: {_e(names.get(original, original))} restored.</p>'
    tools = ", ".join(plans.get("tools", []))
    return (
        "<section id=\"plans\"><h2>One-store plans</h2>"
        f"{swap_note}"
        f'<p>Baseline at your usual store, no offer: {_e(baseline.get("shelf_total", "n/a"))} LKR.</p>'
        f"{headline}"
        "<table><thead><tr><th>Store</th><th>Shelf total</th><th>Legal saving</th>"
        "<th>Effective cost</th><th>Offer</th><th>Status</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        f"<h3>Other offer-day</h3><ul>{sweep}</ul>"
        f"<h3>Offer end dates</h3><ul>{valid_to}</ul>"
        f'<p id="tools">Tools run: {_e(tools)}</p>'
        "</section>"
    )


def _option_summary(plans: dict[str, Any]) -> dict[str, Any]:
    """Winner cost and whether the offer minimum is met, all from engine output."""
    offers = {o["id"]: o for o in _load_offers()}
    winner = plans.get("winner") or {}
    offer_plan = next((p for p in plans["plans"] if p["offer_id"]), None)
    note = "No card offer applies on this day."
    if offer_plan is not None:
        offer = offers[offer_plan["offer_id"]]
        shortfall = int(offer["min_bill_lkr"]) - int(offer_plan["eligible_subtotal"])
        if offer_plan["reason"] == "expired":
            note = "The offer rule ended in this snapshot."
        elif shortfall > 0:
            note = (
                f'Eligible items are {shortfall} LKR below the {offer["min_bill_lkr"]} LKR offer minimum, '
                "so the offer pays 0."
            )
        else:
            note = f'Offer minimum met. Legal saving at {offer_plan["store_id"].title()}: {offer_plan["discount"]} LKR.'
    return {
        "store_id": winner.get("store_id"),
        "effective_cost": winner.get("effective_cost"),
        "discount": winner.get("discount"),
        "note": note,
    }


def _render_options(options: dict[str, Any]) -> str:
    names = _sku_names()
    original, alternate = next(iter(_substitutions().items()))
    rows_spec = [
        ("applied", "Option A — buy what you need", names.get(alternate, alternate)),
        ("rejected", f"Option B — restore {names.get(original, original)}", names.get(original, original)),
    ]
    summaries = {state: _option_summary(options[state]) for state, _, _ in rows_spec}
    rows = "".join(
        f'<tr class="option" data-option="{state}">'
        f"<td>{_e(label)}{' (selected)' if options['selected'] == state else ''}</td>"
        f"<td>{_e(item)}</td>"
        f'<td>{_e((summaries[state]["store_id"] or "none").title())}</td>'
        f'<td>{_e(summaries[state]["effective_cost"])} LKR</td>'
        f'<td>{_e(summaries[state]["discount"])} LKR</td>'
        f'<td>{_e(summaries[state]["note"])}</td>'
        "</tr>"
        for state, label, item in rows_spec
    )
    a = summaries["applied"]["effective_cost"]
    b = summaries["rejected"]["effective_cost"]
    if a is None or b is None:
        verdict = "One option has no complete plan."
    elif a < b:
        verdict = f"Buying what you need costs {b - a} LKR less than restoring the original item."
    elif b < a:
        verdict = f"Restoring the original item costs {a - b} LKR less, because the offer pays."
    else:
        verdict = "Both options cost the same."
    return (
        '<section id="options"><h2>Your options</h2>'
        "<p>You choose. The page never adds items to reach an offer minimum.</p>"
        "<table><thead><tr><th>Option</th><th>Item</th><th>Winner</th><th>Effective cost</th>"
        "<th>Legal saving</th><th>Offer</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        f'<p id="options-verdict">{_e(verdict)}</p>'
        "</section>"
    )


def _render_page(
    *,
    persona: dict[str, str],
    staples_checked: set[str],
    receipt_lines: list[dict[str, Any]],
    checked: set[str],
    receipt_label: str | None,
    swap: str,
    plans: dict[str, Any] | None = None,
    basket: list[dict[str, Any]] | None = None,
    message: str | None = None,
    approve: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> str:
    can_reject = plans is not None and swap == "applied" and any(
        line["sku_id"] in _substitutions().values() for line in (basket or [])
    )
    can_keep = plans is not None and swap == "rejected" and any(
        line["sku_id"] in _substitutions() for line in (basket or [])
    )
    can_approve = plans is not None and plans.get("winner") is not None
    controls = (
        "<section id=\"controls\">"
        '<button type="submit" name="action" value="sample">Use sample receipt</button> '
        '<button type="submit" name="action" value="extract">Extract this image</button> '
        f'<button type="submit" name="action" value="reject_swap"{"" if can_reject else " disabled"}>Reject swap</button> '
        f'<button type="submit" name="action" value="keep_swap"{"" if can_keep else " disabled"}>Keep swap</button> '
        f'<button type="submit" name="action" value="approve"{"" if can_approve else " disabled"}>Approve plan</button> '
        '<button type="submit" name="action" value="refused">Show a basket this offer refuses</button>'
        "</section>"
    )
    body = [
        f'<p id="banner"><strong>{_e(DATA_LABEL)}</strong></p>',
        f'<p id="message">{_e(message)}</p>' if message else "",
        '<form method="post" action="/ui">',
        _render_persona(persona),
        _render_staples(staples_checked),
        _render_receipt(receipt_lines, checked, receipt_label),
        f'<input type="hidden" name="swap" value="{_e(swap)}">',
        controls,
        "</form>",
        _render_options(options) if options else "",
        _render_plans(plans, swap, basket or []) if plans is not None else "",
        (
            '<section id="approve"><h2>Order preview — MOCK</h2>'
            f'<p>MOCK preview {_e(approve["preview_id"])}. No order is sent.</p></section>'
            if approve
            else ""
        ),
    ]
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Savvy Cart AI</title></head><body><h1>Savvy Cart AI</h1>"
        + "".join(body)
        + "</body></html>"
    )


def _default_staples() -> set[str]:
    return {line["sku_id"] for line in _load_fixture("staples.json")["lines"] if line["running_low"]}


@app.get("/", response_class=HTMLResponse)
def guest_page() -> str:
    return _render_page(
        persona=dict(DEFAULT_PERSONA),
        staples_checked=_default_staples(),
        receipt_lines=[],
        checked=set(),
        receipt_label=None,
        swap="applied",
    )


@app.post("/ui", response_class=HTMLResponse)
async def guest_action(request: Request) -> str:
    form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)

    def get(key: str, default: str) -> str:
        return form.get(key, [default])[0]

    persona = {
        "weekday": get("weekday", DEFAULT_PERSONA["weekday"]),
        "usual_store": get("usual_store", DEFAULT_PERSONA["usual_store"]),
        "budget": get("budget", DEFAULT_PERSONA["budget"]),
        "card_product_id": get("card_product_id", DEFAULT_PERSONA["card_product_id"]),
    }
    if persona["weekday"] not in DEMO_DATES:
        persona["weekday"] = DEFAULT_PERSONA["weekday"]
    if persona["usual_store"] not in STORES:
        persona["usual_store"] = DEFAULT_PERSONA["usual_store"]
    if persona["card_product_id"] not in dict(CARD_PRODUCTS):
        persona["card_product_id"] = DEFAULT_PERSONA["card_product_id"]

    action = get("action", "plan")
    staples_checked = set(form.get("staple", []))
    try:
        receipt_lines = _clean_receipt_lines(json.loads(get("receipt_json", "[]")))
    except json.JSONDecodeError:
        receipt_lines = []
    receipt_label = get("receipt_label", "") or None
    checked = set(form.get("line", []))
    swap = get("swap", "applied")
    if swap not in ("applied", "rejected"):
        swap = "applied"
    message: str | None = None

    sample_lines = _load_fixture("receipt-expected.json")["lines"]
    if action == "sample":
        receipt_lines, receipt_label, swap = sample_lines, SAMPLE_LABEL, "applied"
        checked = set(_checked_receipt_ids(receipt_lines))
    elif action == "extract":
        png = (FIXTURES / "receipt-sample.png").read_bytes()
        extracted = await _internal_post(
            request,
            "/v1/receipts",
            content=png,
            headers={"content-type": "image/png"},
        )
        if extracted.status_code == 200:
            receipt_lines, receipt_label = _clean_receipt_lines(extracted.json().get("lines")), LIVE_LABEL
        else:
            receipt_lines, receipt_label = sample_lines, SAMPLE_LABEL
            message = "The live extract failed. The sample lines stay."
        checked = set(_checked_receipt_ids(receipt_lines))
        swap = "applied"
    elif action == "reject_swap":
        swap = "rejected"
    elif action == "keep_swap":
        swap = "applied"

    if action == "refused":
        basket = [dict(line) for line in _load_fixture("baskets/refused.json")["lines"]]
        message = "Control basket from fixtures/baskets/refused.json: the eligible subtotal misses the minimum."
    else:
        basket = _basket(receipt_lines, checked, staples_checked, swap)

    identity = {
        "line_ids": basket,
        "day": {"weekday": persona["weekday"], "date": DEMO_DATES[persona["weekday"]]},
        "card_product_id": persona["card_product_id"],
        "usual_store": persona["usual_store"],
    }
    plans: dict[str, Any] | None = None
    approve: dict[str, Any] | None = None
    response = await _internal_post(request, "/v1/plans", json=identity)
    if response.status_code == 200:
        plans = response.json()
    elif not basket:
        message = message or "Confirm at least one line to price a plan."
    else:
        message = message or "The plan request failed."

    options: dict[str, Any] | None = None
    needed = _basket(receipt_lines, checked, staples_checked, "rejected")
    if action != "refused" and plans is not None and any(line["sku_id"] in _substitutions() for line in needed):
        other = "rejected" if swap == "applied" else "applied"
        other_basket = _basket(receipt_lines, checked, staples_checked, other)
        compared = await _internal_post(request, "/v1/plans", json={**identity, "line_ids": other_basket})
        if compared.status_code == 200:
            options = {swap: plans, other: compared.json(), "selected": swap}

    if action == "approve" and plans and plans.get("winner"):
        approved = await _internal_post(
            request,
            "/v1/approve",
            json={**identity, "store_id": plans["winner"]["store_id"]},
        )
        if approved.status_code == 200:
            approve = approved.json()

    return _render_page(
        persona=persona,
        staples_checked=staples_checked,
        receipt_lines=receipt_lines,
        checked=checked,
        receipt_label=receipt_label,
        swap=swap if action != "refused" else "applied",
        plans=plans,
        basket=basket,
        message=message,
        approve=approve,
        options=options,
    )
