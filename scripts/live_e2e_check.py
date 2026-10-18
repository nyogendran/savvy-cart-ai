"""Run the guest journey against a deployed Savvy Cart URL and print each step's timing and checks (SC-032 AC6).

Usage: python scripts/live_e2e_check.py https://<service-url>
Exit code 1 when a check fails. Uses the live model, so it costs a few Gemini calls.
"""

from __future__ import annotations

import html
import re
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urlencode

import httpx

SMS = ("Save 25% at Keells on Fresh Meat, Fruits & Vegetables with Mastercard Credit Cards every Sunday till 31 Oct, "
       "for bills above LKR 5,000 & max savings LKR 1,500. T&C Apply.")


class _Form(HTMLParser):
    """What a browser would submit: hidden fields, checked boxes, typed values, selected options."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: list[tuple[str, str]] = []
        self._select: str | None = None
        self._first: str | None = None
        self._chosen = False
        self._textarea: str | None = None
        self._text = ""

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
            self._select, self._first, self._chosen = a.get("name"), None, False
        elif tag == "option" and self._select:
            if self._first is None:
                self._first = a.get("value", "")
            if "selected" in a:
                self.fields.append((self._select, a.get("value", "")))
                self._chosen = True
        elif tag == "textarea" and a.get("name"):
            self._textarea, self._text = a["name"], ""

    def handle_data(self, data):
        if self._textarea:
            self._text += data

    def handle_endtag(self, tag):
        if tag == "select" and self._select:
            if not self._chosen and self._first is not None:
                self.fields.append((self._select, self._first))
            self._select = None
        elif tag == "textarea" and self._textarea:
            self.fields.append((self._textarea, html.unescape(self._text)))
            self._textarea = None


def _text(page: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def main(url: str) -> int:
    failures: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(f"    {'ok  ' if ok else 'FAIL'} {what}")
        if not ok:
            failures.append(what)

    with httpx.Client(timeout=130) as client:
        def post(page: str, action: str, changes: tuple[tuple[str, str], ...] = ()) -> tuple[str, float]:
            parser = _Form()
            parser.feed(page)
            changed = {k for k, _ in changes}
            fields = [(k, v) for k, v in parser.fields if k not in changed] + list(changes)
            start = time.time()
            response = client.post(url.rstrip("/") + "/ui", content=urlencode([("action", action)] + fields),
                                   headers={"content-type": "application/x-www-form-urlencoded"})
            seconds = time.time() - start
            print(f"{action:12s} {response.status_code} {seconds:6.1f}s")
            check(response.status_code == 200, f"{action} returns 200")
            return response.text, seconds

        start = time.time()
        home = client.get(url).text
        print(f"{'GET /':12s} {time.time() - start:6.1f}s")
        offer, _ = post(home, "offer")
        read, _ = post(offer, "offer_read", (("o_text", SMS),))
        text = _text(read)
        check("Not covered" in text, "SMS: items outside fresh produce are not covered")
        check(bool(re.search(r"This offer pays LKR [\d,]+, not LKR [\d,]+: \d+ of your \d+ items do not count", text)), "SMS: payout counts only covered items")
        check("card network" in text, "SMS: Mastercard is named as a card network")
        plan, _ = post(read, "plan")
        why, seconds = post(plan, "why")
        check(seconds < 2, "Next: explain this plan opens in under 2 s")
        check("Engine explanation" in why, "Why opens with the engine explanation")
        asked, seconds = post(why, "explain", (("question", "Would one store be enough if I drop the extra trip?"),))
        check(seconds < 100 and "Answer from the ADK agent" in asked, "Ask returns the agent's answer within 100 s")
        approve, _ = post(asked, "approve")
        check('<article class="cart"' in approve and "No order is sent." in approve, "Approve shows the MOCK cart")
    print("PASS" if not failures else f"FAILED: {len(failures)} check(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
