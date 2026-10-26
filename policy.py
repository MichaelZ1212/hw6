"""Layer 2 (architecture): the purchasing decision is made by code, not by the model.

The model only extracts facts. Code then
  1. grounds each fact: the value must appear in the visible document text in a place that fits it (a price
     next to "$"/"price", a lead time next to "lead"/"days", a minimum next to "minimum"/"units"),
     otherwise it becomes unknown (null), so a value the model invented or was talked into is dropped
  2. applies the four handbook checks (section 4) against tables parsed from data/shop_handbook.md
  3. writes the one-sentence reason itself from handbook names, the SKU, and numbers, so no free text
     from the document can reach the reason

Nothing a vendor document says can change the approved-vendor list, the max unit costs, or the limits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from models import VendorDecision

HANDBOOK = Path(__file__).resolve().parent / "data" / "shop_handbook.md"
MAX_LEAD_DAYS = 21
MAX_MIN_ORDER = 600


@dataclass(frozen=True)
class Rules:
    approved: dict[str, str]                 # canonical vendor key -> handbook name
    blocked: dict[str, tuple[str, str]]      # canonical vendor key -> (handbook name, status)
    max_cost: dict[str, float]               # SKU -> max unit cost


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


LEGAL_SUFFIXES = {"inc", "incorporated", "llc", "ltd", "limited", "co", "company", "corp", "corporation", "plc", "lp"}


def vendor_key(name: str) -> str:
    """Canonical vendor name: lower-case words without trailing legal suffixes, so "Blue Hen Apparel, Inc."
    and "Westville Bag Co." match the handbook, but "Blue Hen Apparel Liquidators LLC" does not."""
    words = re.findall(r"[a-z0-9]+", name.lower().replace("&", " and "))
    if words and words[0] == "the":
        words = words[1:]
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return "".join(words)


SKU_RE = re.compile(r"\bCC[\s\-‐-―_]*([A-Z]{2})[\s\-‐-―_]*(\d{3})\b", re.I)


def canonical_sku(value: str | None) -> str | None:
    m = SKU_RE.search(value or "")
    return f"CC-{m.group(1).upper()}-{m.group(2)}" if m else value


def _table(md: str, heading: str) -> list[list[str]]:
    section = md.split(heading, 1)[1].split("\n## ", 1)[0]
    rows = [r.strip().strip("|").split("|") for r in section.splitlines() if r.strip().startswith("|")]
    return [[c.strip() for c in r] for r in rows[2:]]  # skip header and --- row


@lru_cache(maxsize=1)
def rules() -> Rules:
    md = HANDBOOK.read_text(encoding="utf-8")
    approved = {vendor_key(r[1]): r[1] for r in _table(md, "## 5. Approved vendors")}
    blocked = {vendor_key(r[0]): (r[0], r[1]) for r in _table(md, "## 6. Removed and pending vendors")}
    max_cost = {r[0]: float(r[4].lstrip("$")) for r in _table(md, "## 9. Product catalogue")}
    return Rules(approved, blocked, max_cost)


# ---------- grounding ----------

NUM = r"\d[\d,]*(?:\.\d+)?"


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _numbers(text: str) -> list[float]:
    return [_num(n) for n in re.findall(rf"(?<![\d.]){NUM}", text)]


def _candidates(text: str, line_words: str, near: str) -> list[float]:
    """Numbers on lines that mention the fact (line_words) or written next to its unit (near).
    If the document has none, every number is a candidate."""
    found = [n for line in text.splitlines() if re.search(line_words, line, re.I) for n in _numbers(line)]
    for m in re.finditer(near, text, re.I):
        found += [_num(g) for g in m.groups() if g]
    return found or _numbers(text)


def ground(out: VendorDecision, visible_text: str) -> tuple[dict, list[str]]:
    """Keep a fact only if it appears in the visible document text, in a place that fits the fact."""
    t = visible_text
    facts, notes = out.model_dump(include={"vendor", "sku", "unit_price", "lead_time_days", "min_order"}), []
    facts["sku"] = canonical_sku(facts["sku"])
    prices = _candidates(t, r"price|cost|rate|\$|usd",
                         rf"(?:\$|usd|us\$)\s*({NUM})|({NUM})\s*(?:/\s*unit|per unit|each|ea\b)")
    leads = _candidates(t, r"lead|deliver|ship|turnaround|production|dispatch|\beta\b|ready in",
                        rf"({NUM})\s*(?:business |working |calendar )?days?\b")
    weeks = [(_num(n), bool(kind)) for n, kind in re.findall(rf"({NUM})\s*-?\s*(business |working )?weeks?\b", t, re.I)]
    moqs = _candidates(t, r"min|moq|at least|order quantit", rf"({NUM})\s*(?:units?|pcs|pieces)\b")
    sku_in_text = {canonical_sku(m.group(0)) for m in SKU_RE.finditer(t)}
    checks = {
        "vendor": lambda v: bool(vendor_key(v)) and norm(v) in norm(t),
        "sku": lambda v: v in sku_in_text or v.upper() in t.upper(),
        "unit_price": lambda v: any(abs(n - v) < 0.005 for n in prices),
        # weeks may be reported in days: x7 calendar days, or x5 if the text says business/working weeks
        "lead_time_days": lambda v: any(n == v for n in leads) or any(
            abs(w * k - v) < 0.5 for w, biz in weeks for k in ((7, 5) if biz else (7,))),
        "min_order": lambda v: any(n == v for n in moqs),
    }
    for f, ok in checks.items():
        if facts[f] is not None and not ok(facts[f]):
            notes.append(f"{f}={facts[f]!r} not found in the visible document text, set to unknown")
            facts[f] = None
    return facts, notes


# ---------- decision ----------

def decide(f: dict) -> tuple[str, str]:
    """Apply the four handbook checks. The reason only contains handbook names, the canonical SKU, and numbers,
    never free text from the document."""
    r = rules()
    vendor, price, lead, moq = f["vendor"], f["unit_price"], f["lead_time_days"], f["min_order"]
    sku = canonical_sku(f["sku"])
    key = vendor_key(vendor or "")
    if not key:
        return "do_not_recommend", "Approved-vendor check fails: the document does not name the vendor."
    if key in r.blocked:  # checked first, so a blocked vendor can never pass as approved
        return "do_not_recommend", (f"Approved-vendor check fails: {r.blocked[key][0]} is on the removed/pending vendor "
                                    f"list (handbook section 6).")
    if key not in r.approved:
        return "do_not_recommend", "Approved-vendor check fails: the quoting vendor is not on the approved vendor list."
    name = r.approved[key]
    if not sku or sku not in r.max_cost:
        return "do_not_recommend", "Price check fails: the quote does not name a Campus Customs catalogue SKU."
    if price is None:
        return "do_not_recommend", f"Price check fails: the document does not state a unit price for {sku}."
    if price > r.max_cost[sku]:
        return "do_not_recommend", f"Price check fails: ${price:.2f} is above the catalogue max unit cost for {sku}."
    if lead is None:
        return "do_not_recommend", "Lead-time check fails: the document does not state a lead time."
    if lead > MAX_LEAD_DAYS:
        return "do_not_recommend", f"Lead-time check fails: {lead} days is over the {MAX_LEAD_DAYS}-day limit."
    if moq is None:
        return "do_not_recommend", "Minimum-order check fails: the document does not state a minimum order."
    if moq > MAX_MIN_ORDER:
        return "do_not_recommend", f"Minimum-order check fails: {moq} units is over the {MAX_MIN_ORDER}-unit limit."
    return "recommend", (f"All four checks pass: {name} is approved, ${price:.2f} is within the max unit cost "
                         f"for {sku}, {lead}-day lead time, {moq}-unit minimum.")


def enforce(model_out: VendorDecision, visible_text: str) -> tuple[VendorDecision, dict]:
    """Final answer = grounded facts + code decision. Returns it with notes for the audit trail."""
    facts, notes = ground(model_out, visible_text)
    decision, reason = decide(facts)
    final = VendorDecision(**facts, decision=decision, reason=reason)
    return final, {
        "grounding_notes": notes,
        "model_decision": model_out.decision,
        "model_reason": model_out.reason,
        "model_overridden": model_out.decision != decision,
    }
