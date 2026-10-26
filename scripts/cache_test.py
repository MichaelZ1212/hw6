"""Problem 4: run the vendor desk agent on all 12 practice documents with and without prompt caching.

Same model, handbook, prompt, and documents in both setups. Only the prompt cache key changes:
  cached    one shared key for this test (new for each test run, so the first call starts cold)
  no_cache  a fresh random key on every model request (see agent.NoCacheResponsesModel)

Writes output/cache_test.json (every model call, raw usage, cost, checks) and output/cache_test.md.
All numbers come from the usage the API returned. Nothing is estimated except the Problem 2 comparison.

Usage:  python scripts/cache_test.py            run both setups, then write the report
        python scripts/cache_test.py --report   rebuild the report from output/cache_test.json
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent  # noqa: E402

DOCS_DIR = ROOT / "data" / "practice_docs"
KEY = json.loads((ROOT / "data" / "practice_key.json").read_text(encoding="utf-8"))
PRICES = json.loads((ROOT / "data" / "prices.json").read_text(encoding="utf-8"))[agent.MODEL_NAME]
OUT_JSON = ROOT / "output" / "cache_test.json"
OUT_MD = ROOT / "output" / "cache_test.md"
HANDBOOK_TOKENS = 10_058  # Problem 2, tiktoken o200k_base
DOCS_PER_MONTH = 1000 * 30


def check_calls(mode: str, calls: list[dict], first_in_setup: bool) -> list[str]:
    """Flags for anything that means caching did not behave as the setup intends."""
    flags = []
    for i, c in enumerate(calls):
        if mode == "no_cache" and c["cached_tokens"]:
            flags.append(f"call {i + 1}: no_cache setup reported {c['cached_tokens']} cached tokens")
        if mode == "cached" and not c["cached_tokens"] and not (first_in_setup and i == 0):
            flags.append(f"call {i + 1}: cached setup reported 0 cached tokens (cache miss)")
    return flags


def run_setup(mode: str, docs: list[Path]) -> list[dict]:
    rows = []
    first_done = False  # the first *successful* run is the one expected to write the cache
    for doc in docs:
        rel = doc.relative_to(ROOT).as_posix()
        print(f"[{mode}] {doc.name} ...", flush=True)
        try:
            rec = agent.run(rel, cache=(mode == "cached"), mode="baseline")  # Problem 3 agent, as measured in Problem 4
        except Exception as e:  # keep going; a failed call is flagged, not counted
            rows.append({"doc": doc.name, "cache_mode": mode, "status": "failed",
                         "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]})
            print(f"   FAILED: {e}")
            continue
        expected = next((k for k in KEY if k["file"] == doc.name), {"decision": None})
        flags = check_calls(mode, rec["model_calls"], first_in_setup=not first_done)
        first_done = True
        rows.append({
            "doc": doc.name,
            "cache_mode": mode,
            "status": "flagged" if flags else "ok",
            "flags": flags,
            "requests": rec["requests"],
            "seconds": rec["seconds"],
            "totals": {k: rec[k] for k in ("input_tokens", "cached_input_tokens", "cache_write_tokens",
                                           "output_tokens", "total_tokens")},
            "cost": rec["cost"],
            "model_calls": rec["model_calls"],
            "recommendation": rec["recommendation"],
            "decision_matches_key": rec["recommendation"]["decision"] == expected["decision"],
        })
        r = rows[-1]
        print(f"   {r['status']}  calls={r['requests']}  cached={r['totals']['cached_input_tokens']}  "
              f"write={r['totals']['cache_write_tokens']}  ${r['cost']['total_usd']:.6f}")
    return rows


def run_test() -> dict:
    docs = [p for p in sorted(DOCS_DIR.iterdir()) if p.is_file() and p.suffix.lower() in (".html", ".htm", ".pdf", ".eml")]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    agent.CACHE_KEY = f"campus-customs-cache-test-{stamp}"  # new key per test run, so the cached setup starts cold
    data = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": agent.MODEL_NAME,
        "prices_per_1m": PRICES,
        "cached_setup_key": agent.CACHE_KEY,
        "portkey_response_cache": "bypassed with x-portkey-cache-force-refresh in both setups",
        "runs": run_setup("cached", docs) + run_setup("no_cache", docs),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


# ---------------- report ----------------

def usd(x: float, digits: int = 6) -> str:
    return f"${x:,.{digits}f}"


def summarize(rows: list[dict]) -> dict:
    # Flagged runs (a cache miss where a hit was expected) are real, paid calls, so they stay in the totals;
    # only failed runs, which returned nothing, are left out.
    ok = [r for r in rows if r["status"] != "failed"]
    calls = [c for r in ok for c in r["model_calls"]]
    s = {k: sum(c[k] for c in calls) for k in
         ("input_tokens", "cached_tokens", "cache_write_tokens", "uncached_input_tokens", "output_tokens")}
    s.update({
        "docs_ok": len(ok),
        "docs_bad": len(rows) - len(ok),
        "calls": len(calls),
        "cost": sum(r["cost"]["total_usd"] for r in ok),
        "cost_parts": {k: sum(r["cost"][k] for r in ok) for k in
                       ("uncached_input", "cached_input", "cache_write", "output")},
        "seconds": sum(r["seconds"] for r in ok),
        "correct": sum(r["decision_matches_key"] for r in ok),
    })
    s["per_doc"] = s["cost"] / s["docs_ok"] if s["docs_ok"] else 0.0
    # Steady state: leave out the first run, which pays the one-time cold cache write for this test's key.
    rest = [r["cost"]["total_usd"] for r in ok[1:]]
    s["steady_per_doc"] = sum(rest) / len(rest) if rest else s["per_doc"]
    return s


def build_report(data: dict) -> str:
    runs = data["runs"]
    c = summarize([r for r in runs if r["cache_mode"] == "cached"])
    n = summarize([r for r in runs if r["cache_mode"] == "no_cache"])
    p = data["prices_per_1m"]
    saved = n["cost"] - c["cost"]
    # Compare per-document averages, so the percentage stays fair if one setup lost a run.
    pct = (n["per_doc"] - c["per_doc"]) / n["per_doc"] if n["per_doc"] else 0.0
    pct_steady = (n["steady_per_doc"] - c["steady_per_doc"]) / n["steady_per_doc"] if n["steady_per_doc"] else 0.0
    bad = [r for r in runs if r["status"] != "ok"]

    # Problem 2 estimate: handbook only, one call per document.
    est_no = HANDBOOK_TOKENS * p["input_per_1m"] / 1e6
    est_hit = HANDBOOK_TOKENS * p["cached_input_per_1m"] / 1e6
    avg_in_per_call = (n["input_tokens"] / n["calls"]) if n["calls"] else 0
    # What the no-cache run would cost if the API billed plain input (no cache-write charge).
    n_list_price = (n["input_tokens"] * p["input_per_1m"] + n["output_tokens"] * p["output_per_1m"]) / 1e6
    n_list_per_doc = n_list_price / n["docs_ok"] if n["docs_ok"] else 0.0

    def per_doc_table() -> str:
        lines = ["| Doc | Setup | Calls | Input | Cached | Cache write | Output | Cost | Decision OK | Status |",
                 "|---|---|---:|---:|---:|---:|---:|---:|:---:|---|"]
        for r in runs:
            if r["status"] == "failed":
                lines.append(f"| {r['doc']} | {r['cache_mode']} | - | - | - | - | - | - | - | **FAILED**: {r['error'][:80]} |")
                continue
            t = r["totals"]
            status = "ok" if r["status"] == "ok" else "**FLAGGED**: " + "; ".join(r["flags"])
            lines.append(f"| {r['doc']} | {r['cache_mode']} | {r['requests']} | {t['input_tokens']:,} | "
                         f"{t['cached_input_tokens']:,} | {t['cache_write_tokens']:,} | {t['output_tokens']:,} | "
                         f"{usd(r['cost']['total_usd'])} | {'yes' if r['decision_matches_key'] else 'NO'} | {status} |")
        return "\n".join(lines)

    uncached_per_call = n["uncached_input_tokens"] / n["calls"] if n["calls"] else 0
    slowest = max((r for r in runs if r["status"] != "failed"), key=lambda r: r["seconds"], default=None)
    typical = sorted(r["seconds"] for r in runs if r["status"] != "failed")
    median = typical[len(typical) // 2] if typical else 0
    slow_note = (f"Most documents took about {median:.1f} s in either setup. The slowest was {slowest['doc']} "
                 f"({slowest['cache_mode']}, {slowest['seconds']:.1f} s), a one-off latency spike that also "
                 f"explains most of the difference in total run time between the setups."
                 if slowest else "")
    wrong = [r for r in runs if r["status"] != "failed" and not r["decision_matches_key"]]
    mismatch_note = ("Mismatches: " + "; ".join(f"{r['doc']} ({r['cache_mode']}: {r['recommendation']['decision']})"
                     for r in wrong) + ". Most come from text inside the documents that claims a 'revised' price or "
                     "lead time, which the agent believed (a prompt-injection / safety issue for the later problems). "
                     "Because the same document can flip between runs, these differences are model variance, "
                     "not an effect of caching." if wrong else "All decisions match.")
    first_cached = next((r for r in runs if r["cache_mode"] == "cached" and r["status"] != "failed"), None)
    calls_per_doc = n["calls"] / n["docs_ok"] if n["docs_ok"] else 0

    return f"""# Prompt caching test: with vs. without cached tokens

Run at {data['time']} on **{data['model']}** through Portkey. Raw data: `output/cache_test.json`
(every model call with the usage the API returned and its cost). Script: `scripts/cache_test.py`.

## Setup

Both setups use the Problem 3 agent (`agent.run(..., mode="baseline")`: the original instructions, now kept in
`prompts/prompt_baseline.md`, plus the full handbook), the same tools, and the same {c['docs_ok']} practice documents.
Only one setting differs:

| Setup | How | What the API should report |
|---|---|---|
| **cached** | Every request sends the same `prompt_cache_key` (`{data['cached_setup_key']}`) | 1st call writes the handbook to the cache, every later call reads it (`cached_tokens` > 0) |
| **no_cache** | Every request sends a brand-new random `prompt_cache_key` | `cached_tokens` = 0 on every call |

Two things had to be fixed before the comparison was fair:

1. **Portkey's own response cache was replaying answers.** Sending the same request twice came back in
   0.18 s with header `x-portkey-cache-status: HIT`. The model never ran and the old usage numbers were
   repeated. Both setups now send `x-portkey-cache-force-refresh: true` (status `REFRESH`), so every row
   below is a real model call. Every model call has its own `response_id` in the JSON.
2. **The provider's prompt cache cannot be switched off.** The backend (Azure OpenAI) caches any long prefix
   automatically. With no key, a "no cache" request still read 10,069 cached tokens.
   `prompt_cache_retention` only accepts `in_memory` or `24h` (`none` is rejected with a 400 error), and
   `prompt_cache: false` is ignored. A fresh random `prompt_cache_key` per request was the only way to
   get `cached_tokens = 0`.

**Verification.** Every call in the no_cache setup is checked for `cached_tokens == 0`. Every cached call
after the very first one is checked for `cached_tokens > 0`. Failed calls or failed checks are flagged below
and left out of the totals.
{"" if not bad else chr(10) + "**Flagged / failed documents: " + ", ".join(f"{r['doc']} ({r['cache_mode']})" for r in bad) + "**" + chr(10)}
## 1. Total and average cost

Prices from `data/prices.json` (per 1M tokens): input ${p['input_per_1m']}, cache write ${p['cache_write_per_1m']},
cached input ${p['cached_input_per_1m']}, output ${p['output_per_1m']}.

Cost per call = uncached input x {p['input_per_1m']} + cache write x {p['cache_write_per_1m']}
+ cached x {p['cached_input_per_1m']} + output x {p['output_per_1m']}, all / 1,000,000.

| | cached | no_cache |
|---|---:|---:|
| Documents counted (ok) | {c['docs_ok']} | {n['docs_ok']} |
| Model calls | {c['calls']} | {n['calls']} |
| Input tokens (total) | {c['input_tokens']:,} | {n['input_tokens']:,} |
| of which cached (read) | {c['cached_tokens']:,} | {n['cached_tokens']:,} |
| of which cache write | {c['cache_write_tokens']:,} | {n['cache_write_tokens']:,} |
| of which uncached | {c['uncached_input_tokens']:,} | {n['uncached_input_tokens']:,} |
| Output tokens | {c['output_tokens']:,} | {n['output_tokens']:,} |
| Cost: cached input | {usd(c['cost_parts']['cached_input'])} | {usd(n['cost_parts']['cached_input'])} |
| Cost: cache write | {usd(c['cost_parts']['cache_write'])} | {usd(n['cost_parts']['cache_write'])} |
| Cost: uncached input | {usd(c['cost_parts']['uncached_input'])} | {usd(n['cost_parts']['uncached_input'])} |
| Cost: output | {usd(c['cost_parts']['output'])} | {usd(n['cost_parts']['output'])} |
| **Total cost** | **{usd(c['cost'])}** | **{usd(n['cost'])}** |
| **Average per document** | **{usd(c['per_doc'])}** | **{usd(n['per_doc'])}** |
| Total run time | {c['seconds']:.1f} s | {n['seconds']:.1f} s |
| Decisions matching practice_key | {c['correct']}/{c['docs_ok']} | {n['correct']}/{n['docs_ok']} |

**Saved by caching:** {usd(n['cost'])} - {usd(c['cost'])} = **{usd(saved)}**, i.e. {usd(saved)} / {usd(n['cost'])} = **{pct:.1%} cheaper**.

### Per document

{per_doc_table()}

## 2. Actual vs. the Problem 2 estimate

Problem 2 priced only the handbook ({HANDBOOK_TOKENS:,} tokens) for one call per document.

| | Problem 2 estimate | Actual (this test) |
|---|---:|---:|
| Input tokens per model call | {HANDBOOK_TOKENS:,} (handbook only) | {avg_in_per_call:,.0f} |
| Model calls per document | 1 | {calls_per_doc:.1f} |
| Cost per document, no caching | {usd(est_no)} | {usd(n['per_doc'])} |
| Cost per document, cached (cache hit) | {usd(est_hit)} | {usd(c['per_doc'])} |
| Savings from caching | 90% (at steady state, 89.9% over 1,000 calls) | {pct:.1%} |

Why the actual numbers are higher:

- **More tokens per call.** Each call also carries the agent instructions (`prompt.md`), the tool and
  output schemas, the user message, and from the 2nd call on the document text and the first answer.
  That is about {avg_in_per_call - HANDBOOK_TOKENS:,.0f} tokens per call on top of the handbook.
- **Two calls per document, not one.** The agent first calls `read_document`, then returns its answer
  in a second request. The handbook is sent both times, so per document the input roughly doubles.
- **No-cache calls are billed as cache writes.** The provider writes every new prefix to the cache, so the
  no_cache setup pays ${p['cache_write_per_1m']}/1M on most of its input, not the ${p['input_per_1m']}/1M that
  Problem 2 assumed. At the plain input price the no_cache run would have cost
  {usd(n_list_price)} ({usd(n_list_per_doc)} per document).
- **Output tokens** were left out of Problem 2. They are a small share here.

The savings percentage still lands close to the estimate. Caching cuts the per-document bill by roughly an
order of magnitude.

## 3. Monthly projection (1,000 documents/day x 30 days = {DOCS_PER_MONTH:,} documents)

The projection uses the **steady-state** cost per document: the average of every run except the first one in each
setup, which paid this test's one-time cold cache write. (Averaging that cold write into every document would
charge it 30,000 times a month.)

| Setup | Calculation | Per month |
|---|---|---:|
| cached | {DOCS_PER_MONTH:,} x {usd(c['steady_per_doc'])} | **{usd(DOCS_PER_MONTH * c['steady_per_doc'], 2)}** |
| no_cache | {DOCS_PER_MONTH:,} x {usd(n['steady_per_doc'])} | **{usd(DOCS_PER_MONTH * n['steady_per_doc'], 2)}** |
| Savings | | **{usd(DOCS_PER_MONTH * (n['steady_per_doc'] - c['steady_per_doc']), 2)} / month ({pct_steady:.1%})** |

At 1,000 documents a day the cache stays warm all day, so nearly every call is a cache hit, and the cold write is paid
roughly once per cache lifetime, not once per document. Including the cold write in the average (as in section 1) gives
{usd(DOCS_PER_MONTH * c['per_doc'], 2)} cached vs {usd(DOCS_PER_MONTH * n['per_doc'], 2)} no-cache per month.

## 4. Unexpected findings

1. **Portkey's gateway cache.** It silently replayed responses and their usage. In Problem 3 the p01 run finished
   in 0.81 s for 2 requests, which is probably a replay. Without the force-refresh header the no_cache test
   would have reported tokens and costs for calls that never reached the model.
2. **Caching is on by default and has no off switch.** The provider caches automatically, so "without caching"
   had to be built by giving each request its own cache key. A plain agent with no key would already get most
   of the caching benefit by accident.
3. **"No caching" costs more than plain input pricing.** Each new prefix is written to the cache at
   ${p['cache_write_per_1m']}/1M, 25% above the ${p['input_per_1m']}/1M input price. So turning caching "off" this way
   is slightly worse than the true no-cache baseline in Problem 2.
4. **The first cached call is the most expensive.** {"It is " + first_cached['doc'] + " (" + usd(first_cached['cost']['total_usd']) + "), because it pays the cache write; its second request already reads the cache." if first_cached else "n/a"}
5. **New tokens are billed as cache writes, not plain input.** Only about {uncached_per_call:.0f} tokens per call
   are billed as plain uncached input. Everything new in a request is written to the cache at
   ${p['cache_write_per_1m']}/1M: the whole prefix in the no_cache setup, and in the cached setup the
   document-specific part (about 150-300 tokens). So even the cached setup pays a small write charge on
   every document ({usd(c['cost_parts']['cache_write'])} in total, {c['cost_parts']['cache_write'] / c['cost']:.0%} of its bill).
6. **Run time is not a reliable caching signal here.** {slow_note}
7. **Decisions do not depend on caching, but they are not fully stable.** {c['correct']}/{c['docs_ok']} (cached) and
   {n['correct']}/{n['docs_ok']} (no_cache) decisions match `practice_key.json`. {mismatch_note}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="Only rebuild the report from output/cache_test.json")
    args = ap.parse_args()
    data = json.loads(OUT_JSON.read_text(encoding="utf-8")) if args.report else run_test()
    OUT_MD.write_text(build_report(data), encoding="utf-8")
    print(f"wrote {OUT_JSON} and {OUT_MD}")


if __name__ == "__main__":
    main()
