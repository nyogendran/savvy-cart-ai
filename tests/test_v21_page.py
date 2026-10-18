"""v2.1 wizard: bounded date, one step at a time, add item, receipt upload, suggestions, mock delivery (SC-019)."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from savvycart.http import _pantry_view, _parse_state, _v2_catalog, _v2_offers, app, engine_plan_day
from savvycart.receipts import MemoryStorage

FORM = {"content-type": "application/x-www-form-urlencoded"}
BANKS = ["Commercial Bank", "Nations Trust Bank", "HNB"]


class _Form(HTMLParser):
    """What a browser would submit: hidden fields, checked boxes and radios, number values, selected options."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: list[tuple[str, str]] = []
        self._select: str | None = None
        self._first_option: str | None = None
        self._selected = False

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        if tag == "input" and a.get("name"):
            kind = a.get("type", "text")
            if kind in ("checkbox", "radio"):
                if "checked" in a:
                    self.fields.append((a["name"], a.get("value", "on")))
            elif kind not in ("file", "submit"):
                self.fields.append((a["name"], a.get("value", "")))
        elif tag == "select":
            self._select, self._first_option, self._selected = a.get("name"), None, False
        elif tag == "option" and self._select:
            if self._first_option is None:
                self._first_option = a.get("value", "")
            if "selected" in a:
                self.fields.append((self._select, a.get("value", "")))
                self._selected = True

    def handle_endtag(self, tag):
        if tag == "select" and self._select:
            if not self._selected and self._first_option is not None:
                self.fields.append((self._select, self._first_option))
            self._select = None


def _fields(page: str, drop: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    parser = _Form()
    parser.feed(page)
    return [(k, v) for k, v in parser.fields if k not in drop]


def _submit(http: TestClient, page: str, action: str, changes: list[tuple[str, str]] | None = None, drop: tuple[str, ...] = ()) -> str:
    changed = {k for k, _ in changes or []}
    fields = [(k, v) for k, v in _fields(page, drop) if k not in changed] + (changes or [])
    response = http.post("/ui", content=urlencode([("action", action)] + fields), headers=FORM)
    assert response.status_code == 200
    return response.text


def _sections(page: str) -> list[str]:
    return re.findall(r'<section class="step" id="(\w+)"', page)


def test_planning_date_is_a_bounded_demo_control():
    with TestClient(app) as http:
        home = http.get("/").text
        select = re.search(r'<select id="today" name="today">(.*?)</select>', home, re.S).group(1)
        values = re.findall(r'<option value="([\d-]+)"', select)
        assert values[0] == "2026-10-17" and values[-1] == "2026-10-31" and len(values) == 15
        assert '<label for="today">Planning date (17 to 31 Oct 2026)</label>' in home
        assert re.search(r'<option value="2026-10-22" selected>', select)
        for outside in ("2026-06-01", "2026-10-16", "2026-11-01", "garbage"):
            page = _submit(http, home, "pantry", [("today", outside)])
            assert re.search(r'<option value="2026-10-22" selected>', page), outside
        inside = _submit(http, home, "pantry", [("today", "2026-10-25")])
        assert re.search(r'<option value="2026-10-25" selected>', inside)
        assert 'id="date-update"' in home and 'addEventListener("change"' in home


def test_wizard_shows_one_step_at_a_time():
    with TestClient(app) as http:
        home = http.get("/").text
        assert _sections(home) == ["pantry"]
        wallet = _submit(http, home, "wallet", drop=("sku",), changes=[("sku", "banana_ambul"), ("sku", "tomatoes")])
        assert _sections(wallet) == ["wallet"]
        plan = _submit(http, wallet, "plan", [("max_stores", "1"), ("bank", "HNB")], drop=("bank",))
        assert _sections(plan) == ["plan"]
        why = _submit(http, plan, "explain")
        approve = _submit(http, why, "approve")
        for page, step in ((wallet, "Wallet"), (plan, "Plan"), (why, "Why"), (approve, "Approve")):
            assert re.search(rf'<li aria-current="step"><span>{step}</span></li>', page), step
            assert '<button type="submit" name="action" value="' in page and 'class="back">Back</button>' in page
        assert _sections(why) == ["why"] and _sections(approve) == ["approve"]
        assert "(you allowed up to 1)" in plan
        # Back keeps every earlier choice: basket, wallet, and store limit.
        back = _submit(http, approve, "pantry")
        assert _sections(back) == ["pantry"]
        checked = set(re.findall(r'name="sku" value="([^"]+)" checked', back))
        assert checked == {"banana_ambul", "tomatoes"}
        assert '<input type="hidden" name="max_stores" value="1">' in back
        assert re.findall(r'<input type="hidden" name="bank" value="([^"]+)">', back) == ["HNB"]
        again = _submit(http, back, "plan")
        assert "(you allowed up to 1)" in again and len(re.findall(r'<article class="bill"', again)) == 1


def test_shopper_can_add_a_catalog_item():
    with TestClient(app) as http:
        home = http.get("/").text
        options = re.search(r'<select id="add_sku" name="add_sku">(.*?)</select>', home, re.S).group(1)
        assert 'value="papaya"' in options and 'value="banana_ambul"' not in options  # due items are already listed
        added = _submit(http, home, "add", [("add_sku", "papaya"), ("add_qty", "2")])
        assert re.search(r'name="sku" value="papaya" checked', added) and "Added by you" in added
        assert 'name="qty_papaya" min="0.5" max="50" step="0.5" value="2"' in added
        plan = _submit(http, added, "plan")
        assert re.search(r'<article class="bill"[^>]*>(?:(?!</article>).)*Papaya', plan, re.S)
        refused = _submit(http, home, "add", [("add_sku", "unicorn")])
        assert "Only items in the catalog can be added." in refused


class _ReceiptModel:
    def __init__(self) -> None:
        self.images: list[bytes] = []

    def extract(self, image_bytes: bytes, schema: dict[str, Any]) -> dict[str, Any]:
        self.images.append(image_bytes)
        return {"lines": [{"raw": "BANANA - AMBUL", "sku_id": None, "qty": 1},
                          {"raw": "VISA 4111111111111111", "sku_id": None, "qty": 1}]}


def test_uploaded_receipt_adds_listed_lines():
    photo = b"\xff\xd8\xff\xe0" + b"fake-jpeg-bytes"
    model, storage = _ReceiptModel(), MemoryStorage()
    with TestClient(app) as http:
        home = http.get("/").text
        no_model = http.post("/ui", data=dict(_fields(home)) | {"action": "upload"}, files={"receipt_photo": ("r.jpg", photo, "image/jpeg")})
        assert no_model.status_code == 200 and "The live extract is unavailable here" in no_model.text
        assert '<input type="hidden" name="receipt_json" value="[]">' in no_model.text
        app.state.model_client, app.state.storage, app.state.extract_rate_limiter = model, storage, None
        try:
            page = http.post("/ui", data=dict(_fields(home)) | {"action": "upload"}, files={"receipt_photo": ("r.jpg", photo, "image/jpeg")}).text
            wrong = http.post("/ui", data={"action": "upload"}, files={"receipt_photo": ("r.gif", b"GIF89a", "image/gif")}).text
        finally:
            app.state.model_client = app.state.storage = app.state.extract_rate_limiter = None
    assert model.images == [photo] and storage.writes == []
    assert "Added 1 lines from your receipt photo as purchases on 2026-10-22." in page
    assert "<li>Banana ambul x 1</li>" in page
    assert "Left out (1, not regular items):" in page and "4111111111111111" not in page and "<li>VISA ####</li>" in page
    assert "BANANA - AMBUL" in html.unescape(re.search(r'name="receipt_json" value="([^"]*)"', page).group(1))
    assert "Upload a JPEG or PNG photo." in wrong
    with TestClient(app) as http:
        sample = _submit(http, http.get("/").text, "sample")
    assert "Added 6 lines from the sample receipt" in sample and "<ul><li>" in sample


SUGGEST_CASE = [("today", "2026-10-22"), ("pantry_set", "1"), ("wallet_set", "1"), ("bank", "Commercial Bank"), ("max_stores", "1"),
                ("usual_store", "keells"), ("day", "2026-10-24"), ("sku", "flora_500g"), ("sku", "bread_450g"),
                ("qty_flora_500g", "3"), ("qty_bread_450g", "4")]


def test_offer_minimum_suggestions_use_only_items_due_soon():
    form: dict[str, list[str]] = {}
    for key, value in SUGGEST_CASE:
        form.setdefault(key, []).append(value)
    state = _parse_state(form)
    items = {i["sku_id"]: i for i in _pantry_view(state)}
    allowed = {i["name"]: i for i in items.values()
               if not i["checked"] and i.get("next_due") and i["next_due"] <= "2026-11-05" and i["display_status"] != "stale"}
    with TestClient(app) as http:
        page = http.post("/ui", content=urlencode([("action", "plan")] + SUGGEST_CASE), headers=FORM).text
        refused = _submit(http, http.get("/").text, "refused")
    blocks = re.findall(r'<div class="suggestion">(.*?)</div>', page, re.S)
    assert blocks, "Commercial Bank at Keells on Saturday misses its minimum by less than the shopper's soon-due items"
    for block in blocks:
        text = html.unescape(re.sub(r"<[^>]+>", "", block))
        assert "Only if you need these soon. Savvy Cart does not add them." in text
        names = re.search(r"adding (.+?) \(LKR", text).group(1).split(", ")
        assert names and set(names) <= set(allowed)  # not in the basket, due within 14 days of 22 Oct
        replanned = int(re.search(r"plan with them is LKR ([\d,]+)", text).group(1).replace(",", ""))
        lines = [{"sku_id": "flora_500g", "qty": 3.0}, {"sku_id": "bread_450g", "qty": 4.0}]
        lines += [{"sku_id": allowed[n]["sku_id"], "qty": allowed[n]["qty"]} for n in names]
        engine = engine_plan_day(_v2_catalog(), _v2_offers(), lines, "2026-10-24", ["Commercial Bank"], 1, 250, "keells", _with_baselines=False)
        assert replanned == engine["effective_cost_lkr"]
        assert engine["stores"][0]["card"] and engine["stores"][0]["card"]["bank"] == "Commercial Bank"  # the offer really fires
    # Never added: the basket the page carries forward is unchanged.
    assert set(re.findall(r'<input type="hidden" name="sku" value="([^"]+)">', page)) | set(
        re.findall(r'name="sku" value="([^"]+)" checked', page)) <= {"flora_500g", "bread_450g"}
    assert "suggests nothing" in refused  # the two-item control basket cannot honestly reach a minimum


def test_suggestions_never_claim_a_minimum_the_engine_does_not_reach():
    # Store promotions lower the promoted subtotal the minimum counts; shelf prices would wrongly reach it here.
    fields = [("action", "plan"), ("today", "2026-10-22"), ("pantry_set", "1"), ("wallet_set", "1"), ("bank", "Commercial Bank"),
              ("max_stores", "1"), ("usual_store", "keells"), ("day", "2026-10-24"), ("sku", "flora_500g"), ("sku", "bread_450g"),
              ("qty_flora_500g", "3"), ("qty_bread_450g", "4")]
    with TestClient(app) as http:
        page = http.post("/ui", content=urlencode(fields), headers=FORM).text
    assert "LKR 3,992" not in page
    for block in re.findall(r'<div class="suggestion">(.*?)</div>', page, re.S):
        text = html.unescape(re.sub(r"<[^>]+>", "", block))
        replanned = int(re.search(r"plan with them is LKR ([\d,]+)", text).group(1).replace(",", ""))
        assert replanned >= 4000 - 1250  # a fired Commercial Bank offer leaves the bill at or above minimum minus cap


def test_approve_offers_a_mock_delivery_quote():
    with TestClient(app) as http:
        home = http.get("/").text
        pickup = _submit(http, home, "approve")
        delivery = _submit(http, pickup, "approve", [("fulfilment", "delivery"), ("delivery_fee", "400")])
    assert "MOCK" in pickup and "No order is sent." in pickup and "Uber" not in pickup
    bills = re.findall(r"<li>(\w+): bill LKR ([\d,]+), delivery LKR 400 \(assumption\)</li>", delivery)
    assert bills and "No booking is made. Savvy Cart is not integrated with Uber, PickMe, or any store." in delivery
    total = int(re.search(r"Total with delivery: <strong>LKR ([\d,]+)</strong>", delivery).group(1).replace(",", ""))
    plan_total = int(re.search(r"Plan total (\d+) LKR", delivery).group(1))
    assert total == plan_total + 400 * len(bills)
    assert "MOCK" in delivery and "No order is sent." in delivery
