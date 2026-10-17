"""Build a de-identified purchase history from local Keells e-bill PDFs.

Reads samples/purchase-history/*.pdf (git-ignored, never committed) and writes
samples/purchase-history.json. Only whitelisted fields are written. The build
fails if a bill does not add up, or if any value from a bill header appears in
the output.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "samples" / "purchase-history"
OUTPUT = ROOT / "samples" / "purchase-history.json"

ITEM = re.compile(r"^(\d{1,2}) (\d+) (.+?) (\d+\.\d{1,3}) ([\d,]+\.\d{2}) ([\d,]+\.\d{2})")
# Percent discounts ("10.00% Dis") and fixed-value discounts ("Value Dis", recorded with rate_bps 0).
DISCOUNT = re.compile(r"^(\d{1,2}) \S+ (?:([\d.]+)% |Value )Dis Rs: ([\d,]+\.\d{2})")
# Wrapped product text is printed in capitals and contains a letter; names, links,
# notes, and the loyalty-points figures printed beside items are not product text.
CONTINUATION = re.compile(r"^(?=.*[A-Z])[A-Z0-9][A-Z0-9 &+/().,'%-]{0,39}$")
# Bill-level bank card offer, e.g. "NTB | 25% off on Fresh Rs: 709.00".
CARD_OFFER = re.compile(r"^([A-Za-z][A-Za-z ]*?) \| (\d+(?:\.\d+)?)% off on (.+?) Rs: ([\d,]+\.\d{2})$")
# Gmail reprints its page header (sender, link, timestamp) at page breaks, even mid-section.
PAGE_NOISE = re.compile(r"https?://|@|Gmail|^\d{1,2}/\d{1,2}/\d{2},")
HEADER_FIELDS = ("Bill No", "Nexus No", "Cashier ID", "Store Mobile", "Store Address", "Billed Store")


def lkr(value: str) -> int:
    return int(Decimal(value.replace(",", "")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def header_tokens(lines: list[str]) -> set[str]:
    """Values that identify the shopper, the bill, or the branch."""
    tokens: set[str] = set()
    for line in lines:
        for field in HEADER_FIELDS:
            if line.startswith(field):
                value = line.split(":", 1)[-1].strip()
                tokens.update(part.strip() for part in re.split(r"[|,]", value) if len(part.strip()) >= 4)
        tokens.update(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", line))
        tokens.update(re.findall(r"\b\d{6,}\b", line))
    if lines:
        sender = re.match(r"^(.+?) <", lines[1] if len(lines) > 1 else "")
        if sender:
            tokens.update(part for part in sender.group(1).split() if len(part) >= 3)
    return tokens


def parse_bill(text: str) -> tuple[dict, set[str]]:
    lines = text.splitlines()
    date = next(datetime.strptime(l.split(":", 1)[1].strip(), "%d-%b-%Y") for l in lines if l.startswith("Bill Date"))
    items: list[dict] = []
    promotions: list[dict] = []
    card_offers: list[dict] = []
    label = None
    section = "header"
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# Item Description"):
            section = "items"
            continue
        if stripped == "Discounts":
            section = "discounts"
            continue
        if stripped.startswith("Total Gross"):
            section = "totals"
        if section == "items":
            match = ITEM.match(stripped)
            if match:
                items.append(
                    {
                        "line": int(match[1]),
                        "raw": match[3].strip(),
                        "qty": float(match[4]),
                        "unit_lkr": lkr(match[5]),
                        "amount_raw": Decimal(match[6].replace(",", "")),
                    }
                )
            elif items and CONTINUATION.match(stripped):
                items[-1]["raw"] = f'{items[-1]["raw"]} {stripped}'
        elif section == "discounts":
            if PAGE_NOISE.search(stripped):
                continue
            if card_offers and re.search(r"(?:&|\band|\bfor)$", card_offers[-1]["category"]) and stripped:
                card_offers[-1]["category"] = f'{card_offers[-1]["category"]} {stripped.lower()}'
                continue
            card = CARD_OFFER.match(stripped)
            if card:
                card_offers.append(
                    {
                        "bank": card[1].strip(),
                        "rate_bps": int(Decimal(card[2]) * 100),
                        "category": card[3].strip().lower(),
                        "amount_lkr": lkr(card[4]),
                    }
                )
                continue
            match = DISCOUNT.match(stripped)
            if match:
                promotions.append(
                    {
                        "label": label or "Promotion",
                        "line": int(match[1]),
                        "rate_bps": int(Decimal(match[2]) * 100) if match[2] else 0,
                        "amount_lkr": lkr(match[3]),
                    }
                )
            elif stripped and re.match(r"^[A-Za-z]", stripped) and not stripped.startswith("Total"):
                label = "Green Discount" if "Green Discount" in stripped else stripped
    gross = next(Decimal(l.split()[-1].replace(",", "")) for l in lines if l.startswith("Total Gross Amount"))
    net = next(Decimal(l.split()[-1].replace(",", "")) for l in lines if l.startswith("Total Net Amount"))
    parsed = sum((i["amount_raw"] for i in items), Decimal("0"))
    if abs(parsed - gross) > Decimal("0.05"):
        raise ValueError(f"bill {date:%Y-%m-%d}: parsed lines sum to {parsed}, gross is {gross}")
    discounted = sum((Decimal(p["amount_lkr"]) for p in promotions + card_offers), Decimal("0"))
    if abs(gross - discounted - net) > len(promotions) + len(card_offers) + 1:
        raise ValueError(f"bill {date:%Y-%m-%d}: gross {gross} minus parsed promotions {discounted} is not net {net}")
    bill = {
        "date": date.strftime("%Y-%m-%d"),
        "chain": "keells",
        "source": "receipt",
        "lines": [
            {"line": i["line"], "raw": i["raw"], "qty": i["qty"], "unit_lkr": i["unit_lkr"], "amount_lkr": lkr(str(i["amount_raw"]))}
            for i in items
        ],
        "promotions": promotions,
        "card_offers": card_offers,
        "gross_lkr": lkr(str(gross)),
        "net_lkr": lkr(str(net)),
    }
    return bill, header_tokens(lines)


def main() -> int:
    pdfs = sorted(SOURCE_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"no PDFs in {SOURCE_DIR}", file=sys.stderr)
        return 2
    bills, tokens = [], set()
    for pdf_path in pdfs:
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        bill, bill_tokens = parse_bill(text)
        bills.append(bill)
        tokens |= bill_tokens
    bills.sort(key=lambda b: (b["date"], b["gross_lkr"]))
    document = {
        "note": "De-identified from one shopper's Keells e-bills with their consent. Names, contact details, branch, bill, cashier, loyalty and card numbers removed.",
        "bills": bills,
    }
    output = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    folded = output.casefold()
    leaked = sorted(t for t in tokens if t.casefold() in folded)
    if leaked:
        print(f"refusing to write: {len(leaked)} header value(s) would appear in the output", file=sys.stderr)
        return 1
    OUTPUT.write_text(output, encoding="utf-8")
    print(f"wrote {len(bills)} bills, {sum(len(b['lines']) for b in bills)} lines to {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
