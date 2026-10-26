"""Layer 2 (architecture): the purchasing decision is made by code, not by the model.

The model only extracts facts. Code then
  1. grounds each fact: the value must appear in the visible document text, otherwise it becomes
     unknown (null), so a value the model invented or was talked into is dropped
  2. applies the four handbook checks (section 4) against tables parsed from data/shop_handbook.md
  3. writes the one-sentence reason itself, so no document text can reach the reason

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
    approved: frozenset[str]
    blocked: dict[str, str]          # normalized vendor -> status text
    max_cost: dict[str, float]       # SKU -> max unit cost


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _table(md: str, heading: str) -> list[list[str]]:
    section = md.split(heading, 1)[1].split("\n## ", 1)[0]
    rows = [r.strip().strip("|").split("|") for r in section.splitlines() if r.strip().startswith("|")]
    return [[c.strip() for c in r] for r in rows[2:]]  # skip header and --- row


@lru_cache(maxsize=1)
def rules() -> Rules:
    md = HANDBOOK.read_text(encoding="utf-8")
    approved = frozenset(norm(r[1]) for r in _table(md, "## 5. Approved vendors"))
    blocked = {norm(r[0]): r[1] for r in _table(md, "## 6. Removed and pending vendors")}
    max_cost = {r[0]: float(r[4].lstrip("$")) for r in _table(md, "## 9. Product catalogue")}
    return Rules(approved, blocked, max_cost)


# ---------- grounding ----------

def _numbers(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", text)]


def ground(out: VendorDecision, visible_text: str) -> tuple[dict, list[str]]:
    """Keep a fact only if it appears in the visible document text."""
    nums = _numbers(visible_text)
    text_n = norm(visible_text)
    facts, notes = out.model_dump(include={"vendor", "sku", "unit_price", "lead_time_days", "min_order"}), []
    checks = {
        "vendor": lambda v: norm(v) and norm(v) in text_n,
        "sku": lambda v: v.upper() in visible_text.upper(),
        "unit_price": lambda v: any(abs(n - v) < 0.005 for n in nums),
        "lead_time_days": lambda v: any(n == v for n in nums),
        "min_order": lambda v: any(n == v for n in nums),
    }
    for f, ok in checks.items():
        if facts[f] is not None and not ok(facts[f]):
            notes.append(f"{f}={facts[f]!r} not found in the visible document text, set to unknown")
            facts[f] = None
    return facts, notes


# ---------- decision ----------

def _listed(v: str, names) -> bool:
    """A handbook vendor name matches if it is the vendor name, or the start of it (e.g. "Blue Hen Apparel Inc.")."""
    return any(v == n or v.startswith(n) for n in names)


def decide(f: dict) -> tuple[str, str]:
    r = rules()
    vendor, sku, price, lead, moq = f["vendor"], f["sku"], f["unit_price"], f["lead_time_days"], f["min_order"]
    v = norm(vendor or "")
    if not v:
        return "do_not_recommend", "Approved-vendor check fails: the document does not name the vendor."
    if _listed(v, r.blocked):  # checked first, so a blocked vendor can never pass as approved
        return "do_not_recommend", (f"Approved-vendor check fails: {vendor} is on the removed/pending vendor list "
                                    f"(handbook section 6).")
    if not _listed(v, r.approved):
        return "do_not_recommend", f"Approved-vendor check fails: {vendor} is not on the approved vendor list."
    if not sku or sku.upper() not in r.max_cost:
        return "do_not_recommend", "Price check fails: the quote does not name a Campus Customs catalogue SKU."
    if price is None:
        return "do_not_recommend", f"Price check fails: the document does not state a unit price for {sku}."
    if price > r.max_cost[sku.upper()]:
        return "do_not_recommend", f"Price check fails: ${price:.2f} is above the catalogue max unit cost for {sku}."
    if lead is None:
        return "do_not_recommend", "Lead-time check fails: the document does not state a lead time."
    if lead > MAX_LEAD_DAYS:
        return "do_not_recommend", f"Lead-time check fails: {lead} days is over the {MAX_LEAD_DAYS}-day limit."
    if moq is None:
        return "do_not_recommend", "Minimum-order check fails: the document does not state a minimum order."
    if moq > MAX_MIN_ORDER:
        return "do_not_recommend", f"Minimum-order check fails: {moq} units is over the {MAX_MIN_ORDER}-unit limit."
    return "recommend", (f"All four checks pass: {vendor} is approved, ${price:.2f} is within the max unit cost "
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
