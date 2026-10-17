"""Check the Dockerfile and docs/deploy.md carry the Cloud Run settings required by SC-009."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
DEPLOY_DOC = ROOT / "docs" / "deploy.md"

DOCKERFILE_REQUIRED = ["python:3.12-slim", "uvicorn savvycart.http:app", "0.0.0.0", "8080"]
# The app resolves fixtures/ relative to src/; without both steps the guest page cannot load data.
DOCKERFILE_LAYOUT = [
    re.compile(r"^\s*COPY\s+src\s+\./src\s*$", re.MULTILINE),
    re.compile(r"^\s*COPY\s+fixtures\s+\./fixtures\s*$", re.MULTILINE),
    re.compile(r"pip install -e \."),
    re.compile(r"^\s*USER\s+(?!root\b)\S+", re.MULTILINE),
]
DEPLOY_REQUIRED = [
    "savvy-cart",
    "asia-southeast1",
    "--min-instances=0",
    "--timeout=120",
    "--allow-unauthenticated",
    "8080",
    "Secret Manager",
    "GEMINI_MODEL",
]
SECRET_SHAPES = [
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"^\s*ENV\s+[^\n]*(API_KEY|SECRET|TOKEN)", re.MULTILINE),
]


def problems(dockerfile: str, deploy_doc: str) -> list[str]:
    found = [f"Dockerfile missing {s!r}" for s in DOCKERFILE_REQUIRED if s not in dockerfile]
    found += [f"Dockerfile missing layout step ({p.pattern})" for p in DOCKERFILE_LAYOUT if not p.search(dockerfile)]
    found += [f"docs/deploy.md missing {s!r}" for s in DEPLOY_REQUIRED if s not in deploy_doc]
    for name, text in (("Dockerfile", dockerfile), ("docs/deploy.md", deploy_doc)):
        found += [f"{name} contains a secret-shaped value ({p.pattern})" for p in SECRET_SHAPES if p.search(text)]
    return found


def main() -> int:
    issues = problems(DOCKERFILE.read_text(encoding="utf-8"), DEPLOY_DOC.read_text(encoding="utf-8"))
    for issue in issues:
        print(issue, file=sys.stderr)
    if not issues:
        print("deploy docs: ok")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
