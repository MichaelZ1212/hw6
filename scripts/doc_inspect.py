"""Problem 5 helper: what a human sees vs. what the agent reads.

For each vendor document this finds text segments a person would NOT see in a browser, PDF viewer,
or email client (hidden CSS, HTML comments, white or tiny PDF text, text placed off the page,
email HTML parts that differ from the plain-text part) and checks whether that hidden text is
passed to the agent by tools.read_document.

This file only inspects. It does not change the agent.
"""

from __future__ import annotations

import email
import re
import sys
from email import policy
from html.parser import HTMLParser
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import read_document  # noqa: E402

ZERO_WIDTH = re.compile(r"[​‌‍⁠﻿]")
VOID = {"br", "img", "hr", "meta", "link", "input", "wbr"}
BLOCK = {"br", "p", "tr", "div", "h1", "h2", "h3", "li", "footer", "header", "table"}


def norm(text: str) -> str:
    return " ".join(ZERO_WIDTH.sub("", text).split()).lower()


def hidden_style(style: str) -> str | None:
    """Return the hiding technique used by an inline style, or None if it looks visible."""
    s = style.replace(" ", "").lower()
    if "display:none" in s:
        return "CSS display:none"
    if "visibility:hidden" in s:
        return "CSS visibility:hidden"
    if re.search(r"opacity:0(\.0*)?(;|$)", s):
        return "CSS opacity:0"
    m = re.search(r"font-size:([\d.]+)(px|pt|em|rem)?", s)
    if m and float(m.group(1)) <= 2 and (m.group(2) or "px") in ("px", "pt"):
        return f"CSS font-size:{m.group(1)}{m.group(2) or ''} (too small to see)"
    if re.search(r"(?<!background-)color:(#fff(fff)?|white|rgb\(255,255,255\))", s):
        return "white text on white background"
    return None


class _HtmlInspector(HTMLParser):
    """Splits an HTML page into visible text and hidden segments."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str | None] = []  # hiding technique per open element (None = visible)
        self.visible: list[str] = []
        self.hidden: list[dict] = []
        self._buf: dict[str, list[str]] = {}

    def _hiding(self) -> str | None:
        return next((h for h in reversed(self.stack) if h), None)

    def handle_starttag(self, tag, attrs):
        if tag in BLOCK:
            self.visible.append("\n")
        if tag in VOID:
            return
        how = hidden_style(dict(attrs).get("style") or "")
        if tag in ("script", "style"):
            how = f"<{tag}> element (code, not shown)"
        self.stack.append(how)

    def handle_endtag(self, tag):
        if tag in VOID or not self.stack:
            return
        how = self.stack.pop()
        if how and how in self._buf and how not in (h for h in self.stack if h):
            text = " ".join("".join(self._buf.pop(how)).split())
            if not how.startswith("<"):  # <script>/<style> hold code, not hidden prose
                self.hidden.append({"technique": how, "text": text})
        if tag in ("td", "th"):
            self.visible.append(" ")

    def handle_data(self, data):
        how = self._hiding()
        if how:
            self._buf.setdefault(how, []).append(data)
        else:
            self.visible.append(data)

    def handle_comment(self, data):
        self.hidden.append({"technique": "HTML comment <!-- -->", "text": " ".join(data.split())})


def inspect_html(html: str) -> tuple[str, list[dict]]:
    p = _HtmlInspector()
    p.feed(html)
    lines = (" ".join(line.split()) for line in "".join(p.visible).splitlines())
    return "\n".join(line for line in lines if line), [h for h in p.hidden if h["text"]]


def inspect_pdf(path: Path) -> tuple[str, list[dict]]:
    """Walk a simple (ReportLab-style) content stream and flag text drawn white, tiny, or off the page."""
    page = PdfReader(path).pages[0]
    w, h = float(page.mediabox.width), float(page.mediabox.height)
    stream = page.get_contents().get_data().decode("latin-1")
    color, size, last_hidden = (0.0, 0.0, 0.0), 12.0, False
    visible, hidden = [], []
    for line in stream.splitlines():
        if m := re.search(r"([\d.]+) ([\d.]+) ([\d.]+) rg", line):
            color = tuple(float(x) for x in m.groups())
        if m := re.search(r"/F\d+ ([\d.]+) Tf", line):
            size = float(m.group(1))
        for x, y, raw in re.findall(r"1 0 0 1 ([-\d.]+) ([-\d.]+) Tm \((.*?)(?<!\\)\) Tj", line):
            text = raw.replace("\\(", "(").replace("\\)", ")")
            x, y = float(x), float(y)
            reasons = []
            if color == (1.0, 1.0, 1.0):
                reasons.append("white text on white page")
            if size < 4:
                reasons.append(f"font size {size:g} pt (too small to read)")
            if not (0 <= x <= w and 0 <= y <= h):
                reasons.append(f"placed off the page at ({x:g}, {y:g})")
            how = "; ".join(reasons)
            if reasons and last_hidden and hidden[-1]["technique"] == how:
                hidden[-1]["text"] += " " + text  # one hidden sentence split over several lines
            elif reasons:
                hidden.append({"technique": how, "text": text})
            else:
                visible.append(text)
            last_hidden = bool(reasons)
    return "\n".join(visible), hidden


def inspect_eml(path: Path) -> tuple[str, list[dict]]:
    """An email client shows the HTML part of multipart/alternative mail (plain text otherwise)."""
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    plain = html = None
    for part in msg.walk():
        if part.get_content_type() == "text/plain" and plain is None:
            plain = part.get_content()
        elif part.get_content_type() == "text/html" and html is None:
            html = part.get_content()
    if html is None:
        return (plain or "").strip(), []
    visible, hidden = inspect_html(html)
    for hseg in hidden:
        if ZERO_WIDTH.search(hseg["text"]):
            hseg["technique"] += "; zero-width characters split the words"
        hseg["technique"] = "email HTML part: " + hseg["technique"]
    return visible, hidden


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

    for f in sorted((ROOT / "data" / "practice_docs").iterdir()):
        r = inspect(f)
        print(f.name, json.dumps(r["hidden"], indent=1))
