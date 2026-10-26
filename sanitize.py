"""Layer 1 (code): turn a vendor document into the text a person would actually see.

Removed before anything reaches the model, and logged:
  HTML   hidden CSS (display:none, visibility:hidden, opacity:0, font-size <= 2px, white text),
         the hidden attribute, HTML comments, <script>/<style>/<noscript>/<template>
  PDF    text drawn white, invisible (render mode 3), smaller than 4 pt, or outside the page
  Email  for HTML mail, only the visible text of the HTML part (what a mail client shows);
         the plain-text alternative is not used when an HTML part exists
  All    zero-width and bidi control characters, fake <vendor_document> tags, overlong text

Legitimate visible content (vendor, SKU, prices, lead times, minimums) passes through unchanged.
"""

from __future__ import annotations

import email
import re
import time
from dataclasses import dataclass, field
from email import policy
from html.parser import HTMLParser
from pathlib import Path

from pypdf import PdfReader

from tools import resolve_doc

INVISIBLE_CHARS = re.compile(r"[​-‏‪-‮⁠-⁤⁦-⁩﻿­]")
MAX_CHARS = 8000
CODE_TAGS = {"script", "style", "noscript", "template"}
VOID = {"br", "img", "hr", "meta", "link", "input", "wbr", "col", "area", "base", "source"}
BLOCK = {"br", "p", "tr", "div", "h1", "h2", "h3", "h4", "li", "footer", "header", "table", "section"}
MIN_PDF_FONT = 4.0


@dataclass
class CleanDoc:
    text: str
    removed: list[dict] = field(default_factory=list)  # {"technique", "text"}
    seconds: float = 0.0


# ---------- HTML ----------

def hidden_style(style: str) -> str | None:
    s = style.replace(" ", "").lower()
    if "display:none" in s:
        return "CSS display:none"
    if "visibility:hidden" in s or "visibility:collapse" in s:
        return "CSS visibility:hidden"
    if re.search(r"(^|;)opacity:0*(\.0+)?(;|$)", s):
        return "CSS opacity:0"
    m = re.search(r"font-size:([\d.]+)(px|pt)?(;|$)", s)
    if m and float(m.group(1)) <= 2:
        return f"CSS font-size:{m.group(1)}{m.group(2) or ''}"
    if re.search(r"(^|;)color:(#fff(fff)?|white|rgba?\(255,255,255)", s):
        return "white text"
    if re.search(r"(^|;)(height|width|max-height):0(px)?(;|$)", s) and "overflow:hidden" in s:
        return "zero-size box"
    if re.search(r"(left|top|text-indent):-\d{3,}", s):
        return "moved off screen"
    return None


class _VisibleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str | None] = []
        self.out: list[str] = []
        self.removed: list[dict] = []
        self._hidden_buf: list[str] = []

    def _hiding(self) -> str | None:
        return next((h for h in reversed(self.stack) if h), None)

    def handle_starttag(self, tag, attrs):
        if tag in BLOCK:
            self.out.append("\n")
        if tag in VOID:
            return
        a = dict(attrs)
        how = hidden_style(a.get("style") or "")
        if "hidden" in a:
            how = "hidden attribute"
        if tag in CODE_TAGS:
            how = f"<{tag}> element"
        self.stack.append(how)

    def handle_endtag(self, tag):
        if tag in VOID or not self.stack:
            return
        how = self.stack.pop()
        if how and not self._hiding():
            text = " ".join("".join(self._hidden_buf).split())
            self._hidden_buf = []
            if text and how != "<style> element":  # stylesheets are layout code, not worth logging
                self.removed.append({"technique": how, "text": text})
        if tag in ("td", "th"):
            self.out.append(" ")

    def handle_data(self, data):
        (self._hidden_buf if self._hiding() else self.out).append(data)

    def handle_comment(self, data):
        if data.strip():
            self.removed.append({"technique": "HTML comment", "text": " ".join(data.split())})


def clean_html(html: str) -> tuple[str, list[dict]]:
    p = _VisibleHTML()
    p.feed(html)
    p.close()
    lines = (" ".join(line.split()) for line in "".join(p.out).splitlines())
    return "\n".join(line for line in lines if line), p.removed


# ---------- PDF ----------

def clean_pdf(path: Path) -> tuple[str, list[dict]]:
    visible: list[str] = []
    removed: list[dict] = []
    for page in PdfReader(path).pages:
        box = page.mediabox
        x0, y0, x1, y1 = float(box.left), float(box.bottom), float(box.right), float(box.top)
        gs = {"fill": (0.0, 0.0, 0.0), "mode": 0}
        stack: list[dict] = []

        def before(op, args, cm, tm):
            if op == b"q":
                stack.append(dict(gs))
            elif op == b"Q" and stack:
                gs.update(stack.pop())
            elif op == b"rg" and len(args) == 3:
                gs["fill"] = tuple(float(a) for a in args)
            elif op == b"g" and len(args) == 1:
                gs["fill"] = (float(args[0]),) * 3
            elif op == b"k" and len(args) == 4:
                c, m, y, k = (float(a) for a in args)
                gs["fill"] = tuple((1 - min(1.0, v + k)) for v in (c, m, y))
            elif op == b"Tr" and args:
                gs["mode"] = int(args[0])

        def on_text(text, cm, tm, font, size):
            if not text.strip():
                return
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            scale = (abs(tm[3] * cm[3]) or 1.0)
            eff = float(size) * scale
            why = []
            if all(c >= 0.95 for c in gs["fill"]):
                why.append("white text")
            if gs["mode"] == 3:
                why.append("invisible render mode")
            if eff < MIN_PDF_FONT:
                why.append(f"{eff:g} pt text")
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                why.append(f"off the page at ({x:g}, {y:g})")
            if why:
                how = "PDF " + ", ".join(why)
                if removed and removed[-1]["technique"] == how:
                    removed[-1]["text"] += " " + " ".join(text.split())
                else:
                    removed.append({"technique": how, "text": " ".join(text.split())})
            else:
                visible.append(text)

        page.extract_text(visitor_operand_before=before, visitor_text=on_text)
    lines = (" ".join(line.split()) for line in "".join(visible).splitlines())
    return "\n".join(line for line in lines if line), removed


# ---------- email ----------

def clean_eml(path: Path) -> tuple[str, list[dict]]:
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    header = "\n".join(f"{h}: {msg[h]}" for h in ("From", "To", "Subject", "Date") if msg[h])
    plain = html = None
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain" and plain is None:
            plain = part.get_content()
        elif ctype == "text/html" and html is None:
            html = part.get_content()
    removed: list[dict] = []
    if html is not None:
        body, hidden = clean_html(html)
        removed += [{"technique": "email HTML part: " + h["technique"], "text": h["text"]} for h in hidden]
        if plain is not None and " ".join(plain.split()) != " ".join(body.split()):
            removed.append({"technique": "email plain-text alternative (not what the client shows)",
                            "text": "(ignored; the visible HTML part was used instead)"})
    else:
        body = (plain or "").strip()
    return header + "\n\n" + body, removed


# ---------- entry point ----------

def finalize(text: str, removed: list[dict]) -> str:
    n_invisible = len(INVISIBLE_CHARS.findall(text))
    if n_invisible:
        removed.append({"technique": "zero-width / control characters", "text": f"{n_invisible} characters"})
        text = INVISIBLE_CHARS.sub("", text)
    for r in removed:
        r["text"] = INVISIBLE_CHARS.sub("", r["text"])
    if re.search(r"</?\s*vendor_document", text, re.I):
        removed.append({"technique": "fake <vendor_document> delimiter", "text": "neutralised"})
        text = re.sub(r"<(/?)\s*vendor_document", r"[\1vendor_document", text, flags=re.I)
    if len(text) > MAX_CHARS:
        removed.append({"technique": "length cap", "text": f"{len(text) - MAX_CHARS} characters cut"})
        text = text[:MAX_CHARS]
    return text


def clean_document(path: str) -> CleanDoc:
    """Visible text of an .html, .pdf, or .eml vendor document inside data/, plus what was removed."""
    started = time.perf_counter()
    p = resolve_doc(path)
    suffix = p.suffix.lower()
    if suffix in (".html", ".htm"):
        text, removed = clean_html(p.read_text(encoding="utf-8"))
    elif suffix == ".pdf":
        text, removed = clean_pdf(p)
    elif suffix == ".eml":
        text, removed = clean_eml(p)
    else:
        raise ValueError(f"Unsupported document type: {suffix}")
    text = finalize(text, removed)
    return CleanDoc(text=text, removed=removed, seconds=time.perf_counter() - started)


def read_document_clean(path: str) -> str:
    """Read a vendor document (.html, .pdf, or .eml) from the data/ folder and return its visible text.

    Args:
        path: Path to the document, e.g. data/practice_docs/p01_bluehen_quote.html
    """
    return clean_document(path).text
