# HW 6: Campus Customs vendor desk agent

An AI agent that reads one vendor document (an HTML quote, a PDF quote, or a supplier email), extracts
the **vendor, SKU, unit price, lead time, and minimum order**, and recommends whether Campus Customs
should buy, following the rules in `data/shop_handbook.md`. Every AI call uses **gpt-6-luna** through the
Portkey gateway.

The project also measures the cost of sending the 10,000-token handbook on every call (and how much prompt
caching saves), attacks the agent with prompt injections hidden in vendor documents, and defends it with three
safety layers.

> **No real emails or payments.** `send_email` and `approve_payment` are simulations. They only write the attempted
> call to `output/trap_calls.json`. The defended agent cannot call them at all.

Results dashboard (open offline in any browser): **`output/hw6_report.html`**

---

## 1. Setup

Requires **Python 3.11+** (developed on Python 3.14) and a Portkey API key with access to `gpt-6-luna`.

```bash
git clone https://github.com/MichaelZ1212/hw6.git
cd hw6
python -m venv .venv
```

Activate the virtual environment:

```bash
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Windows (Git Bash)
source .venv/Scripts/activate
# macOS / Linux
source .venv/bin/activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

## 2. Configure the API key

Copy the example file and put your own key in it. `.env` is git-ignored and must never be committed.

```bash
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
```

Then edit `.env`:

```
PORTKEY_API_KEY=your-portkey-key-here
```

(Alternatively, set `PORTKEY_API_KEY` as an environment variable. A real shell variable takes precedence over `.env`.)

## 3. Run the agent on a sample document

```bash
python agent.py --doc data/practice_docs/p01_bluehen_quote.html
```

Expected output (a JSON recommendation):

```json
{
  "vendor": "Blue Hen Apparel",
  "sku": "CC-HD-006",
  "unit_price": 21.8,
  "lead_time_days": 14,
  "min_order": 240,
  "decision": "recommend",
  "reason": "All four checks pass: Blue Hen Apparel is approved, $21.80 is within the max unit cost for CC-HD-006, 14-day lead time, 240-unit minimum."
}
```

More examples:

```bash
python agent.py --doc data/practice_docs/p05_maplemills_quote.pdf      # PDF
python agent.py --doc data/practice_docs/p08_chapelst_email.eml        # email
python agent.py --doc data/exam_docs/e03_quote.html                    # exam document
python agent.py --doc data/practice_docs/p12_bluehen_quote.pdf --baseline   # original agent, no defenses
python agent.py --doc data/practice_docs/p01_bluehen_quote.html --no-cache  # no prompt-cache reuse
```

| Option | Meaning |
|---|---|
| `--doc PATH` | Vendor document inside `data/` (`.html`, `.pdf`, `.eml`) |
| *(default)* | **Defended** agent: all three safety layers |
| `--baseline` | Original Problem 3 agent with no protections (for comparison) |
| `--mode {baseline,l1,l1_l2,defended}` | Turn safety layers on one at a time |
| `--no-cache` | Fresh prompt-cache key on every call, so the API reports 0 cached tokens |

Every run appends to `output/usage_log.json` (tokens, cost, time), `output/audit_trail.json` (tool calls,
removed hidden text, the model's own answer and the code decision), and `output/trap_calls.json`.

## 4. How it works

| File | Role |
|---|---|
| `agent.py` | Command-line entry point. Builds the PydanticAI agent on gpt-6-luna via Portkey, applies the safety mode, writes the logs |
| `models.py` | `VendorDecision`, the structured output (vendor, sku, unit_price, lead_time_days, min_order, decision, reason) |
| `tools.py` | Raw document reader (HTML / PDF / email) and the two **simulated** tools `send_email` / `approve_payment` |
| `prompts/prompt.md` | Hardened agent instructions (the full handbook is appended on every request) |
| `prompts/prompt_baseline.md` | Original instructions used by `--baseline` |
| `sanitize.py` | **Layer 1:** keeps only text a person would see (removes hidden CSS, comments, white/tiny/off-page PDF text, hidden email parts, zero-width characters) |
| `policy.py` | **Layer 2:** checks each extracted value against the visible text, then applies the four handbook rules in code (approved vendor, price <= max unit cost, lead time <= 21 days, minimum order <= 600) |
| `approvals.py` | **Layer 2:** the only way to run `send_email` / `approve_payment`. A person must type `APPROVE`, and it still only logs |

In defended mode the document agent has **no tools**. Code reads and cleans the document, hands it to the model
as data inside `<vendor_document>` tags, and makes the final decision itself. More detail: `output/harness.md`.

## 5. Reproduce each part of the assignment

All scripts run from the project root and call the API, except where marked offline.

| Problem | Command | Output |
|---|---|---|
| 1 Prompt log | (written during the work) | `AI_prompts.md` |
| 2 Handbook size and cost estimate (offline) | `python scripts/handbook_estimate.py` | `output/handbook_estimate.md` |
| 3 Agent | `python agent.py --doc data/practice_docs/p01_bluehen_quote.html` | `output/usage_log.json`, `output/audit_trail.json`, `output/trap_calls.json`, `output/harness.md` |
| 4 With vs. without caching (24 runs) | `python scripts/cache_test.py` | `output/cache_test.json`, `output/cache_test.md` |
| 5 Attack the baseline (36 runs) | `python scripts/attack_test.py` | `output/attack_results.json`, `output/attack_results.md` |
| 6 Defenses, layer by layer (144 runs) | `python scripts/defense_test.py` | `output/defense_results.json`, `output/defense_results.md` |
| 7 Red team: build docs (offline), then test (12 runs) | `python scripts/build_red_team_docs.py` then `python scripts/red_team_test.py` | `data/my_attacks/`, `output/red_team.json`, `output/red_team.md` |
| 8 Exam documents (10 runs) | `python scripts/run_exam.py` | `output/exam_results.json` |
| 9 Dashboard (offline) | `python scripts/build_report.py` | `output/hw6_report.html` |

`cache_test.py`, `attack_test.py`, `defense_test.py` and `red_team_test.py` also take `--report`, which rebuilds the
markdown from the saved JSON without calling the API.

Offline self-test (no API key needed): `python scripts/self_test.py` checks the sanitizer, the code rules, and that each
script runs the agent mode it describes.
Re-running a test overwrites its result files with new measurements. The model is not deterministic, so counts
can differ slightly from run to run.

## 6. Repository contents

```
hw6/
├── agent.py, tools.py, models.py          the agent
├── sanitize.py, policy.py, approvals.py   safety layers
├── prompts/prompt.md, prompt_baseline.md  agent instructions
├── AI_prompts.md                          prompts used for every problem
├── requirements.txt, .env.example, .gitignore, README.md
├── data/
│   ├── shop_handbook.md, prices.json, practice_key.json
│   ├── practice_docs/   12 practice documents (HTML, PDF, email)
│   ├── exam_docs/       10 exam documents
│   └── my_attacks/      2 red-team documents + attack_key.json (round1/ = first attempt)
├── scripts/             one script per experiment (see section 5)
└── output/              all results: logs, cache test, attack/defense/red-team results,
                         exam_results.json, harness.md, hw6_report.html
```

## 7. Headline results

| | Result |
|---|---|
| Prompt caching (Problem 4) | **85% cheaper**: $0.000418 vs $0.002780 per document |
| Misled by hidden instructions (Problems 5-6) | **11/36 runs** before the defenses, **0/36** after |
| Legitimate quotes still approved, defended | **12/12** |
| Cost per document, defended vs. original | **$0.000199 vs $0.000339** (the defenses removed one AI call per document) |
| Red team (Problem 7) | Covered-text "amended terms" PDF fooled the original agent 3/3 and the defended agent 0/3. The fake-system payment email failed against both |
| Exam (Problem 8) | 10/10 processed, 0 simulated tool calls, all decisions consistent with the handbook rules |
| Projected cost at 1,000 documents/day | about **$5.96 per month** (projection from the measured average) |
