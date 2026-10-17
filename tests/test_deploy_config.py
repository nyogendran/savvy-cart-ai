"""Model configuration rules for the Agent Platform deploy, without a live client."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from savvycart.http import _model_configured

ROOT = Path(__file__).resolve().parents[1]


def _live_script():
    spec = importlib.util.spec_from_file_location("extract_receipt_live", ROOT / "scripts/extract_receipt_live.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("env", "configured"),
    [
        ({"GEMINI_MODEL": "m", "GOOGLE_GENAI_USE_ENTERPRISE": "true"}, True),
        ({"GEMINI_MODEL": "m", "GOOGLE_GENAI_USE_ENTERPRISE": "TRUE"}, True),
        ({"GEMINI_MODEL": "m", "GOOGLE_GENAI_USE_VERTEXAI": "true"}, True),
        ({"GEMINI_MODEL": "m", "GEMINI_API_KEY": "k"}, True),
        ({"GOOGLE_GENAI_USE_ENTERPRISE": "true"}, False),
        ({"GEMINI_MODEL": "m", "GOOGLE_GENAI_USE_ENTERPRISE": "false"}, False),
        ({"GEMINI_MODEL": "m"}, False),
    ],
)
def test_enterprise_flag_configures_the_model(monkeypatch, env, configured):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert _model_configured() is configured


def test_live_script_accepts_enterprise_flag(monkeypatch):
    script = _live_script()
    assert script.missing_credentials()[0] == "GEMINI_MODEL"
    assert any("GOOGLE_GENAI_USE_ENTERPRISE" in m for m in script.missing_credentials())
    monkeypatch.setenv("GEMINI_MODEL", "m")
    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "true")
    assert script.missing_credentials() == []


def test_suite_hides_enterprise_settings():
    for name in ("GOOGLE_GENAI_USE_ENTERPRISE", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"):
        assert name not in os.environ
