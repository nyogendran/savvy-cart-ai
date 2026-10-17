"""Mock store and bank endpoints serve exactly the engine's labeled fixtures (SC-019 AC10)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from savvycart.http import app

V2 = Path(__file__).resolve().parents[1] / "fixtures" / "v2"


def test_mock_partner_endpoints_serve_the_engine_fixtures():
    catalog = json.loads((V2 / "catalog.json").read_text(encoding="utf-8"))
    offers = json.loads((V2 / "offers.json").read_text(encoding="utf-8"))
    with TestClient(app) as http:
        stores = http.get("/mock/stores").json()
        assert stores["mock"] is True and stores["data_label"] == catalog["data_label"]
        assert [s["id"] for s in stores["stores"]] == catalog["stores"]
        for store in catalog["stores"]:
            body = http.get(f"/mock/stores/{store}/catalog").json()
            assert body["mock"] is True and body["data_label"] == catalog["data_label"]
            assert {i["sku_id"]: i["price_lkr"] for i in body["items"]} == {s["id"]: s["prices"][store]["amount_lkr"] for s in catalog["skus"]}
            assert body["promotions"] == [p for p in offers["store_promotions"] if p["store_id"] == store]
        banks = http.get("/mock/banks").json()
        assert banks["mock"] is True and {b["name"] for b in banks["banks"]} == {o["bank"] for o in offers["card_offers"]}
        served = []
        for bank in banks["banks"]:
            body = http.get(f"/mock/banks/{bank['id']}/offers").json()
            assert body["mock"] is True and all(o["bank"] == bank["name"] for o in body["offers"])
            served += body["offers"]
        assert sorted(served, key=lambda o: o["id"]) == sorted(offers["card_offers"], key=lambda o: o["id"])
        assert http.get("/mock/stores/arpico/catalog").status_code == 404
        assert http.get("/mock/banks/boc/offers").status_code == 404
