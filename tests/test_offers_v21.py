"""Published bank offers cite their source and match their own headline (SC-019 AC8)."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

OFFERS = Path(__file__).resolve().parents[1] / "fixtures" / "v2" / "offers.json"
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], start=1)}
STORE_WORDS = {"keells": "keells", "cargills": "cargills", "glomark": "glomark", "spar": "spar"}


def _valid_to(headline: str) -> date:
    day, month, year = re.search(r"till (\d{1,2})(?:st|nd|rd|th)? (\w+) (\d{4})", headline).groups()
    return date(int(year), MONTHS[month.lower()], int(day))


def test_bank_offers_cite_their_source():
    offers = json.loads(OFFERS.read_text(encoding="utf-8"))["card_offers"]
    published = [o for o in offers if o["bank"] in ("Nations Trust Bank", "Commercial Bank")]
    assert len(published) == 6
    for offer in published:
        assert offer["source"] == "published" and offer["captured_on"] == "2026-10-18"
        assert offer["source_url"] in ("https://www.nationstrust.com/promotions", "https://www.combank.lk/rewards-promotions")
        assert offer["terms_source"] == "assumption"
        headline = offer["headline"].lower()
        # Store, weekday, rate, and end date all come out of the captured headline sentence.
        assert STORE_WORDS[offer["store_id"]] in headline
        (weekday,) = offer["days"]
        assert weekday in headline
        assert f"{offer['rate_bps'] // 100}%" in headline
        assert _valid_to(offer["headline"]).isoformat() == offer["valid_to"]
    for offer in offers:
        if offer["bank"] == "HNB":
            assert offer["source"] == "fictional" and "source_url" not in offer
