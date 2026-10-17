"""Mock store and bank endpoints, built from the same fixtures the engine reads. Not real partner APIs."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException

from savvycart.agent import load_catalog, load_offers

router = APIRouter(prefix="/mock", tags=["mock partners"])
STORE_NAMES = {"keells": "Keells", "cargills": "Cargills", "spar": "SPAR", "glomark": "Glomark"}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _envelope(**body: Any) -> dict[str, Any]:
    catalog = load_catalog()
    return {"mock": True, "data_label": catalog["data_label"], "offers_note": load_offers()["note"], **body}


@router.get("/stores")
def stores() -> dict[str, Any]:
    return _envelope(stores=[{"id": s, "name": STORE_NAMES.get(s, s)} for s in load_catalog()["stores"]])


@router.get("/stores/{store_id}/catalog")
def store_catalog(store_id: str) -> dict[str, Any]:
    catalog = load_catalog()
    if store_id not in catalog["stores"]:
        raise HTTPException(status_code=404, detail="unknown store")
    items = [
        {"sku_id": sku["id"], "name": sku["name"], "category": sku["category"], "price_lkr": sku["prices"][store_id]["amount_lkr"],
         "price_source": sku["prices"][store_id]["source"]}
        for sku in catalog["skus"] if store_id in sku["prices"]
    ]
    promotions = [p for p in load_offers()["store_promotions"] if p["store_id"] == store_id]
    return _envelope(store_id=store_id, items=items, promotions=promotions)


@router.get("/banks")
def banks() -> dict[str, Any]:
    names = sorted({o["bank"] for o in load_offers()["card_offers"]})
    return _envelope(banks=[{"id": _slug(n), "name": n} for n in names])


@router.get("/banks/{bank_id}/offers")
def bank_offers(bank_id: str) -> dict[str, Any]:
    offers = [o for o in load_offers()["card_offers"] if _slug(o["bank"]) == bank_id]
    if not offers:
        raise HTTPException(status_code=404, detail="unknown bank")
    return _envelope(bank_id=bank_id, offers=offers)
