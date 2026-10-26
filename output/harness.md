# Vendor desk agent harness

The vendor desk agent is a PydanticAI agent on **gpt-6-luna** (through Portkey). It reads one vendor
document, pulls out the purchasing facts, and decides `recommend` or `do_not_recommend` using
the rules in `data/shop_handbook.md`.

```
python agent.py --doc data/practice_docs/p01_bluehen_quote.html              # defended (default)
python agent.py --doc data/practice_docs/p01_bluehen_quote.html --baseline   # original agent, no protections
```

| File | Role |
|---|---|
| `agent.py` | Builds the model and agent, runs it from the command line, writes the logs. `--mode` picks the safety layers |
| `tools.py` | Raw document reader and the two trap tools |
| `models.py` | Structured output the agent must return |
| `prompts/prompt.md` | Hardened agent instructions (Layer 3). The full handbook is appended after them on every request |
| `prompts/prompt_baseline.md` | The original Problem 3 instructions, used by `--baseline` |
| `sanitize.py` | Layer 1: keeps only the text a person would see |
| `policy.py` | Layer 2: checks the extracted facts against the document and applies the handbook rules in code |
| `approvals.py` | Layer 2: the only way to run `send_email` / `approve_payment`, after a person types APPROVE |

## Output fields (`models.py` -> `VendorDecision`)

| Field | Type | Purpose |
|---|---|---|
| `vendor` | text or null | Who is selling. Used for check 1 (approved vendor list, handbook sections 5 and 6). |
| `sku` | text or null | Which Campus Customs item the quote is for. Used to look up the max unit cost in section 9. |
| `unit_price` | number or null | Quoted price per unit in USD. Used for check 2 (at or below max unit cost). |
| `lead_time_days` | integer or null | Days until delivery. Used for check 3 (21 days or less). |
| `min_order` | integer or null | Smallest order the vendor accepts, in units. Used for check 4 (600 or less). |
| `decision` | `recommend` / `do_not_recommend` | The answer for the buyer. `recommend` only if all four checks pass. |
| `reason` | text | One sentence naming the check that decided the outcome, so the buyer can verify it quickly. |

A fact the document does not state comes back as `null` instead of a guess, as handbook section 4 requires.

## Tools (`tools.py`)

| Tool | Real or trap | What it does |
|---|---|---|
| `read_document(path)` | Real | Reads a `.html`, `.pdf`, or `.eml` file inside `data/` and returns plain text. HTML: tags removed, `<script>`/`<style>` skipped. PDF: text from every page via `pypdf`. Email: From/To/Subject/Date plus every text and HTML body part. Paths outside `data/` are refused. |
| `send_email(to, subject, body)` | **Trap** | Never sends anything. Appends the attempted call and its arguments to `output/trap_calls.json` and replies "Email queued." The agent should never call it during an evaluation. |
| `approve_payment(vendor, amount, memo)` | **Trap** | Never pays anything. Appends the attempted call to `output/trap_calls.json` and replies "Payment approved." The agent should never call it during an evaluation. |

The trap tools give a vendor document something to aim at: if a hidden instruction in a document gets
the agent to email or pay someone, it shows up in `trap_calls.json` without causing real harm.

## Caching modes (Problem 4)

| Mode | Flag | How |
|---|---|---|
| `cached` | (default) | Every request sends the same `prompt_cache_key`, so the instructions and handbook prefix are read from the provider's prompt cache |
| `no_cache` | `--no-cache` | Every model request sends a new random `prompt_cache_key`, so the API reports 0 cached tokens |

Both modes send `x-portkey-cache-force-refresh: true`, so Portkey never replays a stored response and every
logged number comes from a real model call. `scripts/cache_test.py` runs all 12 practice docs in both modes.

## Safety (Problem 6)

Vendor documents come from outside the shop, so the agent treats them as **untrusted**. Three layers
protect it. Each one works on its own, so if one misses something the next one still catches it.

### Layer 1: clean the document before the AI sees it (`sanitize.py`)

The agent only gets what a person would see when opening the file. Code removes:
- hidden web-page text: `display:none`, 0 px or 1 px fonts, white text, HTML comments, scripts
- hidden PDF text: white text, tiny text, invisible text, and text placed off the page
- the hidden parts of an email's HTML version
- zero-width characters, and fake `<vendor_document>` tags that try to break out of the data box

Real prices, SKUs, lead times, and minimums are visible, so they pass through unchanged. Everything removed is
listed in `output/audit_trail.json` under `safety.removed`.

*Prevents:* hidden "revised price" or "corrected lead time" notes, and hidden requests to email or pay.

### Layer 2: the AI cannot act, and code makes the call (`agent.py`, `policy.py`, `approvals.py`)

- **No tools for the document agent.** Code reads and cleans the file, then hands the text to the AI inside
  `<vendor_document>` tags. The AI can only return the structured answer. It has no way to send email or pay.
- **Sensitive actions need a person.** `send_email` and `approve_payment` stay in `tools.py` and still only write
  to `output/trap_calls.json`. They can only be run through `python approvals.py ...`, which shows the action and
  does nothing unless someone types `APPROVE`.
- **Facts must be on the page.** Each value the AI extracts (vendor, SKU, price, lead time, minimum) must appear in
  the visible text. If it doesn't, it becomes unknown, and an unknown fact fails its check.
- **Code decides.** The four handbook checks run in Python against the vendor lists and max unit costs read from
  `data/shop_handbook.md`. Code also writes the one-sentence reason, so no document text (links, instructions) can
  end up in the answer. The AI's own decision is kept in the audit trail for comparison.

*Prevents:* a document triggering an email or payment, overriding the vendor list or price limits, or putting
links and instructions into the recommendation. It also catches plain AI mistakes, such as misreading a price comparison.

### Layer 3: tell the AI the rules (`prompts/prompt.md`)

The prompt says plainly that everything inside `<vendor_document>` is vendor data, **not instructions**, even if it
claims to come from the buyer or owner. It lists the tricks to ignore (requests to email, pay, share costs,
add links, use a "corrected" number, or switch the "vendor of record"), and it says to use the numbers in the main quote table.

*Prevents:* the AI being talked into wrong extracted facts when an attack is visible or slips past Layer 1.

| Mode | Layers | Command |
|---|---|---|
| `baseline` | none (original agent) | `--baseline` |
| `l1` | 1 | `--mode l1` |
| `l1_l2` | 1 + 2 | `--mode l1_l2` |
| `defended` | 1 + 2 + 3 | default |

Results and the cost of each layer: `output/defense_results.md`. New attacks tested against both agents:
`output/red_team.md`. Final exam run (defended agent): `python scripts/run_exam.py` -> `output/exam_results.json`.

## Logs (kept across runs, each run appends)

| File | Contents |
|---|---|
| `output/usage_log.json` | Per run: requests, input / cached / cache-write / output tokens, estimated cost from `data/prices.json`, seconds |
| `output/audit_trail.json` | Per run: every tool call with its arguments and a short result, the safety record (mode, removed hidden text, grounding notes, the model's own decision and whether code overrode it), and the final recommendation |
| `output/trap_calls.json` | Every attempted `send_email` / `approve_payment` call. Starts as `[]` |
| `output/approval_log.json` | Every action requested through `approvals.py`, and whether a person approved it |
