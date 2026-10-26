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
import math
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
    """Hiding technique used by a (combined) style string, or None. For each property the last value wins,
    as in CSS, so an inline style overrides a stylesheet rule."""
    s = style.replace(" ", "").lower()
    display, visibility, opacity = _css(s, "display"), _css(s, "visibility"), _css(s, "opacity")
    if display == "none":
        return "CSS display:none"
    if visibility in ("hidden", "collapse"):
        return "CSS visibility:hidden"
    if opacity is not None and re.fullmatch(r"0*(\.0+)?", opacity):
        return "CSS opacity:0"
    size = _css(s, "font-size")
    m = re.fullmatch(r"([\d.]+)(px|pt|em|rem|%)?", size or "")
    if m:
        unit = m.group(2) or "px"
        if float(m.group(1)) <= {"px": 2, "pt": 2, "em": 0.2, "rem": 0.2, "%": 20}[unit]:
            return f"CSS font-size:{m.group(1)}{m.group(2) or ''}"
    if _css(s, "overflow") == "hidden" and any(re.fullmatch(r"0(px)?", _css(s, p) or "x") for p in ("height", "width", "max-height")):
        return "zero-size box"
    if any(re.fullmatch(r"-\d{3,}(\.\d+)?(px|em|pt)?", _css(s, p) or "") for p in ("left", "top", "text-indent", "margin-left", "margin-top")):
        return "moved off screen"
    return None


WHITE = re.compile(r"^(#fff(fff)?|white|rgba?\(255,255,255(,1(\.0*)?)?\))$")


SIMPLE_SELECTOR = re.compile(r"^([a-z][a-z0-9]*)?((?:[.#][a-z0-9_-]+)*)$")


def parse_stylesheet(css: str) -> list[tuple[str | None, set[str], str | None, str]]:
    """Rules from a <style> block as (tag, classes, id, declarations). Only simple selectors such as
    p, .note, #x, p.note are used; selectors with combinators are skipped rather than guessed."""
    rules = []
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S).lower()
    for selectors, body in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
        for sel in selectors.split(","):
            m = SIMPLE_SELECTOR.match(sel.strip())
            if not m or not sel.strip():
                continue
            parts = re.findall(r"[.#][a-z0-9_-]+", m.group(2) or "")
            rules.append((m.group(1), {p[1:] for p in parts if p[0] == "."},
                          next((p[1:] for p in parts if p[0] == "#"), None), body))
    return rules


def _css(style: str, prop: str) -> str | None:
    """Value of one CSS property in an inline style (spaces removed, lower case)."""
    vals = re.findall(rf"(?:^|;){prop}:([^;]+)", style.replace(" ", "").lower())
    return vals[-1].replace("!important", "") if vals else None  # last declaration wins


class _VisibleHTML(HTMLParser):
    """Visible text of an HTML page. Each open element is a stack entry (tag, hiding technique,
    background colour); end tags pop back to their matching start tag, so unclosed children
    (<p>, <li>, ...) cannot leave a hidden state behind."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None, str | None]] = []
        self.out: list[str] = []
        self.removed: list[dict] = []
        self._hidden_buf: list[str] = []
        self.rules: list[tuple[str | None, set[str], str | None, str]] = []

    def _style_for(self, tag: str, attrs: dict) -> str:
        """Declarations from matching <style> rules, then the inline style (inline wins)."""
        classes = set((attrs.get("class") or "").lower().split())
        el_id = (attrs.get("id") or "").lower() or None
        decl = [body for t, cls, i, body in self.rules
                if (t is None or t == tag) and cls <= classes and (i is None or i == el_id) and (t or cls or i)]
        return ";".join(decl + [attrs.get("style") or ""])

    def _hiding(self) -> str | None:
        return next((h for _, h, _ in reversed(self.stack) if h), None)

    def _background(self) -> str:
        return next((bg for _, _, bg in reversed(self.stack) if bg), "#ffffff")

    def handle_starttag(self, tag, attrs):
        if tag in BLOCK:
            self.out.append("\n")
        if tag in VOID:
            return
        a = dict(attrs)
        style = self._style_for(tag, a)
        how = hidden_style(style)
        bg = _css(style, "background-color") or _css(style, "background")
        color = _css(style, "color")
        # White text is only invisible on a white (or unset) background; white on a dark banner is legitimate.
        if not how and color and WHITE.match(color) and WHITE.match(bg or self._background()):
            how = "white text"
        if "hidden" in a:
            how = "hidden attribute"
        if tag in CODE_TAGS:
            how = f"<{tag}> element"
        self.stack.append((tag, how, bg))

    def handle_endtag(self, tag):
        if tag in VOID or not any(t == tag for t, _, _ in self.stack):
            return  # stray end tag: ignore instead of popping someone else's state
        while self.stack:
            t, how, _ = self.stack.pop()
            self._flush(how)
            if t == tag:
                break
        if tag in ("td", "th"):
            self.out.append(" ")

    def _flush(self, how: str | None) -> None:
        if how and not self._hiding():
            text = " ".join("".join(self._hidden_buf).split())
            self._hidden_buf = []
            if text and how != "<style> element":  # stylesheets are layout code, not worth logging
                self.removed.append({"technique": how, "text": text})

    def handle_data(self, data):
        if self.stack and self.stack[-1][0] == "style":
            self.rules += parse_stylesheet(data)  # rules apply to elements after the <style> block
        (self._hidden_buf if self._hiding() else self.out).append(data)

    def handle_comment(self, data):
        if data.strip():
            self.removed.append({"technique": "HTML comment", "text": " ".join(data.split())})


def clean_html(html: str) -> tuple[str, list[dict]]:
    p = _VisibleHTML()
    p.feed(html)
    p.close()
    while p.stack:  # unclosed elements at the end of the document
        p._flush(p.stack.pop()[1])
    lines = (" ".join(line.split()) for line in "".join(p.out).splitlines())
    return "\n".join(line for line in lines if line), p.removed


# ---------- PDF ----------

def clean_pdf(path: Path) -> tuple[str, list[dict]]:
    visible: list[str] = []
    removed: list[dict] = []
    for page in PdfReader(path).pages:
        box = page.cropbox  # the visible area (defaults to the media box)
        x0, y0, x1, y1 = float(box.left), float(box.bottom), float(box.right), float(box.top)
        gs = {"fill": (0.0, 0.0, 0.0), "mode": 0}
        stack: list[dict] = []
        pending: list[tuple[float, float, float, float]] = []  # rectangles in the current path
        dark: list[tuple[float, float, float, float]] = []     # filled non-white rectangles (backgrounds)

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
            elif op in (b"sc", b"scn") and args and all(isinstance(a, (int, float)) for a in args):
                v = [float(a) for a in args]
                if len(v) == 1:
                    gs["fill"] = (v[0],) * 3
                elif len(v) == 3:
                    gs["fill"] = tuple(v)
                elif len(v) == 4:
                    gs["fill"] = tuple((1 - min(1.0, c + v[3])) for c in v[:3])
            elif op == b"Tr" and args:
                gs["mode"] = int(args[0])
            elif op == b"re" and len(args) == 4:
                rx, ry, rw, rh = (float(a) for a in args)
                corners = [(px * cm[0] + py * cm[2] + cm[4], px * cm[1] + py * cm[3] + cm[5])
                           for px in (rx, rx + rw) for py in (ry, ry + rh)]
                xs, ys = [c[0] for c in corners], [c[1] for c in corners]
                pending.append((min(xs), min(ys), max(xs), max(ys)))
            elif op in (b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"):
                if not all(c >= 0.95 for c in gs["fill"]):
                    dark.extend(pending)
                pending.clear()
            elif op in (b"n", b"S", b"s"):
                pending.clear()

        def on_text(text, cm, tm, font, size):
            if not text.strip():
                return
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            # Effective size = font size x the vertical scale of text matrix and CTM (works for rotated text too).
            scale = math.hypot(tm[2], tm[3]) * math.hypot(cm[2], cm[3])
            eff = float(size) * (scale or 1.0)
            why = []
            on_dark = any(a <= x <= c and b <= y <= d for a, b, c, d in dark)
            if all(c >= 0.95 for c in gs["fill"]) and not on_dark:
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
        visible.append("\n")  # keep the last line of one page apart from the first line of the next
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
