"""Guest page — judge controls and the sample plan path (no live model)."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from savvycart.http import DATA_LABEL, app

CONTROLS = [
    "Use sample receipt",
    "Extract this image",
    "Reject swap",
    "Approve plan",
    "Show a basket this offer refuses",
]

FORM_HEADERS = {"content-type": "application/x-www-form-urlencoded"}


class FakeModelClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise AssertionError("plans must not call the model")

    def extract(self, image_bytes: bytes, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        raise AssertionError("sample path must not call extract")

    def explain(self, plan_json: dict[str, Any], instruction: str) -> str:
        self.calls += 1
        raise AssertionError("sample plan path does not explain")


def _post_ui(http: TestClient, fields: list[tuple[str, str]]) -> str:
    response = http.post("/ui", content=urlencode(fields), headers=FORM_HEADERS)
    assert response.status_code == 200
    return response.text


def test_guest_page_has_judge_controls():
    with TestClient(app) as http:
        response = http.get("/")
    assert response.status_code == 200
    page = response.text
    assert DATA_LABEL in page
    for control in CONTROLS:
        assert f">{control}</button>" in page
    assert "Karuppan, Saturday, Commercial Bank credit, budget about LKR 12,000." in page
    assert re.search(r'name="staple" value="rice_5kg" checked', page)
    assert re.search(r'name="staple" value="milk_400g">', page)


def test_sample_plan_names_tools():
    client = FakeModelClient()
    app.state.model_client = client
    try:
        with TestClient(app) as http:
            page = _post_ui(http, [("action", "sample"), ("weekday", "saturday"), ("usual_store", "keells")])
    finally:
        app.state.model_client = None

    tools = re.search(r'<p id="tools">Tools run: ([^<]*)</p>', page)
    assert tools is not None
    assert tools.group(1) == "catalog, offers, optimizer"
    assert client.calls == 0
    assert "fixture lines for the sample path" in page
    assert "Swap applied" in page
    assert "<s>25% off</s>" in page


def test_reject_swap_restores_capped_basket_and_cap():
    with TestClient(app) as http:
        sample = _post_ui(http, [("action", "sample"), ("weekday", "saturday")])
        receipt_json = re.search(r'name="receipt_json" value="([^"]*)"', sample).group(1)
        fields = [
            ("action", "reject_swap"),
            ("weekday", "saturday"),
            ("usual_store", "keells"),
            ("swap", "applied"),
            ("receipt_json", html.unescape(receipt_json)),
            ("receipt_label", "fixture lines for the sample path"),
        ] + [("line", sku) for sku in ["rice_5kg", "chicken_1kg", "milk_400g", "vegetables"]]
        page = _post_ui(http, fields)
    assert "Swap rejected" in page
    assert "Keells Saturday: legal saving 1000 LKR" in page
    assert "Keells Thursday: legal saving 0 LKR" in page
    assert re.search(r"Cargills</td><td>\d+ LKR</td><td>0 LKR", page)
    assert re.search(r"Spar</td><td>\d+ LKR</td><td>0 LKR", page)


def _carry_state(page: str, action: str, weekday: str = "saturday") -> list[tuple[str, str]]:
    """Resubmit the form the way a browser would after the previous page."""
    receipt_json = html.unescape(re.search(r'name="receipt_json" value="([^"]*)"', page).group(1))
    swap = re.search(r'name="swap" value="([^"]*)"', page).group(1)
    lines = re.findall(r'name="line" value="([^"]*)" checked', page)
    staples = re.findall(r'name="staple" value="([^"]*)" checked', page)
    return (
        [
            ("action", action),
            ("weekday", weekday),
            ("usual_store", "keells"),
            ("swap", swap),
            ("receipt_json", receipt_json),
            ("receipt_label", "fixture lines for the sample path"),
        ]
        + [("line", sku) for sku in lines]
        + [("staple", sku) for sku in staples]
    )


def _option_row(page: str, state: str) -> str:
    row = re.search(rf'<tr class="option" data-option="{state}">(.*?)</tr>', page)
    assert row is not None, f"missing option row {state}"
    return row.group(1)


def test_options_compare_need_and_minimum():
    with TestClient(app) as http:
        sample = _post_ui(http, [("action", "sample"), ("weekday", "saturday"), ("staple", "rice_5kg"), ("staple", "chicken_1kg")])
        need = _option_row(sample, "applied")
        restore = _option_row(sample, "rejected")
        assert "Option A — buy what you need (selected)" in need
        assert "<td>9230 LKR</td><td>0 LKR</td>" in need
        assert "1000 LKR below the 8000 LKR offer minimum" in need
        assert "Option B — restore Chicken 1 kg</td>" in restore
        assert "<td>9730 LKR</td><td>1000 LKR</td>" in restore
        assert "Offer minimum met" in restore
        assert "Buying what you need costs 500 LKR less than restoring the original item." in sample
        assert "never adds items" in sample

        rejected = _post_ui(http, _carry_state(sample, "reject_swap"))
        assert "(selected)" in _option_row(rejected, "rejected")
        assert "(selected)" not in _option_row(rejected, "applied")
        assert '>Keep swap</button>' in rejected and 'value="keep_swap">' in rejected

        kept = _post_ui(http, _carry_state(rejected, "keep_swap"))
        assert "(selected)" in _option_row(kept, "applied")
        assert "Swap applied" in kept


def test_refused_basket_and_mock_approve():
    with TestClient(app) as http:
        refused = _post_ui(http, [("action", "refused"), ("weekday", "saturday")])
        approved = _post_ui(http, [("action", "approve"), ("weekday", "saturday"), ("staple", "rice_5kg")])
    assert re.search(r"Keells \(winner\)</td><td>\d+ LKR</td><td>0 LKR|Keells</td><td>\d+ LKR</td><td>0 LKR", refused)
    assert "MOCK" in approved
    assert "No order is sent." in approved
