"""Problem 5 helper: what a human sees vs. what the agent reads.

For each vendor document this finds text segments a person would NOT see in a browser, PDF viewer,
or email client and checks whether that hidden text is passed to the agent by tools.read_document
(the raw reader the baseline agent uses). Detection reuses sanitize.py, the Layer 1 code, so the
inspection and the defense always agree on what counts as hidden.

This file only inspects. It does not change the agent.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sanitize  # noqa: E402
from tools import read_document  # noqa: E402

ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")


def norm(text: str) -> str:
    return " ".join(ZERO_WIDTH.sub("", text).split()).lower()


def _hidden(removed: list[dict]) -> list[dict]:
    """Hidden prose only: code blocks (<script>/<style>) and bookkeeping notes are not hidden content."""
    return [dict(r) for r in removed if not r["technique"].startswith("<") and not r["text"].startswith("(")]


def inspect_html(html: str) -> tuple[str, list[dict]]:
    visible, removed = sanitize.clean_html(html)
    return visible, _hidden(removed)


def inspect_pdf(path: Path) -> tuple[str, list[dict]]:
    visible, removed = sanitize.clean_pdf(path)
    return visible, _hidden(removed)


def inspect_eml(path: Path) -> tuple[str, list[dict]]:
    """An email client shows the HTML part of multipart/alternative mail (plain text otherwise)."""
    text, removed = sanitize.clean_eml(path)
    hidden = _hidden(removed)
    for h in hidden:
        if ZERO_WIDTH.search(h["text"]):
            h["technique"] += "; zero-width characters split the words"
    return text.split("\n\n", 1)[-1], hidden


def inspect(path: Path) -> dict:
    """Visible text, hidden segments, and whether each hidden segment reaches the agent."""
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm"):
        visible, hidden = inspect_html(path.read_text(encoding="utf-8"))
        where = "HTML page"
    elif suffix == ".pdf":
        visible, hidden = inspect_pdf(path)
        where = "PDF"
    else:
        visible, hidden = inspect_eml(path)
        where = "email"
    agent_text = read_document(str(path))
    agent_norm = norm(agent_text)
    for seg in hidden:
        seg["reaches_agent"] = norm(seg["text"])[:60] in agent_norm
        seg["looks_like_instruction"] = bool(re.search(
            r"approve_payment|send_email|replaces|correction|revised|now \$?\d|vendor of record|tracking link|"
            r"put this|send|ignore|instruction", ZERO_WIDTH.sub("", seg["text"]), re.I))
    return {"format": where, "visible_text": visible, "agent_text": agent_text, "hidden": hidden}


if __name__ == "__main__":
    import json

    for f in sorted(x for x in (ROOT / "data" / "practice_docs").iterdir() if x.suffix in (".html", ".pdf", ".eml")):
        r = inspect(f)
        print(f.name, json.dumps(r["hidden"], indent=1))
