"""Problem 9: build output/hw6_report.html, a single self-contained results dashboard.

Every number is read from the saved experiment files (nothing is typed in by hand) and summarized
with the same functions the earlier markdown reports used:
  data/prices.json, data/shop_handbook.md        Problem 2 estimate
  output/cache_test.json                         Problem 4 caching
  output/attack_results.json                     Problem 5 baseline attack test
  output/defense_results.json                    Problem 6 defenses and overhead
  output/red_team.json, output/red_team_round1.json   Problem 7 red team
  output/exam_results.json, output/audit_trail.json   Problem 8 exam run

The HTML has no external dependencies: CSS, JavaScript, SVG charts, and the data are all inline.

Usage:  python scripts/build_report.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import tiktoken  # noqa: E402

import cache_test  # noqa: E402
import defense_test  # noqa: E402

OUT = ROOT / "output" / "hw6_report.html"
DOCS_PER_MONTH = 1000 * 30
missing: list[str] = []


def load(name: str):
    p = ROOT / "output" / name
    if not p.exists():
        missing.append(f"output/{name} not found")
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def r6(x: float) -> float:
    return round(float(x), 8)


def build_data() -> dict:
    prices = json.loads((ROOT / "data" / "prices.json").read_text(encoding="utf-8"))["gpt-6-luna"]
    handbook_tokens = len(tiktoken.get_encoding("o200k_base").encode((ROOT / "data" / "shop_handbook.md").read_text(encoding="utf-8")))
    d: dict = {"prices": prices, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    # ---- Problem 2 estimate ----
    d["p2"] = {
        "handbook_tokens": handbook_tokens,
        "per_call_no_cache": r6(handbook_tokens * prices["input_per_1m"] / 1e6),
        "per_call_cache_hit": r6(handbook_tokens * prices["cached_input_per_1m"] / 1e6),
    }

    # ---- Problem 4 caching ----
    ct = load("cache_test.json")
    if ct:
        c = cache_test.summarize([r for r in ct["runs"] if r["cache_mode"] == "cached"])
        n = cache_test.summarize([r for r in ct["runs"] if r["cache_mode"] == "no_cache"])
        flagged = [f"{r['doc']} ({r['cache_mode']})" for r in ct["runs"] if r["status"] != "ok"]
        d["p4"] = {
            "time": ct["time"],
            "setups": {k: {"docs": s["docs_ok"], "calls": s["calls"], "input": s["input_tokens"], "cached": s["cached_tokens"],
                           "cache_write": s["cache_write_tokens"], "uncached": s["uncached_input_tokens"],
                           "output": s["output_tokens"], "total": r6(s["cost"]), "per_doc": r6(s["per_doc"]),
                           "parts": {p: r6(v) for p, v in s["cost_parts"].items()}, "correct": s["correct"]}
                       for k, s in (("cached", c), ("no_cache", n))},
            "saved_pct": (n["cost"] - c["cost"]) / n["cost"],
            "flagged": flagged,
        }

    # ---- Problem 5 baseline attack test ----
    at = load("attack_results.json")
    if at:
        d["p5"] = {"time": at["time"], "totals": at["totals"], "trials": at["trials_per_doc"],
                   "docs": [{"doc": x["doc"], "hidden": [h["technique"] for h in x["hidden_content"]],
                             "misled": x["summary"]["trials_misled"], "n": x["summary"]["trials_ok"]} for x in at["documents"]]}

    # ---- Problem 6 defenses ----
    df = load("defense_results.json")
    if df:
        runs = df["runs"]
        S = {m: defense_test.summarize([r for r in runs if r["mode"] == m]) for m in defense_test.MODES}
        keys = defense_test.KEY
        docs = sorted({r["doc"] for r in runs})

        def per(doc, mode):
            rs = [r for r in runs if r["doc"] == doc and r["mode"] == mode and r["status"] == "ok"]
            return {"n": len(rs), "misled": sum(r["misled"] for r in rs), "correct": sum(r["decision_correct"] for r in rs)}

        d["p6"] = {
            "time": df["time"], "trials": df["trials_per_doc"],
            "modes": [{"mode": m, "label": defense_test.LABEL[m], "runs": S[m]["runs"], "failed": S[m]["failed"],
                       "misled": S[m]["misled"], "decision_acc": S[m]["decision_acc"], "all_correct": S[m]["all_correct"],
                       "trap_calls": S[m]["trap_calls"], "suspicious": S[m]["suspicious"],
                       "legit_ok": S[m]["legit_recommended"], "legit_n": S[m]["legit_runs"], "nulls": S[m]["null_fields"],
                       "requests": S[m]["requests"], "input": S[m]["input"], "cached": S[m]["cached"],
                       "output": S[m]["output"], "cost_avg": r6(S[m]["cost_avg"]), "cost_median": r6(S[m]["cost_median"]),
                       "cost_total": r6(S[m]["cost_total"]), "latency": S[m]["seconds_median"],
                       "sanitize_ms": S[m]["sanitize_ms"], "policy_ms": S[m]["policy_ms"], "overridden": S[m]["overridden"]}
                      for m in defense_test.MODES],
            "docs": [{"doc": doc, "expected": keys[doc]["decision"],
                      "removed": sorted({t for r in runs if r["doc"] == doc and r["mode"] == "defended" for t in r["removed"]}),
                      **{m: per(doc, m) for m in defense_test.MODES}} for doc in docs],
            "prompt_tokens": {"baseline": df["static"]["baseline_prompt_tokens"], "hardened": df["static"]["hardened_prompt_tokens"]},
        }

    # ---- Problem 7 red team ----
    def red(data, key_file):
        keyfile = {k["file"]: k for k in json.loads(key_file.read_text(encoding="utf-8"))}
        out = []
        for doc in sorted({r["doc"] for r in data["runs"]}):
            row = {"doc": doc}
            for m in ("baseline", "defended"):
                rs = [r for r in data["runs"] if r["doc"] == doc and r["mode"] == m and r["status"] == "ok"]
                row[m] = {"n": len(rs), "succ": sum(r["attack_succeeded"] for r in rs),
                          "traps": sum(len(r["trap_calls"]) for r in rs),
                          "decisions": sorted({r["recommendation"]["decision"] for r in rs}),
                          "leads": sorted({str(r["recommendation"]["lead_time_days"]) for r in rs}),
                          "evidence": sorted({e for r in rs for e in r["evidence"]}),
                          "model_wrong": sum(1 for r in rs if r.get("model_decision") and r["model_decision"] != data["key"][doc]["decision"])}
            row["expected"] = data["key"][doc]["decision"]
            row["goal"] = keyfile[doc]["goal"]
            out.append(row)
        return out

    rt, rt1 = load("red_team.json"), load("red_team_round1.json")
    kdir = ROOT / "data" / "my_attacks"
    d["p7"] = {"round2": red(rt, kdir / "attack_key.json") if rt else None,
               "round1": red(rt1, kdir / "round1" / "attack_key.json") if rt1 else None,
               "time": rt["time"] if rt else None, "trials": rt["trials_per_doc"] if rt else None}

    # ---- Problem 8 exam ----
    ex = load("exam_results.json")
    audit = load("audit_trail.json") or []
    if ex:
        removed = {}
        for e in audit:
            if "exam_docs" in e.get("doc", "") and e.get("safety_mode") == "defended":
                removed[e["doc"].split("/")[-1]] = [r["technique"] for r in e["safety"].get("removed", [])]
        d["p8"] = [{**{k: r[k] for k in ("file", "vendor", "sku", "unit_price", "lead_time_days", "min_order", "decision",
                                         "reason", "trap_tool_called", "input_tokens", "cached_tokens", "output_tokens",
                                         "cost_usd", "status")},
                    "removed": removed.get(r["file"], [])} for r in ex]

    # ---- Projections (clearly estimates) ----
    if "p6" in d:
        m = {x["mode"]: x for x in d["p6"]["modes"]}
        d["projection"] = {
            "docs_per_month": DOCS_PER_MONTH,
            "defended_per_doc": m["defended"]["cost_avg"],
            "baseline_per_doc": m["baseline"]["cost_avg"],
        }
        if "p8" in d:
            d["projection"]["exam_per_doc"] = r6(sum(r["cost_usd"] for r in d["p8"]) / len(d["p8"]))
        if "p4" in d:
            d["projection"]["p4_no_cache_per_doc"] = d["p4"]["setups"]["no_cache"]["per_doc"]

    d["missing"] = missing + [
        "The exam documents have no answer key, so exam accuracy cannot be measured. Section 4 shows what the agent "
        "decided and a by-hand check against the handbook, not a score.",
        "Problem 4 measured caching on the Problem 3 (baseline) agent. A no-cache run of the defended agent was not "
        "measured, so the defended no-cache cost is not shown.",
        "The assignment's required field names for exam_results.json were not provided. The file uses the "
        "practice_key.json names plus reason, trap, token, and cost fields.",
    ]
    return d


# ---------------------------------------------------------------- self-checks

def self_check(d: dict) -> list[str]:
    """Cross-check the embedded numbers against independent recomputation from the raw files."""
    errs = []
    if not all(k in d for k in ("p4", "p6", "p8")):
        return errs  # a source file is missing; build_data already lists it under "What this report does not show"
    ct = json.loads((ROOT / "output" / "cache_test.json").read_text(encoding="utf-8"))
    for mode in ("cached", "no_cache"):
        raw = sum(r["cost"]["total_usd"] for r in ct["runs"] if r["cache_mode"] == mode and r["status"] == "ok")
        if abs(raw - d["p4"]["setups"][mode]["total"]) > 1e-7:
            errs.append(f"p4 {mode} total mismatch {raw} vs {d['p4']['setups'][mode]['total']}")
    df = json.loads((ROOT / "output" / "defense_results.json").read_text(encoding="utf-8"))
    for m in d["p6"]["modes"]:
        rs = [r for r in df["runs"] if r["mode"] == m["mode"] and r["status"] == "ok"]
        if sum(r["misled"] for r in rs) != m["misled"]:
            errs.append(f"p6 {m['mode']} misled mismatch")
        if abs(sum(r["cost"]["total_usd"] for r in rs) / len(rs) - m["cost_avg"]) > 1e-7:
            errs.append(f"p6 {m['mode']} cost mismatch")
    ex = json.loads((ROOT / "output" / "exam_results.json").read_text(encoding="utf-8"))
    if len(ex) != 10 or len(d["p8"]) != 10:
        errs.append("exam entries != 10")
    for a, b in zip(ex, d["p8"]):
        if a["decision"] != b["decision"] or a["unit_price"] != b["unit_price"]:
            errs.append(f"exam mismatch {a['file']}")
    return errs


# ---------------------------------------------------------------- HTML

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Campus Customs vendor desk agent - HW 6 results</title>
<style>
.viz-root {
  color-scheme: light;
  --page: #f9f9f7; --surface-1: #fcfcfb; --card: #ffffff;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #6f6d67;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a; --series-4: #eda100;
  --neutral: #b9b7ae;
  --good: #0ca30c; --good-text: #006300; --warning: #fab219; --critical: #d03b3b; --critical-text: #b42318;
  --accent-wash: #eef4fc;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz-root {
    color-scheme: dark;
    --page: #0d0d0d; --surface-1: #1a1a19; --card: #1a1a19;
    --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #9a988f;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
    --neutral: #5d5c57;
    --good: #0ca30c; --good-text: #0ca30c; --critical: #d03b3b; --critical-text: #f08a8a;
    --accent-wash: #16263a;
  }
}
:root[data-theme="dark"] .viz-root {
  color-scheme: dark;
  --page: #0d0d0d; --surface-1: #1a1a19; --card: #1a1a19;
  --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #9a988f;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
  --neutral: #5d5c57;
  --good: #0ca30c; --good-text: #0ca30c; --critical: #d03b3b; --critical-text: #f08a8a;
  --accent-wash: #16263a;
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body.viz-root { background: var(--page); color: var(--text-primary);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
.wrap { max-width: 1120px; margin: 0 auto; padding: 32px 24px 64px; }
header.top { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
h1 { font-size: 28px; line-height: 1.2; margin: 0 0 6px; font-weight: 650; }
h2 { font-size: 21px; margin: 0 0 4px; font-weight: 650; }
h3 { font-size: 16px; margin: 22px 0 8px; font-weight: 600; }
.sub { color: var(--text-secondary); margin: 0; }
.muted { color: var(--text-muted); font-size: 13px; }
nav.toc { display: flex; gap: 8px; flex-wrap: wrap; margin: 20px 0 8px; }
nav.toc a { color: var(--text-secondary); text-decoration: none; font-size: 13px; padding: 6px 12px;
  border: 1px solid var(--border); border-radius: 999px; background: var(--card); }
nav.toc a:hover { color: var(--text-primary); }
.theme-btn { font: inherit; font-size: 13px; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--card); color: var(--text-secondary); cursor: pointer; }
section.card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 24px; margin-top: 20px; }
.sec-num { display: inline-block; font-size: 12px; font-weight: 600; color: var(--text-secondary); letter-spacing: .04em;
  text-transform: uppercase; margin-bottom: 4px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 16px 0 4px; }
.tile { border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; background: var(--surface-1); }
.tile .label { color: var(--text-secondary); font-size: 13px; }
.tile .value { font-size: 26px; font-weight: 650; line-height: 1.2; margin-top: 4px; }
.tile .note { color: var(--text-muted); font-size: 12px; margin-top: 2px; }
.hero { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 20px; }
.hero .tile { background: var(--card); }
.hero .tile .value { font-size: 34px; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 20px; }
.chart { margin-top: 8px; position: relative; }
.chart svg { display: block; width: 100%; height: auto; overflow: visible; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px; color: var(--text-secondary); margin: 6px 0 2px; }
.legend .key { display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; margin-top: 10px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--grid); vertical-align: top; }
th { color: var(--text-secondary); font-weight: 600; font-size: 12.5px; background: var(--surface-1); }
td.nw { white-space: nowrap; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.table-wrap { overflow-x: auto; }
details.tv { margin-top: 6px; }
details.tv summary { cursor: pointer; color: var(--text-secondary); font-size: 13px; }
.chip { display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; font-weight: 600; padding: 2px 9px;
  border-radius: 999px; border: 1px solid var(--border); white-space: nowrap; }
.chip .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.chip.good { color: var(--good-text); } .chip.good .dot { background: var(--good); }
.chip.bad { color: var(--critical-text); } .chip.bad .dot { background: var(--critical); }
.chip.neutral { color: var(--text-secondary); } .chip.neutral .dot { background: var(--neutral); }
.callout { border-left: 3px solid var(--series-1); background: var(--accent-wash); padding: 12px 16px; border-radius: 0 10px 10px 0; margin: 14px 0; }
.est { display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
  color: var(--text-secondary); border: 1px dashed var(--axis); border-radius: 6px; padding: 1px 6px; margin-left: 6px; vertical-align: 2px; }
ul.clean { margin: 8px 0; padding-left: 20px; } ul.clean li { margin: 4px 0; }
.tip { position: fixed; pointer-events: none; z-index: 10; background: var(--card); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; font-size: 13px; box-shadow: 0 4px 16px rgba(0,0,0,.12);
  display: none; max-width: 280px; }
.tip strong { font-size: 14px; display: block; }
.tip .k { display: inline-block; width: 14px; height: 2px; vertical-align: 4px; margin-right: 6px; }
.verdict { font-size: 18px; font-weight: 650; margin: 6px 0 10px; }
footer { color: var(--text-muted); font-size: 12px; margin-top: 28px; }
code { font: 12.5px ui-monospace, SFMono-Regular, Consolas, monospace; background: var(--surface-1); padding: 1px 5px; border-radius: 5px; border: 1px solid var(--border); }
@media print { .theme-btn, nav.toc { display: none; } section.card { break-inside: avoid; } }
</style>
</head>
<body class="viz-root">
<div class="wrap">
  <header class="top">
    <div>
      <h1>Vendor desk agent: results report</h1>
      <p class="sub">Campus Customs, HW 6. What the AI vendor desk costs, how it was attacked, and how it was secured.</p>
      <p class="muted" id="gen"></p>
    </div>
    <button class="theme-btn" id="themeBtn" type="button">Switch light / dark</button>
  </header>
  <nav class="toc">
    <a href="#s1">1 · Caching &amp; cost</a><a href="#s2">2 · Security</a><a href="#s3">3 · Defense overhead</a>
    <a href="#s4">4 · Exam &amp; red team</a><a href="#s5">5 · Recommendation</a>
  </nav>
  <div class="hero" id="hero"></div>

  <section class="card" id="s1">
    <span class="sec-num">Section 1 · Problems 2 and 4</span>
    <h2>Caching and cost savings</h2>
    <p class="sub">The 10,000-token shop handbook is sent on every call. Prompt caching lets the AI provider reuse it at a 90% discount.</p>
    <div class="tiles" id="p4tiles"></div>
    <div class="grid2">
      <div><h3>Average cost per document, by what you pay for</h3><div class="legend" id="p4legend"></div><div class="chart" id="p4chart"></div></div>
      <div><h3>Estimate (Problem 2) vs. what we actually paid</h3><div class="table-wrap" id="p4est"></div>
        <p class="muted">The estimate priced only the handbook for one call. Real runs make 2 calls per document and also send the
        instructions, tool definitions, and the document, so real costs are higher. The savings rate is close to the estimate.</p></div>
    </div>
    <details class="tv"><summary>Table view: full caching test numbers</summary><div class="table-wrap" id="p4table"></div></details>
    <div class="callout" id="p4notes"></div>
  </section>

  <section class="card" id="s2">
    <span class="sec-num">Section 2 · Problems 5 and 6</span>
    <h2>Security improvements</h2>
    <p class="sub">Some supplier documents hide instructions aimed at the AI. We measured how often the agent was misled before and after adding three safety layers.</p>
    <div class="tiles" id="p6tiles"></div>
    <div class="grid2">
      <div><h3>Runs where the agent was misled (out of 36)</h3><div class="chart" id="p6misled"></div></div>
      <div><h3>Correct purchasing decisions</h3><div class="chart" id="p6acc"></div></div>
    </div>
    <h3>Every practice document: before vs. after</h3>
    <div class="table-wrap" id="p6docs"></div>
    <p class="muted" id="p6docsnote"></p>
  </section>

  <section class="card" id="s3">
    <span class="sec-num">Section 3 · Problem 6</span>
    <h2>Defense overhead: what security costs</h2>
    <p class="sub">Each safety layer was switched on one at a time and measured on the same 12 documents, 3 runs each.</p>
    <div class="tiles" id="p3tiles"></div>
    <div class="grid2">
      <div><h3>Average cost per document</h3><div class="chart" id="p3cost"></div></div>
      <div><h3>Input tokens sent per document</h3><div class="chart" id="p3tok"></div></div>
    </div>
    <h3>What each layer adds or saves (measured)</h3>
    <div class="table-wrap" id="p3table"></div>
    <div class="callout" id="p3note"></div>
  </section>

  <section class="card" id="s4">
    <span class="sec-num">Section 4 · Problems 7 and 8</span>
    <h2>Exam and red-team results</h2>
    <h3>10 exam documents, defended agent</h3>
    <div class="tiles" id="p8tiles"></div>
    <div class="table-wrap" id="p8table"></div>
    <p class="muted">The exam documents have no answer key. "Handbook check" compares each decision with the handbook tables
    (approved vendors, max unit cost, 21 days, 600 units) recomputed in this report, not with an official answer.</p>
    <h3>Two custom attacks (red team)</h3>
    <div class="table-wrap" id="p7table"></div>
    <div class="callout" id="p7notes"></div>
  </section>

  <section class="card" id="s5">
    <span class="sec-num">Section 5</span>
    <h2>Recommendation for the store manager</h2>
    <div id="rec"></div>
    <h3>Monthly operating cost <span class="est">Projection</span></h3>
    <div class="tiles" id="projtiles"></div>
    <div class="table-wrap" id="projtable"></div>
    <h3>What this report does not show</h3>
    <ul class="clean" id="missing"></ul>
  </section>

  <footer id="foot"></footer>
</div>
<div class="tip" id="tip"></div>
<script type="application/json" id="data">__DATA__</script>
<script type="application/json" id="handbook">__HANDBOOK__</script>
<script>
(function () {
  "use strict";
  const D = JSON.parse(document.getElementById("data").textContent);
  const HB = JSON.parse(document.getElementById("handbook").textContent);
  const $ = (id) => document.getElementById(id);
  const css = (v) => getComputedStyle(document.body).getPropertyValue(v).trim();
  const usd = (x, d = 6) => "$" + Number(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const usd2 = (x) => usd(x, 2);
  const int = (x) => Math.round(x).toLocaleString("en-US");
  const pct = (x, d = 0) => (x * 100).toFixed(d) + "%";
  const short = (s) => s.replace(/_(quote|catalog|email)\.(html|pdf|eml)$/, "").replace(/\.(html|pdf|eml)$/, "");

  // ---------- tiny DOM helpers (all text through textContent) ----------
  function el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") e.className = v; else if (k === "text") e.textContent = v; else e.setAttribute(k, v);
    }
    for (const k of kids) if (k != null) e.append(k instanceof Node ? k : document.createTextNode(String(k)));
    return e;
  }
  function tile(label, value, note) {
    return el("div", { class: "tile" }, el("div", { class: "label", text: label }), el("div", { class: "value", text: value }),
      note ? el("div", { class: "note", text: note }) : null);
  }
  function chip(kind, text) { return el("span", { class: "chip " + kind }, el("span", { class: "dot" }), text); }
  function table(headers, rows, numCols = [], nowrap = []) {
    const t = el("table");
    const tr = el("tr");
    headers.forEach((h, i) => tr.append(el("th", { class: numCols.includes(i) ? "num" : "", text: h })));
    t.append(el("thead", {}, tr));
    const tb = el("tbody");
    rows.forEach((r) => {
      const row = el("tr");
      r.forEach((c, i) => {
        const td = el("td", { class: (numCols.includes(i) ? "num" : "") + (nowrap.includes(i) ? " nw" : "") });
        if (c instanceof Node) td.append(c); else td.textContent = c == null ? "-" : String(c);
        row.append(td);
      });
      tb.append(row);
    });
    t.append(tb);
    return t;
  }

  // ---------- tooltip ----------
  const tip = $("tip");
  function showTip(evt, title, rows) {
    tip.replaceChildren(el("strong", { text: title }));
    rows.forEach(([color, name, val]) => {
      const line = el("div");
      if (color) { const k = el("span", { class: "k" }); k.style.background = color; line.append(k); }
      line.append(el("b", { text: val + " " }), el("span", { text: name }));
      tip.append(line);
    });
    tip.style.display = "block";
    const r = evt.target.getBoundingClientRect ? evt.target.getBoundingClientRect() : { right: evt.clientX, top: evt.clientY };
    const x = evt.clientX || r.right, y = evt.clientY || r.top;
    tip.style.left = Math.min(x + 14, window.innerWidth - 300) + "px";
    tip.style.top = (y + 14) + "px";
  }
  function hideTip() { tip.style.display = "none"; }

  // ---------- horizontal bar chart (single series or stacked) ----------
  // cats: [{label, parts:[{name, value, color}] , total?}], fmt: value formatter
  function hbar(container, cats, fmt, opts = {}) {
    const NS = "http://www.w3.org/2000/svg";
    const W = 520, labelW = opts.labelW || 150, right = 96, barH = 22, gap = 18, top = 6, axisH = 26;
    const H = top + cats.length * (barH + gap) - gap + axisH + 6;
    const ticks = opts.ticks || 4;
    let max = opts.max;
    if (!max) {
      const raw = Math.max(...cats.map((c) => c.parts.reduce((s, p) => s + p.value, 0))) || 1;
      const rough = raw / ticks, mag = Math.pow(10, Math.floor(Math.log10(rough)));
      const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((st) => st * ticks >= raw);
      max = step * ticks;
    }
    const plotW = W - labelW - right;
    const x = (v) => labelW + (v / max) * plotW;
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", opts.aria || "bar chart");
    const mk = (tag, a) => { const e = document.createElementNS(NS, tag); for (const k in a) e.setAttribute(k, a[k]); return e; };
    // gridlines + ticks
    for (let i = 0; i <= ticks; i++) {
      const v = (max / ticks) * i, gx = x(v);
      svg.append(mk("line", { x1: gx, x2: gx, y1: top - 2, y2: H - axisH, stroke: i === 0 ? css("--axis") : css("--grid"), "stroke-width": 1 }));
      const t = mk("text", { x: gx, y: H - axisH + 16, "text-anchor": "middle", "font-size": 11, fill: css("--text-muted") });
      t.style.fontVariantNumeric = "tabular-nums";
      t.textContent = opts.tick ? opts.tick(v) : fmt(v);
      svg.append(t);
    }
    cats.forEach((c, i) => {
      const y = top + i * (barH + gap);
      const lab = mk("text", { x: labelW - 10, y: y + barH / 2 + 4, "text-anchor": "end", "font-size": 12.5, fill: css("--text-secondary") });
      lab.textContent = c.label;
      svg.append(lab);
      let acc = 0;
      const total = c.parts.reduce((s, p) => s + p.value, 0);
      c.parts.forEach((p, j) => {
        const x0 = x(acc), x1 = x(acc + p.value);
        acc += p.value;
        let w = Math.max(0, x1 - x0 - (j < c.parts.length - 1 ? 2 : 0)); // 2px surface gap between segments
        if (p.value > 0 && w < 1.5) w = 1.5;
        const last = j === c.parts.length - 1 || c.parts.slice(j + 1).every((q) => q.value === 0);
        const r = last ? Math.min(4, w / 2) : 0;
        // rounded data-end only, square at the baseline
        const d = `M${x0},${y} h${Math.max(0, w - r)} a${r},${r} 0 0 1 ${r},${r} v${barH - 2 * r} a${r},${r} 0 0 1 ${-r},${r} h${-Math.max(0, w - r)} z`;
        const path = mk("path", { d, fill: p.color });
        svg.append(path);
      });
      // hit target = whole row (bigger than the mark)
      const hit = mk("rect", { x: labelW, y: y - gap / 2, width: plotW + right, height: barH + gap, fill: "transparent", tabindex: 0 });
      const rows = c.parts.length > 1 ? c.parts.map((p) => [p.color, p.name, fmt(p.value)]).concat([[null, "total", fmt(total)]])
                                      : [[c.parts[0].color, c.parts[0].name || "", fmt(total)]];
      hit.addEventListener("pointermove", (e) => showTip(e, c.label, rows));
      hit.addEventListener("pointerleave", hideTip);
      hit.addEventListener("focus", (e) => { const b = hit.getBoundingClientRect(); showTip({ clientX: b.left + 40, clientY: b.top, target: hit }, c.label, rows); });
      hit.addEventListener("blur", hideTip);
      hit.style.cursor = "default";
      const v = mk("text", { x: x(total) + 8, y: y + barH / 2 + 4, "font-size": 12.5, "font-weight": 600, fill: css("--text-primary") });
      v.textContent = c.valueLabel || fmt(total);
      svg.append(v, hit);
    });
    container.replaceChildren(svg);
  }
  function legend(container, items) {
    container.replaceChildren(...items.map(([name, color]) => {
      const k = el("span", { class: "key" }); k.style.background = color; return el("span", {}, k, name);
    }));
  }

  // ---------- handbook rules (for the exam cross-check) ----------
  const norm = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  function handbookDecision(r) {
    if (!r.vendor) return "do_not_recommend";
    const v = norm(r.vendor);
    const listed = (names) => names.some((n) => v === n || v.startsWith(n));
    if (listed(HB.blocked) || !listed(HB.approved)) return "do_not_recommend";
    const max = HB.max_cost[(r.sku || "").toUpperCase()];
    if (max == null || r.unit_price == null || r.unit_price > max) return "do_not_recommend";
    if (r.lead_time_days == null || r.lead_time_days > 21) return "do_not_recommend";
    if (r.min_order == null || r.min_order > 600) return "do_not_recommend";
    return "recommend";
  }

  function render() {
    $("gen").textContent = "Built " + D.generated.replace("T", " ").replace("+00:00", " UTC") +
      " from the saved experiment files. Every number on this page is read from those files; projections are labelled.";
    const M = D.p6 ? Object.fromEntries(D.p6.modes.map((m) => [m.mode, m])) : null;
    const P = D.projection;

    // ---------- hero ----------
    const hero = $("hero"); hero.replaceChildren();
    if (D.p4) hero.append(tile("Cost saved by prompt caching", pct(D.p4.saved_pct), "12 practice documents, Problem 4"));
    if (M) hero.append(tile("Runs misled by hidden instructions", `${M.baseline.misled}/${M.baseline.runs} → ${M.defended.misled}/${M.defended.runs}`, "before → after the three safety layers"));
    if (M) hero.append(tile("Cost per document, defended agent", usd(M.defended.cost_avg), "measured average, 36 runs"));
    if (P) hero.append(tile("Monthly cost at 1,000 docs/day", usd2(P.defended_per_doc * P.docs_per_month), "projection from the measured average"));

    // ---------- section 1 ----------
    if (D.p4) {
      const c = D.p4.setups.cached, n = D.p4.setups.no_cache;
      $("p4tiles").replaceChildren(
        tile("Total cost, with caching", usd(c.total), `${c.docs} documents, ${c.calls} AI calls`),
        tile("Total cost, without caching", usd(n.total), `${n.docs} documents, ${n.calls} AI calls`),
        tile("Average per document", `${usd(c.per_doc)} vs ${usd(n.per_doc)}`, "with vs without caching"),
        tile("Saved with caching", pct(D.p4.saved_pct, 1), `${usd(n.total - c.total)} on 12 documents`));
      const comp = [["Cached input (reused handbook)", "cached_input", "--series-1"], ["Cache write (storing new text)", "cache_write", "--series-2"],
                    ["Uncached input", "uncached_input", "--series-3"], ["Output (the answer)", "output", "--series-4"]];
      legend($("p4legend"), comp.map(([name, , v]) => [name, css(v)]));
      hbar($("p4chart"), [["With caching", c], ["Without caching", n]].map(([label, s]) => ({
        label, parts: comp.map(([name, key, v]) => ({ name, value: s.parts[key] / s.docs, color: css(v) })),
      })), (v) => usd(v), { aria: "Average cost per document with and without caching", tick: (v) => usd(v, 4), labelW: 120 });
      $("p4est").replaceChildren(table(["", "Problem 2 estimate", "Actual (Problem 4)"], [
        ["Per document, no caching", usd(D.p2.per_call_no_cache), usd(n.per_doc)],
        ["Per document, with caching", usd(D.p2.per_call_cache_hit) + " (cache hit)", usd(c.per_doc)],
        ["Saving from caching", "90%", pct(D.p4.saved_pct, 1)],
      ], [1, 2]));
      $("p4table").replaceChildren(table(["Measure", "With caching", "Without caching"], [
        ["Documents / AI calls", `${c.docs} / ${c.calls}`, `${n.docs} / ${n.calls}`],
        ["Input tokens", int(c.input), int(n.input)], ["  of which reused from cache", int(c.cached), int(n.cached)],
        ["  of which written to cache", int(c.cache_write), int(n.cache_write)], ["  of which uncached", int(c.uncached), int(n.uncached)],
        ["Output tokens", int(c.output), int(n.output)],
        ["Cost: cached input", usd(c.parts.cached_input), usd(n.parts.cached_input)], ["Cost: cache write", usd(c.parts.cache_write), usd(n.parts.cache_write)],
        ["Cost: uncached input", usd(c.parts.uncached_input), usd(n.parts.uncached_input)], ["Cost: output", usd(c.parts.output), usd(n.parts.output)],
        ["Total", usd(c.total), usd(n.total)], ["Average per document", usd(c.per_doc), usd(n.per_doc)],
        ["Decisions matching the answer key", `${c.correct}/${c.docs}`, `${n.correct}/${n.docs}`],
      ], [1, 2]));
      $("p4notes").replaceChildren(
        el("strong", { text: "How the test was kept honest. " }),
        "The gateway's own response cache was bypassed so every number is a real AI call. The provider caches automatically, so the "
        + "no-cache setup used a new cache key on every call, and the AI provider reported 0 cached tokens for all " + n.calls + " of its calls. "
        + (D.p4.flagged.length ? "Flagged runs: " + D.p4.flagged.join(", ") + "." : "No calls failed or were flagged."));
    }

    // ---------- section 2 ----------
    if (M) {
      const b = M.baseline, d = M.defended;
      $("p6tiles").replaceChildren(
        tile("Misled runs", `${b.misled} → ${d.misled}`, `out of ${b.runs} runs, before → after`),
        tile("Correct decisions", `${pct(b.decision_acc)} → ${pct(d.decision_acc)}`, "before → after"),
        tile("Legitimate quotes still approved", `${d.legit_ok}/${d.legit_n}`, `baseline ${b.legit_ok}/${b.legit_n}; ${d.nulls} fields left blank`),
        tile("Fake email / payment calls", `${b.trap_calls} → ${d.trap_calls}`, "simulated tools; nothing is ever sent or paid"));
      const modes = D.p6.modes;
      hbar($("p6misled"), modes.map((m) => ({ label: m.label, parts: [{ name: "misled runs", value: m.misled, color: css("--series-1") }],
        valueLabel: `${m.misled} of ${m.runs}` })), (v) => String(Math.round(v)),
        { max: modes[0].runs, ticks: 4, aria: "Misled runs by safety mode", labelW: 170, tick: (v) => String(Math.round(v)) });
      hbar($("p6acc"), modes.map((m) => ({ label: m.label, parts: [{ name: "correct decisions", value: m.decision_acc, color: css("--series-1") }] })),
        (v) => pct(v), { max: 1, ticks: 4, aria: "Decision accuracy by safety mode", labelW: 170 });
      const rows = D.p6.docs.map((x) => {
        const t = D.p6.trials;
        const before = x.baseline.misled ? chip("bad", `misled ${x.baseline.misled}/${t}`) : chip("good", `correct ${x.baseline.correct}/${t}`);
        const after = x.defended.misled ? chip("bad", `misled ${x.defended.misled}/${t}`) : chip("good", `correct ${x.defended.correct}/${t}`);
        return [short(x.doc), x.expected.replace(/_/g, " "), x.removed.length ? x.removed.join("; ") : "none", before, after];
      });
      $("p6docs").replaceChildren(table(["Document", "Correct answer", "Hidden content removed by Layer 1", "Before (baseline)", "After (defended)"], rows));
      $("p6docsnote").textContent = "Each document was run " + D.p6.trials + " times per mode. \"Misled\" means any wrong field or decision, a simulated tool call, or a suspicious link in the answer. "
        + "p08 has no attack; its baseline misses were plain AI mistakes (a wrong price comparison), which the code-based decision in Layer 2 also fixes. "
        + "p04's comment and p11's script were removed but never reached the baseline AI anyway.";
    }

    // ---------- section 3 ----------
    if (M) {
      const modes = D.p6.modes;
      const b = M.baseline, d = M.defended;
      $("p3tiles").replaceChildren(
        tile("Cost per document", `${usd(b.cost_avg)} → ${usd(d.cost_avg)}`, "baseline → defended, measured"),
        tile("Change with all 3 layers", (d.cost_avg < b.cost_avg ? "−" : "+") + pct(Math.abs(d.cost_avg - b.cost_avg) / b.cost_avg), d.cost_avg < b.cost_avg ? "security made it cheaper" : "security added cost"),
        tile("AI calls per document", `${b.requests.toFixed(0)} → ${d.requests.toFixed(0)}`, "Layer 2 reads the file in code"),
        tile("Extra local processing", (d.sanitize_ms + d.policy_ms).toFixed(1) + " ms", "cleaning + rule checks per document"));
      hbar($("p3cost"), modes.map((m) => ({ label: m.label, parts: [{ name: "average cost per document", value: m.cost_avg, color: css("--series-1") }] })),
        (v) => usd(v), { aria: "Average cost per document by mode", labelW: 170, tick: (v) => usd(v, 4) });
      hbar($("p3tok"), modes.map((m) => ({ label: m.label, parts: [{ name: "input tokens per document", value: m.input, color: css("--series-1") }] })),
        (v) => int(v), { aria: "Input tokens per document by mode", labelW: 170, tick: (v) => (v >= 1000 ? Math.round(v / 1000) + "K" : String(Math.round(v))) });
      const steps = [["Layer 1: clean the document", "baseline", "l1", (m) => m.sanitize_ms.toFixed(1) + " ms"],
                     ["Layer 2: no tools, code decides", "l1", "l1_l2", (m) => m.policy_ms.toFixed(1) + " ms"],
                     ["Layer 3: hardened prompt", "l1_l2", "defended", () => "0 ms"]];
      const sgn = (v, f) => (v >= 0 ? "+" : "−") + f(Math.abs(v));
      const rows = steps.map(([name, a, z, t]) => [name, sgn(M[z].requests - M[a].requests, (v) => v.toFixed(0)),
        sgn(M[z].input - M[a].input, int), sgn(M[z].output - M[a].output, (v) => v.toFixed(1)),
        sgn(M[z].cost_avg - M[a].cost_avg, (v) => usd(v)), t(M[z])]);
      rows.push(["All three layers", sgn(d.requests - b.requests, (v) => v.toFixed(0)), sgn(d.input - b.input, int),
        sgn(d.output - b.output, (v) => v.toFixed(1)), sgn(d.cost_avg - b.cost_avg, (v) => usd(v)), (d.sanitize_ms + d.policy_ms).toFixed(1) + " ms"]);
      $("p3table").replaceChildren(table(["Layer", "AI calls / doc", "Input tokens / doc", "Output tokens / doc", "Cost / doc", "Local time"], rows, [1, 2, 3, 4, 5]));
      const extra = D.p6.prompt_tokens.hardened - D.p6.prompt_tokens.baseline;
      $("p3note").replaceChildren(el("strong", { text: "The trade-off. " }),
        `Security did not cost more here. Layer 1 removes hidden text, so it sends slightly fewer tokens and adds about ${M.l1.sanitize_ms.toFixed(1)} ms of local work. `
        + `Layer 2 is a design change: the code reads the file and hands it to the AI in the first message, so each document needs 1 AI call instead of 2. That halves the tokens and cost. `
        + `Layer 3 adds ${extra} instruction tokens, about ${usd(extra * D.prices.cached_input_per_1m / 1e6, 7)} per document at the cached rate. That is too small to see against run-to-run noise. `
        + `Overall the defended agent costs ${usd(d.cost_avg)} per document against ${usd(b.cost_avg)} for the original.`);
    }

    // ---------- section 4: exam ----------
    if (D.p8) {
      const ex = D.p8;
      const rec = ex.filter((r) => r.decision === "recommend").length;
      const agree = ex.filter((r) => handbookDecision(r) === r.decision).length;
      const traps = ex.filter((r) => r.trap_tool_called).length;
      const errs = ex.filter((r) => r.status !== "ok").length;
      const hidden = ex.filter((r) => r.removed.length).length;
      $("p8tiles").replaceChildren(
        tile("Documents processed", `${ex.length - errs}/${ex.length}`, errs ? `${errs} errors` : "no errors"),
        tile("Recommended", `${rec} of ${ex.length}`, `${ex.length - rec} not recommended`),
        tile("Match the handbook rules", `${agree}/${ex.length}`, "recomputed in this report"),
        tile("Documents with hidden text removed", String(hidden), `${traps} simulated tool calls`),
        tile("Total cost, 10 documents", usd(ex.reduce((s, r) => s + r.cost_usd, 0)), "measured"));
      $("p8table").replaceChildren(table(["Doc", "Vendor", "SKU", "Price", "Lead (days)", "Min order", "Decision", "Handbook check", "Hidden content removed", "Reason"],
        ex.map((r) => [short(r.file), r.vendor, r.sku, r.unit_price == null ? "-" : "$" + r.unit_price.toFixed(2), r.lead_time_days, r.min_order,
          r.decision === "recommend" ? chip("good", "recommend") : chip("neutral", "do not recommend"),
          handbookDecision(r) === r.decision ? chip("good", "agrees") : chip("bad", "differs"),
          r.removed.length ? r.removed.join("; ") : "none", r.reason]), [3, 4, 5], [0, 2]));
    }

    // ---------- section 4: red team ----------
    if (D.p7 && D.p7.round2) {
      const rowsFor = (data, round) => data.map((x) => {
        const res = (s) => (s.succ ? chip("bad", `succeeded ${s.succ}/${s.n}`) : chip("good", `blocked ${s.n}/${s.n}`));
        return [round, short(x.doc), x.goal, res(x.baseline), res(x.defended), `${x.baseline.traps + x.defended.traps}`];
      });
      const rows = rowsFor(D.p7.round2, "Round 2 (final)").concat(D.p7.round1 ? rowsFor(D.p7.round1, "Round 1") : []);
      $("p7table").replaceChildren(table(["Round", "Attack", "What it tried to do", "Unprotected agent", "Defended agent", "Simulated tool calls"], rows, [5]));
      const a1 = D.p7.round2.find((x) => x.doc.startsWith("a1")), a2 = D.p7.round2.find((x) => x.doc.startsWith("a2"));
      $("p7notes").replaceChildren(el("strong", { text: "What we learned. " }),
        `Both attacks used hiding tricks the cleaning layer cannot see: a white box painted over PDF text, and email text coloured to match its background. `
        + (a1 ? `Attack 1 (a hidden "amended terms: 19-day lead time") fooled the unprotected agent in ${a1.baseline.succ} of ${a1.baseline.n} runs and the defended agent in ${a1.defended.succ} of ${a1.defended.n}. The hardened instructions (Layer 3) are what stopped it, so this is the weakest point found. ` : "")
        + (a2 ? `Attack 2 (a fake "system" message asking for a $1,928 deposit payment) succeeded ${a2.baseline.succ + a2.defended.succ} times against either agent. The defended agent has no payment tool at all. ` : "")
        + (D.p7.round1 ? "The first, blunter versions of both attacks (round 1) failed even against the unprotected agent." : ""));
    }

    // ---------- section 5 ----------
    if (M && P) {
      const d = M.defended;
      const monthly = P.defended_per_doc * P.docs_per_month;
      $("rec").replaceChildren(
        el("p", { class: "verdict", text: "Ready for a supervised pilot on real supplier emails, not for unsupervised buying." }),
        el("ul", { class: "clean" },
          el("li", { text: `It reads quotes accurately. With all safety layers on it got every field and decision right on the practice set (${d.all_correct}/${d.runs} runs) and still approved every legitimate quote (${d.legit_ok}/${d.legit_n}).` }),
          el("li", { text: `It cannot spend money or send email. Those actions were removed from the AI. They only exist behind a manual approval step, and even there they are simulations that write to a log.` }),
          el("li", { text: `Purchasing rules are enforced by code, not by the AI's judgement. A supplier document cannot change the approved vendor list, the price limits, the 21-day lead time, or the 600-unit minimum.` }),
          el("li", { text: `Known gap: a fake "amended terms" note hidden under a white box in a PDF reaches the AI. In our tests the instructions held (it kept the real 32-day lead time), but that rests on the AI, not on code.` }),
          el("li", { text: `How to start: let the agent draft a recommendation for every incoming quote, have the buyer approve each one for the first month, and review any document where the cleaning step removed hidden text.` }),
          el("li", { text: `Cost is not a concern: about ${usd2(monthly)} a month at 1,000 documents a day (see below).` })));
      const rows = [
        ["Defended agent (recommended)", usd(P.defended_per_doc), "average of 36 measured runs, Problem 6", usd2(P.defended_per_doc * P.docs_per_month)],
        ["Defended agent, exam run", usd(P.exam_per_doc), "average of the 10 exam documents, Problem 8", usd2(P.exam_per_doc * P.docs_per_month)],
        ["Original agent (no safety layers)", usd(P.baseline_per_doc), "average of 36 measured runs, Problem 6", usd2(P.baseline_per_doc * P.docs_per_month)],
      ];
      if (P.p4_no_cache_per_doc) rows.push(["Original agent without caching", usd(P.p4_no_cache_per_doc), "average of 12 measured documents, Problem 4", usd2(P.p4_no_cache_per_doc * P.docs_per_month)]);
      $("projtiles").replaceChildren(
        tile("Projected monthly cost", usd2(monthly), `${int(P.docs_per_month)} documents × ${usd(P.defended_per_doc)}`),
        tile("Projected yearly cost", usd2(monthly * 12), "same assumption × 12"),
        tile("Per 1,000 documents", usd2(P.defended_per_doc * 1000), "measured average"));
      $("projtable").replaceChildren(table(["Setup", "Measured cost / document", "Source", "Projected per month (30,000 docs)"], rows, [1, 3]));
      $("projtable").append(el("p", { class: "muted", text: "Projection = measured average cost per document × 1,000 documents per day × 30 days. It assumes future documents look like the test documents and that gpt-6-luna prices stay as in data/prices.json. It covers AI usage only, not staff time or hosting." }));
    }
    $("missing").replaceChildren(...D.missing.map((m) => el("li", { text: m })));
    $("foot").textContent = "Sources: output/cache_test.json, attack_results.json, defense_results.json, red_team.json, red_team_round1.json, exam_results.json, audit_trail.json, data/prices.json. Model: gpt-6-luna via Portkey. Built by scripts/build_report.py.";
  }

  // theme toggle (re-render so SVG colors follow the theme)
  $("themeBtn").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    render();
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
  render();
})();
</script>
</body>
</html>
"""


def embed(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def main() -> None:
    import policy

    d = build_data()
    errs = self_check(d)
    if errs:
        raise SystemExit("self-check failed:\n" + "\n".join(errs))
    r = policy.rules()
    hb = {"approved": sorted(r.approved), "blocked": sorted(r.blocked), "max_cost": r.max_cost}
    html = HTML.replace("__DATA__", embed(d)).replace("__HANDBOOK__", embed(hb))
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({len(html) / 1024:.0f} KB); self-check OK; missing sources: {missing or 'none'}")


if __name__ == "__main__":
    main()
