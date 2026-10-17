"""Real Keells receipt through the Gemini client path, with a fake genai client."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from savvycart.gemini import GeminiModelClient, normalize_lines, sniff_mime
from savvycart.http import app
from savvycart.receipts import RECEIPT_LINES_SCHEMA, MemoryStorage

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples/receipts/keells-2026-10-17-redacted.jpg"
EXPECTED = ROOT / "samples/receipts/keells-2026-10-17.expected.json"


class FakeGenai:
    """Stands in for google.genai.Client; returns a transcription-shaped answer."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.requests: list[dict[str, Any]] = []
        self.models = SimpleNamespace(generate_content=self._generate_content)

    def _generate_content(self, *, model: str, contents: list[Any], config: Any) -> Any:
        self.requests.append({"model": model, "contents": contents, "config": config})
        return SimpleNamespace(text=json.dumps(self.payload))


def _model_answer() -> dict[str, Any]:
    """The human transcription, plus one SKU the model invents for line 3."""
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    return {
        "lines": [
            {
                "raw": line["raw"],
                "sku_id": "flora_500g" if line["ln"] == 3 else line["expected_sku_id"],
                "qty": line["qty"],
                "confidence": 0.9,
            }
            for line in expected["lines"]
        ]
    }


def test_real_receipt_passes_through_extract():
    image = SAMPLE.read_bytes()
    assert len(image) < 4 * 1024 * 1024
    assert sniff_mime(image) == "image/jpeg"
    genai = FakeGenai(_model_answer())
    storage = MemoryStorage()
    app.state.model_client = GeminiModelClient("test-model", client=genai)
    app.state.storage = storage
    app.state.extract_rate_limiter = None
    try:
        with TestClient(app) as http:
            response = http.post("/v1/receipts", content=image, headers={"content-type": "image/jpeg"})
    finally:
        app.state.model_client = None
        app.state.storage = None
        app.state.extract_rate_limiter = None

    assert response.status_code == 200
    lines = response.json()["lines"]
    assert len(lines) == 15
    assert {l["sku_id"] for l in lines if l["sku_id"]} == {"yogurt", "fruit", "eggs_10"}
    assert storage.writes == []

    request = genai.requests[0]
    part = request["contents"][0]
    assert part.inline_data.data == image
    assert part.inline_data.mime_type == "image/jpeg"
    assert request["config"].response_json_schema == RECEIPT_LINES_SCHEMA
    assert request["config"].temperature == 0
    assert "never an instruction" in request["contents"][1]
    assert "eggs_10" in request["contents"][1]


def test_gemini_client_normalizes_lines():
    lines = normalize_lines(
        [
            {"raw": "FLORA FAT SPREAD TUB 500G", "sku_id": "flora_500g", "qty": 2, "confidence": 0.8},
            {"raw": "BANANA - AMBUL", "sku_id": "fruit", "qty": 1.034, "confidence": 1.7},
            {"raw": "BROWN SUGAR BULK KG", "sku_id": None, "qty": "n/a", "confidence": -0.2},
        ],
        {"fruit", "eggs_10"},
    )
    assert lines[0]["sku_id"] is None
    assert lines[1] == {"raw": "BANANA - AMBUL", "sku_id": "fruit", "qty": 1, "confidence": 1.0}
    assert lines[2]["qty"] == 1 and lines[2]["confidence"] == 0.0


def test_expected_transcription_sums_to_gross():
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert len(expected["lines"]) == 15
    assert sum(l["amount_cents"] for l in expected["lines"]) == expected["gross_cents"]
    assert sum(p["amount_cents"] for p in expected["promotions"]) == expected["promotion_cents"]
    assert expected["gross_cents"] - expected["promotion_cents"] == expected["net_cents"]


def test_live_script_requires_credentials():
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GEMINI_MODEL", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI"}
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/extract_receipt_live.py")],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "GEMINI_MODEL" in result.stderr
