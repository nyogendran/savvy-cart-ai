"""Check README.md carries the judge path strings required by SC-008."""

from __future__ import annotations

import re
import sys
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"

REQUIRED = [
    "Use sample receipt",
    "Sample catalog — not live shelf prices.",
    "Why isn’t rice discounted?",
    "Show a basket this offer refuses",
    "No order is sent.",
    "Cloud Run",
    "Secret Manager",
    "Karuppan, Saturday, Commercial Bank credit, budget about LKR 12,000.",
    "tens of seconds",
]
CANNOT_DO_TOPICS = ["live prices", "live stock", "real orders", "card numbers", "bank affiliation"]


def problems(text: str) -> list[str]:
    found = [f"missing required string: {s!r}" for s in REQUIRED if s not in text]
    lines = text.splitlines()
    if "## Cannot do" not in lines:
        found.append("missing heading line exactly: '## Cannot do'")
    else:
        start = lines.index("## Cannot do") + 1
        end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
        section = "\n".join(lines[start:end]).lower()
        found += [f"Cannot do section does not mention {t!r}" for t in CANNOT_DO_TOPICS if t not in section]
    if re.search(r"AIza[0-9A-Za-z_\-]{20,}", text):
        found.append("README contains something shaped like a Google API key")
    return found


def main() -> int:
    issues = problems(README.read_text(encoding="utf-8"))
    for issue in issues:
        print(issue, file=sys.stderr)
    if not issues:
        print("README judge path: ok")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
