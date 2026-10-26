"""Campus Customs vendor desk agent.

Reads one vendor document, extracts vendor / SKU / unit price / lead time / minimum order,
and recommends or not according to data/shop_handbook.md.

Usage:  python agent.py --doc data/practice_docs/p01_bluehen_quote.html              (defended)
        python agent.py --doc data/practice_docs/p01_bluehen_quote.html --baseline   (original Problem 3 agent)
        python agent.py --doc ... --mode l1_l2 --no-cache

Safety modes (Problem 6). Each layer can be switched on separately so it can be measured:
  baseline  original agent: raw text via the read_document tool, trap tools registered, model decides
  l1        + Layer 1: the read_document tool returns only visible text (sanitize.py)
  l1_l2     + Layer 2: no tools at all; code reads and cleans the document and passes it as data,
            then code grounds the facts and makes the decision (policy.py)
  defended  + Layer 3: hardened prompts/prompt.md (default)

Caching (Problem 4):
  cached    (default) every request uses the same prompt_cache_key, so the handbook prefix is
            written to the provider's prompt cache once and read back on later requests.
  no_cache  every model request gets a brand-new random prompt_cache_key, so it never matches an
            existing cache entry and the API reports zero cached tokens.
  In both modes the Portkey gateway's own response cache is bypassed (force refresh), so every
  number comes from a real model call, not a replayed response.

Every run appends to:
  output/usage_log.json   tokens, estimated cost, and run time
  output/audit_trail.json tool calls (inputs and short results) and the final recommendation
  output/trap_calls.json  calls to the trap tools send_email / approve_payment (should stay empty)

send_email / approve_payment are only reachable by the document agent in baseline and l1 modes. The
defended agent has no tools; those actions go through approvals.py, which needs a human to approve.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent, Tool
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

import policy
from models import VendorDecision
from sanitize import clean_document, read_document_clean
from tools import append_json, approve_payment, init_trap_log, read_document, resolve_doc, send_email

ROOT = Path(__file__).resolve().parent
PROMPT_PATH = ROOT / "prompts" / "prompt.md"
BASELINE_PROMPT_PATH = ROOT / "prompts" / "prompt_baseline.md"
HANDBOOK_PATH = ROOT / "data" / "shop_handbook.md"
PRICES_PATH = ROOT / "data" / "prices.json"
USAGE_LOG = ROOT / "output" / "usage_log.json"
AUDIT_LOG = ROOT / "output" / "audit_trail.json"

# The only model used in this project.
MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
MODEL_SETTINGS = OpenAIResponsesModelSettings(openai_reasoning_effort="low", max_tokens=2000)
CACHE_KEY = "campus-customs-vendor-desk-v1"


@dataclass(frozen=True)
class Mode:
    sanitize: bool         # Layer 1: only visible document text reaches the model
    isolate: bool          # Layer 2: no tools; document passed as data; code grounds facts and decides
    hardened_prompt: bool  # Layer 3: prompts/prompt.md instead of prompts/prompt_baseline.md


MODES = {
    "baseline": Mode(False, False, False),
    "l1": Mode(True, False, False),
    "l1_l2": Mode(True, True, False),
    "defended": Mode(True, True, True),
}
DEFAULT_MODE = "defended"

# .env in this folder first, then the course folder above it. Real shell variables win.
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")


class NoCacheResponsesModel(OpenAIResponsesModel):
    """Same model, but each request carries a fresh random prompt_cache_key, so it can never hit
    a cache entry written by an earlier request (including the agent's own first request)."""

    async def request(self, messages, model_settings, model_request_parameters):
        settings = {**(model_settings or {}), "openai_prompt_cache_key": f"nocache-{uuid.uuid4()}"}
        return await super().request(messages, settings, model_request_parameters)


def build_model(cache: bool = True) -> OpenAIResponsesModel:
    """gpt-6-luna through the Portkey gateway, authenticated with PORTKEY_API_KEY."""
    api_key = os.getenv("PORTKEY_API_KEY")
    if not api_key:
        raise SystemExit("PORTKEY_API_KEY is not set. Put it in .env or export it.")
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=PORTKEY_BASE_URL,
        default_headers={
            "x-portkey-api-key": api_key,
            "x-portkey-provider": "openai",
            # Skip Portkey's response cache: it replays old answers (and old usage) without calling the model.
            "x-portkey-cache-force-refresh": "true",
        },
        timeout=120.0,
        max_retries=2,
    )
    cls = OpenAIResponsesModel if cache else NoCacheResponsesModel
    return cls(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


def build_instructions(hardened: bool = True) -> str:
    """Agent instructions followed by the full handbook. Static text first so it can be cached."""
    prompt = (PROMPT_PATH if hardened else BASELINE_PROMPT_PATH).read_text(encoding="utf-8")
    handbook = HANDBOOK_PATH.read_text(encoding="utf-8")
    return f"{prompt}\n\n---\n\n{handbook}"


def build_agent(cache: bool = True, mode: str = DEFAULT_MODE) -> Agent[None, VendorDecision]:
    m = MODES[mode]
    key = f"{CACHE_KEY}-{mode}"
    settings = OpenAIResponsesModelSettings(**MODEL_SETTINGS, openai_prompt_cache_key=key) if cache else MODEL_SETTINGS
    if m.isolate:
        tools = []  # Layer 2: the document agent cannot call anything, so a document cannot trigger actions
    else:
        reader = Tool(read_document_clean, name="read_document") if m.sanitize else read_document
        tools = [reader, send_email, approve_payment]
    return Agent(
        build_model(cache),
        output_type=VendorDecision,
        instructions=build_instructions(m.hardened_prompt),
        tools=tools,
        model_settings=settings,
    )


def isolated_prompt(doc: str, text: str) -> str:
    """Layer 2: the document goes in as clearly delimited data, not through a tool."""
    return (f"The vendor document {resolve_doc(doc).name} has already been read for you; there is no tool to call. "
            f"Its text is between the tags below. Evaluate it.\n\n"
            f"<vendor_document>\n{text}\n</vendor_document>")


def estimate_cost(usage) -> dict:
    """Cost in USD from data/prices.json. input_tokens includes cached and cache-write tokens."""
    p = json.loads(PRICES_PATH.read_text(encoding="utf-8"))[MODEL_NAME]
    cached = usage.cache_read_tokens or 0
    written = usage.cache_write_tokens or 0
    uncached = max((usage.input_tokens or 0) - cached - written, 0)
    parts = {
        "uncached_input": uncached * p["input_per_1m"] / 1e6,
        "cached_input": cached * p["cached_input_per_1m"] / 1e6,
        "cache_write": written * p["cache_write_per_1m"] / 1e6,
        "output": (usage.output_tokens or 0) * p["output_per_1m"] / 1e6,
    }
    return {"total_usd": round(sum(parts.values()), 8), **{k: round(v, 8) for k, v in parts.items()}}


def short(text, limit: int = 300) -> str:
    s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + f"... [{len(s) - limit} more chars]"


def tool_calls_from(messages) -> list[dict]:
    """Pair each tool call with its result. The final_result output tool is left out."""
    calls, results = {}, {}
    for msg in messages:
        for part in msg.parts:
            if isinstance(part, ToolCallPart) and part.tool_name != "final_result":
                calls[part.tool_call_id] = part
            elif isinstance(part, ToolReturnPart):
                results[part.tool_call_id] = part.content
    return [
        {"tool": c.tool_name, "args": c.args_as_dict(), "result": short(results.get(cid, ""))}
        for cid, c in calls.items()
    ]


def model_calls_from(messages) -> list[dict]:
    """Token usage the API reported for each individual model request in a run."""
    calls = []
    for msg in messages:
        if isinstance(msg, ModelResponse):
            u = msg.usage
            calls.append({
                "response_id": msg.provider_response_id,
                "input_tokens": u.input_tokens,
                "cached_tokens": u.cache_read_tokens,
                "cache_write_tokens": u.cache_write_tokens,
                "uncached_input_tokens": max(u.input_tokens - u.cache_read_tokens - u.cache_write_tokens, 0),
                "output_tokens": u.output_tokens,
                "details": dict(u.details),
                "cost": estimate_cost(u),
            })
    return calls


def run(doc: str, cache: bool = True, mode: str = DEFAULT_MODE) -> dict:
    """Evaluate one document. Appends to the usage, audit, and trap logs and returns the run record."""
    init_trap_log()
    m = MODES[mode]
    agent = build_agent(cache, mode)
    cache_mode = "cached" if cache else "no_cache"
    safety: dict = {"mode": mode, **asdict(m)}

    started = time.perf_counter()
    if m.isolate:
        clean = clean_document(doc) if m.sanitize else None
        text = clean.text if clean else read_document(doc)
        if clean:
            safety["sanitize_ms"] = round(clean.seconds * 1000, 2)
            safety["removed"] = clean.removed
        result = agent.run_sync(isolated_prompt(doc, text))
        policy_started = time.perf_counter()
        decision, enforcement = policy.enforce(result.output, text)
        safety["policy_ms"] = round((time.perf_counter() - policy_started) * 1000, 2)
        safety.update(enforcement)
    else:
        if m.sanitize:
            clean = clean_document(doc)  # same cleaning the tool does; logged here for the audit
            safety["sanitize_ms"] = round(clean.seconds * 1000, 2)
            safety["removed"] = clean.removed
        result = agent.run_sync(f"Evaluate this vendor document: {doc}")
        decision = result.output
    seconds = round(time.perf_counter() - started, 2)

    usage = result.usage
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    messages = result.all_messages()

    record = {
        "time": now,
        "doc": doc,
        "model": MODEL_NAME,
        "safety_mode": mode,
        "cache_mode": cache_mode,
        "requests": usage.requests,
        "input_tokens": usage.input_tokens,
        "cached_input_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "cost": estimate_cost(usage),
        "seconds": seconds,
    }
    append_json(USAGE_LOG, record)
    append_json(AUDIT_LOG, {
        "time": now,
        "doc": doc,
        "safety_mode": mode,
        "cache_mode": cache_mode,
        "tool_calls": tool_calls_from(messages),
        "safety": safety,
        "recommendation": decision.model_dump(),
    })
    return {**record, "model_calls": model_calls_from(messages), "safety": safety,
            "recommendation": decision.model_dump()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Campus Customs vendor desk agent")
    parser.add_argument("--doc", required=True, help="Path to a vendor document (.html, .pdf, or .eml)")
    parser.add_argument("--no-cache", action="store_true", help="Use a fresh prompt cache key on every request")
    parser.add_argument("--mode", choices=list(MODES), default=DEFAULT_MODE, help="Safety layers to use")
    parser.add_argument("--baseline", action="store_true", help="Run the original agent with no protections")
    args = parser.parse_args()
    try:
        resolve_doc(args.doc)
    except (FileNotFoundError, ValueError) as e:
        raise SystemExit(f"Error: {e}")
    out = run(args.doc, cache=not args.no_cache, mode="baseline" if args.baseline else args.mode)
    print(json.dumps(out["recommendation"], indent=2))


if __name__ == "__main__":
    main()
