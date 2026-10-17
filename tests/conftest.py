"""Keep every test away from live model credentials."""

from __future__ import annotations

import pytest

from savvycart.http import app

LIVE_MODEL_ENV = ("GEMINI_MODEL", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI")


@pytest.fixture(autouse=True)
def _no_live_model(monkeypatch: pytest.MonkeyPatch):
    for name in LIVE_MODEL_ENV:
        monkeypatch.delenv(name, raising=False)
    app.state.model_client = None
    yield
    app.state.model_client = None
