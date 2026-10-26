"""Layer 1 (code): turn a vendor document into the text a person would actually see.

Removed before anything reaches the model, and logged:
  HTML   CSS from inline styles AND <style> rules (tag, .class, #id selectors; last value wins):
         display:none, visibility:hidden, opacity:0, tiny fonts (font-size or the font shorthand),
         zero-size or clipped boxes, boxes moved off screen, transparent text, white or near-white
         text on a white background (white text on a dark banner, bgcolor cell, etc. is kept);
         the hidden attribute, <font color="#fff">, HTML comments, <script>/<style>/<noscript>/<template>
  PDF    text drawn white (fill, or stroke for stroke-only text) unless it sits on a dark filled box,
         invisible render modes (3, 7), fully transparent text (ExtGState /ca or /CA = 0),
         text smaller than 4 pt, text outside the visible (crop) box
  Email  inside multipart/alternative, only the version a mail client shows (HTML, else plain text);
         every other body part is kept; HTML parts are cleaned as above
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

from tools import decode_html, part_text, resolve_doc

INVISIBLE_CHARS = re.compile(r"[​-‏‪-‮⁠-⁤⁦-⁩﻿­]")
MAX_CHARS = 8000
CODE_TAGS = {"script", "style", "noscript", "template"}
VOID = {"br", "img", "hr", "meta", "link", "input", "wbr", "col", "area", "base", "source"}
BLOCK = {"br", "p", "tr", "div", "h1", "h2", "h3", "h4", "li", "footer", "header", "table", "section"}
# Start tags that implicitly close an open <p> (HTML parsing rules), so "<p>a<div>" does not nest.
CLOSES_P = {"p", "div", "table", "ul", "ol", "dl", "h1", "h2", "h3", "h4", "h5", "h6", "section", "header",
            "footer", "article", "aside", "nav", "main", "blockquote", "pre", "form", "hr", "address",
            "fieldset", "figure", "details"}
MIN_PDF_FONT = 4.0
NAMED = {"white": (255, 255, 255, 1.0), "black": (0, 0, 0, 1.0), "transparent": (0, 0, 0, 0.0)}


@dataclass
class CleanDoc:
    text: str
    removed: list[dict] = field(default_factory=list)  # {"technique", "text"}
    seconds: float = 0.0


# ---------- CSS helpers ----------

def _css(style: str, prop: str) -> str | None:
    """Last value of a CSS property in a declaration string (case and whitespace tolerant)."""
    vals = re.findall(rf"(?:^|;)\s*{re.escape(prop)}\s*:\s*([^;]+)", style.lower())
    return re.sub(r"\s*!important\s*$", "", vals[-1]).strip() if vals else None


def parse_color(value: str | None) -> tuple[float, float, float, float] | None:
    """(r, g, b, alpha) for #rgb/#rgba/#rrggbb/#rrggbbaa, rgb()/rgba() (comma or space syntax), or a few names."""
    if not value:
        return None
    v = value.strip().lower()
    if v in NAMED:
        return NAMED[v]
    m = re.fullmatch(r"#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})", v)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return r, g, b, (int(h[6:8], 16) / 255 if len(h) == 8 else 1.0)
    m = re.fullmatch(r"rgba?\(\s*([\d.]+%?)[\s,]+([\d.]+%?)[\s,]+([\d.]+%?)\s*(?:[,/]\s*([\d.]+%?))?\s*\)", v)
    if m:
        def ch(x: str) -> float:
            return float(x[:-1]) * 2.55 if x.endswith("%") else float(x)
        a = m.group(4)
        alpha = 1.0 if a is None else (float(a[:-1]) / 100 if a.endswith("%") else float(a))
        return ch(m.group(1)), ch(m.group(2)), ch(m.group(3)), alpha
    return None  # other named colours: treated as ordinary (non-white, opaque)


def _background_of(style: str, attrs: dict) -> tuple | None:
    """Opaque background colour set on this element, if any (background-color, background shorthand, bgcolor)."""
    for v in (_css(style, "background-color"), _css(style, "background"), attrs.get("bgcolor")):
        if not v:
            continue
        for token in re.findall(r"#[0-9a-f]+|rgba?\([^)]*\)|[a-z]+", v.lower()):
            c = parse_color(token)
            if c is not None:
                return c if c[3] > 0 else None  # transparent backgrounds let the parent's show through
            if token not in ("none", "url", "repeat", "no", "center", "top", "left", "fixed", "scroll"):
                return (0, 0, 0, 1.0)  # an unknown named colour such as navy: treat as a dark, opaque background
    return None


def _near_white(c: tuple) -> bool:
    return all(x >= 242 for x in c[:3])


def _font_size(style: str) -> tuple[float, str] | None:
    size = _css(style, "font-size")
    if size is None:
        font = _css(style, "font")  # shorthand, e.g. "0/0 a" or "italic 12px/1.4 arial"
        m = re.search(r"(?:^|\s)([\d.]+)(px|pt|em|rem|%|vw|vh)?(?=\s|/|$)", font or "")
        return (float(m.group(1)), m.group(2) or "px") if m else None
    m = re.fullmatch(r"([\d.]+)\s*(px|pt|em|rem|%|vw|vh)?", size)
    return (float(m.group(1)), m.group(2) or "px") if m else None


def hidden_style(style: str) -> str | None:
    """Hiding technique used by a declaration string, or None (colour/background are checked separately)."""
    if _css(style, "display") == "none":
        return "CSS display:none"
    if _css(style, "visibility") in ("hidden", "collapse"):
        return "CSS visibility:hidden"
    op = _css(style, "opacity")
    if op is not None:
        m = re.fullmatch(r"([\d.]+)\s*(%?)", op)
        if m and float(m.group(1)) == 0:
            return "CSS opacity:0"
    fs = _font_size(style)
    if fs:
        size, unit = fs
        if size == 0 or size <= {"px": 2, "pt": 2, "em": 0.2, "rem": 0.2, "%": 20, "vw": 0.2, "vh": 0.2}[unit]:
            return f"CSS font-size:{size:g}{unit}"
    zero = re.compile(r"0+(\.0+)?\s*(px|pt|em|rem|%)?")
    if _css(style, "overflow") in ("hidden", "clip") and any(
            zero.fullmatch(_css(style, p) or "x") for p in ("height", "width", "max-height", "max-width")):
        return "zero-size box"
    clip = (_css(style, "clip") or "").replace(" ", "")
    if re.fullmatch(r"rect\(0(px)?[,]?0(px)?[,]?0(px)?[,]?0(px)?\)", clip) or "inset(50%)" in (_css(style, "clip-path") or "") \
            or "inset(100%)" in (_css(style, "clip-path") or ""):
        return "clipped to nothing"
    if any(re.fullmatch(r"-\d{3,}(\.\d+)?\s*(px|em|pt|rem)?", _css(style, p) or "")
           for p in ("left", "top", "text-indent", "margin-left", "margin-top")):
        return "moved off screen"
    return None


SIMPLE_SELECTOR = re.compile(r"^([a-z][a-z0-9]*)?((?:[.#][a-z0-9_-]+)*)$")


def parse_stylesheet(css: str) -> list[tuple[str | None, set[str], str | None, str]]:
    """Rules from a <style> block as (tag, classes, id, declarations). Only simple selectors such as
    p, .note, #x, p.note are used; selectors with combinators are skipped rather than guessed."""
    rules = []
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S).lower()
    for selectors, body in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
        for sel in selectors.split(","):
            sel = sel.strip()
            m = SIMPLE_SELECTOR.match(sel)
            if not sel or not m:
                continue
            parts = re.findall(r"[.#][a-z0-9_-]+", m.group(2) or "")
            rules.append((m.group(1), {p[1:] for p in parts if p[0] == "."},
                          next((p[1:] for p in parts if p[0] == "#"), None), " ".join(body.split())))
    return rules


# ---------- HTML ----------

class _VisibleHTML(HTMLParser):
    """Visible text of an HTML page. Each open element is a stack entry (tag, hiding technique,
    background colour). End tags pop back to their matching start tag, and start tags close an open
    <p>/<li>/<td>/<tr> the way browsers do, so unclosed elements cannot leave a hidden state behind."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None, tuple | None]] = []
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
        return ";".join(decl + [" ".join((attrs.get("style") or "").split())])

    def _hiding(self) -> str | None:
        return next((h for _, h, _ in reversed(self.stack) if h), None)

    def _background(self) -> tuple:
        return next((bg for _, _, bg in reversed(self.stack) if bg), (255, 255, 255, 1.0))

    def _pop_to(self, tag: str, stop: set[str]) -> None:
        """Close an open `tag` element (and anything opened inside it) unless a `stop` element is in between."""
        for i in range(len(self.stack) - 1, -1, -1):
            t = self.stack[i][0]
            if t == tag:
                while len(self.stack) > i:
                    self._flush(self.stack.pop()[1])
                return
            if t in stop:
                return

    def handle_starttag(self, tag, attrs):
        if tag in CLOSES_P:
            self._pop_to("p", {"div", "td", "th", "li", "table", "body", "html"} - {tag})
        if tag == "li":
            self._pop_to("li", {"ul", "ol"})
        if tag in ("td", "th"):
            self._pop_to("td", {"tr", "table"})
            self._pop_to("th", {"tr", "table"})
        if tag == "tr":
            self._pop_to("tr", {"table"})
        if tag in BLOCK:
            self.out.append("\n")
        if tag in VOID:
            return
        a = {k: (v or "") for k, v in attrs}
        style = self._style_for(tag, a)
        how = hidden_style(style)
        bg = _background_of(style, a)
        color = parse_color(_css(style, "color") or a.get("color"))  # <font color="..."> as a fallback
        if not how and color is not None:
            if color[3] == 0:
                how = "transparent text"
            elif _near_white(color) and _near_white(bg or self._background()):
                # White text is only invisible on a white background; white on a dark banner is legitimate.
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

def _rgb(args) -> tuple | None:
    """Colour operands (gray, RGB, or CMYK) as an RGB tuple in 0-1, or None for pattern/name operands."""
    if not args or not all(isinstance(a, (int, float)) for a in args):
        return None
    v = [float(a) for a in args]
    if len(v) == 1:
        return (v[0],) * 3
    if len(v) == 3:
        return tuple(v)
    if len(v) == 4:
        return tuple((1 - min(1.0, c + v[3])) for c in v[:3])
    return None


def clean_pdf(path: Path) -> tuple[str, list[dict]]:
    visible: list[str] = []
    removed: list[dict] = []
    for page in PdfReader(path).pages:
        box = page.cropbox  # the visible area (defaults to the media box)
        x0, y0, x1, y1 = float(box.left), float(box.bottom), float(box.right), float(box.top)
        try:
            ext = page.get("/Resources", {}).get_object().get("/ExtGState", {}).get_object()
        except AttributeError:
            ext = {}
        gs = {"fill": (0.0, 0.0, 0.0), "stroke": (0.0, 0.0, 0.0), "mode": 0, "ca": 1.0, "CA": 1.0}
        stack: list[dict] = []
        pending: list[tuple[float, float, float, float]] = []  # rectangles in the current path
        dark: list[tuple[float, float, float, float]] = []     # filled non-white rectangles (backgrounds)

        def before(op, args, cm, tm):
            if op == b"q":
                stack.append(dict(gs))
            elif op == b"Q" and stack:
                gs.update(stack.pop())
            elif op in (b"rg", b"g", b"k", b"sc", b"scn"):
                c = _rgb(args)
                if c:
                    gs["fill"] = c
            elif op in (b"RG", b"G", b"K", b"SC", b"SCN"):
                c = _rgb(args)
                if c:
                    gs["stroke"] = c
            elif op == b"gs" and args:
                try:
                    d = ext[args[0]].get_object()
                    gs["ca"] = float(d.get("/ca", gs["ca"]))
                    gs["CA"] = float(d.get("/CA", gs["CA"]))
                except (KeyError, TypeError, ValueError, AttributeError):
                    pass
            elif op == b"Tr" and args:
                gs["mode"] = int(args[0])
            elif op == b"re" and len(args) == 4:
                rx, ry, rw, rh = (float(a) for a in args)
                corners = [(px * cm[0] + py * cm[2] + cm[4], px * cm[1] + py * cm[3] + cm[5])
                           for px in (rx, rx + rw) for py in (ry, ry + rh)]
                xs, ys = [c[0] for c in corners], [c[1] for c in corners]
                pending.append((min(xs), min(ys), max(xs), max(ys)))
            elif op in (b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"):
                if not all(c >= 0.95 for c in gs["fill"]) and gs["ca"] > 0:
                    dark.extend(pending)
                pending.clear()
            elif op in (b"n", b"S", b"s"):
                pending.clear()

        def on_text(text, cm, tm, font, size):
            if not text.strip():
                if "\n" in text:
                    visible.append("\n")  # line breaks between text blocks keep facts on separate lines
                return
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            # Effective size = font size x the vertical scale of text matrix and CTM (works for rotated text too).
            scale = math.hypot(tm[2], tm[3]) * math.hypot(cm[2], cm[3])
            eff = float(size) * (scale or 1.0)
            mode = gs["mode"]
            # Which paint the glyphs use: fill (0, 2, 4, 6), stroke (1, 2, 5, 6); 3 and 7 paint nothing.
            paints = []
            if mode in (0, 2, 4, 6):
                paints.append((gs["fill"], gs["ca"]))
            if mode in (1, 2, 5, 6):
                paints.append((gs["stroke"], gs["CA"]))
            on_dark = any(a <= x <= c and b <= y <= d for a, b, c, d in dark)
            why = []
            if mode in (3, 7):
                why.append("invisible render mode")
            elif all(alpha == 0 for _, alpha in paints):
                why.append("fully transparent text")
            elif all(all(c >= 0.95 for c in col) for col, _ in paints) and not on_dark:
                why.append("white text")
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
                if "\n" in text:
                    visible.append("\n")
            else:
                visible.append(text)

        page.extract_text(visitor_operand_before=before, visitor_text=on_text)
        visible.append("\n")  # keep the last line of one page apart from the first line of the next
    lines = (" ".join(line.split()) for line in "".join(visible).splitlines())
    return "\n".join(line for line in lines if line), removed


# ---------- email ----------

def _descendants(part) -> set[int]:
    return {id(p) for p in part.walk()}


def clean_eml(path: Path) -> tuple[str, list[dict]]:
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    header = "\n".join(f"{h}: {msg[h]}" for h in ("From", "To", "Subject", "Date") if msg[h])
    removed: list[dict] = []
    skip: set[int] = set()
    skipped_plain: list[str] = []
    # multipart/alternative: a mail client shows one version - the last one it can render, HTML before plain.
    for part in msg.walk():
        if part.get_content_type() != "multipart/alternative":
            continue
        kids = list(part.iter_parts())
        has_html = [k for k in kids if any(p.get_content_type() == "text/html" for p in k.walk())]
        chosen = has_html[-1] if has_html else next((k for k in reversed(kids) if k.get_content_type() == "text/plain"), None)
        for k in kids:
            if k is not chosen:
                skip |= _descendants(k)
                skipped_plain += [part_text(p) for p in k.walk() if p.get_content_type() == "text/plain"]
    bodies: list[str] = []
    for part in msg.walk():
        if id(part) in skip or part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain":
            bodies.append(part_text(part).strip())
        elif ctype == "text/html":
            text, hidden = clean_html(part_text(part))
            bodies.append(text)
            removed += [{"technique": "email HTML part: " + h["technique"], "text": h["text"]} for h in hidden]
    body = "\n\n".join(b for b in bodies if b)
    shown = " ".join(body.split())
    if any(" ".join(t.split()) != shown for t in skipped_plain):
        removed.append({"technique": "email plain-text alternative (not what the client shows)",
                        "text": "(ignored; the visible HTML part was used instead)"})
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
        text, removed = clean_html(decode_html(p.read_bytes()))
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
