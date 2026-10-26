"""Problem 8: run the defended agent (all three layers) on every file in data/exam_docs/.

One entry per exam document, written straight from the agent run (no manual edits). Field names follow
data/practice_key.json, plus the reason, trap-tool check, and real token usage / cost.
Errors are recorded as entries with "status": "error"; documents are never skipped silently.

Writes output/exam_results.json (and prints a validation summary).

Usage:  python scripts/run_exam.py
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent  # noqa: E402
from tools import TRAP_LOG, load_json_list  # noqa: E402

EXAM_DIR = ROOT / "data" / "exam_docs"
OUT = ROOT / "output" / "exam_results.json"
MODE = "defended"

FIELD_TYPES = {
    "file": str,
    "vendor": (str, type(None)),
    "sku": (str, type(None)),
    "unit_price": (float, type(None)),
    "lead_time_days": (int, type(None)),
    "min_order": (int, type(None)),
    "decision": str,
    "reason": str,
    "trap_tool_called": bool,
    "trap_calls": list,
    "input_tokens": int,
    "cached_tokens": int,
    "output_tokens": int,
    "cost_usd": float,
    "status": str,
}


def run_one(doc: Path) -> dict:
    rel = doc.relative_to(ROOT).as_posix()
    before = len(load_json_list(TRAP_LOG))
    try:
        rec = agent.run(rel, mode=MODE)
        error = None
    except Exception as e:  # report, never skip
        rec, error = None, f"{type(e).__name__}: {e}"
        traceback.print_exc()
    trap = load_json_list(TRAP_LOG)[before:]
    if rec is None:
        return {"file": doc.name, "vendor": None, "sku": None, "unit_price": None, "lead_time_days": None,
                "min_order": None, "decision": "error", "reason": error, "trap_tool_called": bool(trap),
                "trap_calls": trap, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0,
                "cost_usd": 0.0, "status": "error"}
    out = rec["recommendation"]
    return {
        "file": doc.name,
        "vendor": out["vendor"],
        "sku": out["sku"],
        "unit_price": None if out["unit_price"] is None else float(out["unit_price"]),
        "lead_time_days": out["lead_time_days"],
        "min_order": out["min_order"],
        "decision": out["decision"],
        "reason": out["reason"],
        "trap_tool_called": bool(trap),
        "trap_calls": trap,
        "input_tokens": rec["input_tokens"],
        "cached_tokens": rec["cached_input_tokens"],
        "output_tokens": rec["output_tokens"],
        "cost_usd": float(rec["cost"]["total_usd"]),
        "status": "ok",
    }


def validate(results: list[dict], docs: list[Path]) -> list[str]:
    problems = []
    if len(results) != len(docs):
        problems.append(f"{len(results)} entries for {len(docs)} documents")
    if sorted(r["file"] for r in results) != sorted(d.name for d in docs):
        problems.append("file names do not match data/exam_docs/")
    for r in results:
        missing = set(FIELD_TYPES) - set(r)
        if missing:
            problems.append(f"{r.get('file')}: missing {sorted(missing)}")
        for f, t in FIELD_TYPES.items():
            if f in r and not isinstance(r[f], t):
                problems.append(f"{r['file']}: {f} has type {type(r[f]).__name__}")
        if r.get("status") == "error":
            problems.append(f"{r['file']}: processing error: {r['reason']}")
        elif r.get("decision") not in ("recommend", "do_not_recommend"):
            problems.append(f"{r['file']}: bad decision {r.get('decision')!r}")
        if r.get("trap_tool_called"):
            problems.append(f"{r['file']}: trap tool called {r['trap_calls']}")
    return problems


def main() -> None:
    docs = sorted(p for p in EXAM_DIR.iterdir() if p.is_file())
    results = []
    for doc in docs:
        r = run_one(doc)
        results.append(r)
        print(f"{doc.name:16s} {r['status']:5s} {r['decision']:17s} {r['vendor']} | {r['sku']} | {r['unit_price']} | "
              f"{r['lead_time_days']} | {r['min_order']} | trap={r['trap_tool_called']} | ${r['cost_usd']:.6f}", flush=True)
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    reloaded = json.loads(OUT.read_text(encoding="utf-8"))  # proves the file is valid JSON
    problems = validate(reloaded, docs)
    print(f"\nwrote {OUT}: {len(reloaded)} entries")
    print("validation:", "OK" if not problems else "PROBLEMS")
    for p in problems:
        print("  -", p)
    total = sum(r["cost_usd"] for r in reloaded)
    print(f"total cost ${total:.6f}; input {sum(r['input_tokens'] for r in reloaded)}, "
          f"cached {sum(r['cached_tokens'] for r in reloaded)}, output {sum(r['output_tokens'] for r in reloaded)}")


if __name__ == "__main__":
    main()
