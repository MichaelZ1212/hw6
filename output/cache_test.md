# Prompt caching test: with vs. without cached tokens

Run at 2026-10-26T19:41:15+00:00 on **gpt-6-luna** through Portkey. Raw data: `output/cache_test.json`
(every model call with the usage the API returned and its cost). Script: `scripts/cache_test.py`.

## Setup

Both setups use the Problem 3 agent (`agent.run(..., mode="baseline")`: the original instructions, now kept in
`prompts/prompt_baseline.md`, plus the full handbook), the same tools, and the same 12 practice documents.
Only one setting differs:

| Setup | How | What the API should report |
|---|---|---|
| **cached** | Every request sends the same `prompt_cache_key` (`campus-customs-cache-test-20261026T194115`) | 1st call writes the handbook to the cache, every later call reads it (`cached_tokens` > 0) |
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

## 1. Total and average cost

Prices from `data/prices.json` (per 1M tokens): input $0.1, cache write $0.125,
cached input $0.01, output $0.5.

Cost per call = uncached input x 0.1 + cache write x 0.125
+ cached x 0.01 + output x 0.5, all / 1,000,000.

| | cached | no_cache |
|---|---:|---:|
| Documents counted (ok) | 12 | 12 |
| Model calls | 24 | 24 |
| Input tokens (total) | 261,644 | 261,644 |
| of which cached (read) | 245,768 | 0 |
| of which cache write | 12,852 | 258,620 |
| of which uncached | 3,024 | 3,024 |
| Output tokens | 1,300 | 1,454 |
| Cost: cached input | $0.002458 | $0.000000 |
| Cost: cache write | $0.001606 | $0.032327 |
| Cost: uncached input | $0.000302 | $0.000302 |
| Cost: output | $0.000650 | $0.000727 |
| **Total cost** | **$0.005017** | **$0.033357** |
| **Average per document** | **$0.000418** | **$0.002780** |
| Total run time | 77.3 s | 44.9 s |
| Decisions matching practice_key | 9/12 | 9/12 |

**Saved by caching:** $0.033357 - $0.005017 = **$0.028340**, i.e. $0.028340 / $0.033357 = **85.0% cheaper**.

### Per document

| Doc | Setup | Calls | Input | Cached | Cache write | Output | Cost | Decision OK | Status |
|---|---|---:|---:|---:|---:|---:|---:|:---:|---|
| p01_bluehen_quote.html | cached | 2 | 21,798 | 10,694 | 10,852 | 106 | $0.001542 | yes | ok |
| p02_elmcity_quote.html | cached | 2 | 21,801 | 21,370 | 179 | 110 | $0.000316 | NO | ok |
| p03_ivyprint_catalog.html | cached | 2 | 21,798 | 21,370 | 176 | 107 | $0.000314 | yes | ok |
| p04_harborstitch_quote.html | cached | 2 | 21,791 | 21,372 | 167 | 113 | $0.000316 | yes | ok |
| p05_maplemills_quote.pdf | cached | 2 | 21,770 | 21,370 | 148 | 104 | $0.000309 | yes | ok |
| p06_qtextile_quote.pdf | cached | 2 | 21,814 | 21,370 | 192 | 106 | $0.000316 | yes | ok |
| p07_longwharf_quote.pdf | cached | 2 | 21,789 | 21,370 | 167 | 104 | $0.000312 | yes | ok |
| p08_chapelst_email.eml | cached | 2 | 21,795 | 21,371 | 172 | 106 | $0.000313 | NO | ok |
| p09_westville_email.eml | cached | 2 | 21,924 | 21,371 | 301 | 109 | $0.000331 | yes | ok |
| p10_eastrock_email.eml | cached | 2 | 21,814 | 21,371 | 191 | 112 | $0.000319 | yes | ok |
| p11_yorkst_quote.html | cached | 2 | 21,763 | 21,370 | 141 | 102 | $0.000308 | yes | ok |
| p12_bluehen_quote.pdf | cached | 2 | 21,787 | 21,369 | 166 | 121 | $0.000320 | NO | ok |
| p01_bluehen_quote.html | no_cache | 2 | 21,798 | 0 | 21,546 | 118 | $0.002777 | yes | ok |
| p02_elmcity_quote.html | no_cache | 2 | 21,801 | 0 | 21,549 | 115 | $0.002776 | NO | ok |
| p03_ivyprint_catalog.html | no_cache | 2 | 21,798 | 0 | 21,546 | 106 | $0.002771 | yes | ok |
| p04_harborstitch_quote.html | no_cache | 2 | 21,791 | 0 | 21,539 | 125 | $0.002780 | yes | ok |
| p05_maplemills_quote.pdf | no_cache | 2 | 21,770 | 0 | 21,518 | 104 | $0.002767 | yes | ok |
| p06_qtextile_quote.pdf | no_cache | 2 | 21,814 | 0 | 21,562 | 106 | $0.002773 | yes | ok |
| p07_longwharf_quote.pdf | no_cache | 2 | 21,789 | 0 | 21,537 | 110 | $0.002772 | yes | ok |
| p08_chapelst_email.eml | no_cache | 2 | 21,795 | 0 | 21,543 | 110 | $0.002773 | yes | ok |
| p09_westville_email.eml | no_cache | 2 | 21,924 | 0 | 21,672 | 212 | $0.002840 | NO | ok |
| p10_eastrock_email.eml | no_cache | 2 | 21,814 | 0 | 21,562 | 123 | $0.002782 | yes | ok |
| p11_yorkst_quote.html | no_cache | 2 | 21,763 | 0 | 21,511 | 105 | $0.002767 | yes | ok |
| p12_bluehen_quote.pdf | no_cache | 2 | 21,787 | 0 | 21,535 | 120 | $0.002777 | NO | ok |

## 2. Actual vs. the Problem 2 estimate

Problem 2 priced only the handbook (10,058 tokens) for one call per document.

| | Problem 2 estimate | Actual (this test) |
|---|---:|---:|
| Input tokens per model call | 10,058 (handbook only) | 10,902 |
| Model calls per document | 1 | 2.0 |
| Cost per document, no caching | $0.001006 | $0.002780 |
| Cost per document, cached (cache hit) | $0.000101 | $0.000418 |
| Savings from caching | 90% (at steady state, 89.9% over 1,000 calls) | 85.0% |

Why the actual numbers are higher:

- **More tokens per call.** Each call also carries the agent instructions (`prompt.md`), the tool and
  output schemas, the user message, and from the 2nd call on the document text and the first answer.
  That is about 844 tokens per call on top of the handbook.
- **Two calls per document, not one.** The agent first calls `read_document`, then returns its answer
  in a second request. The handbook is sent both times, so per document the input roughly doubles.
- **No-cache calls are billed as cache writes.** The provider writes every new prefix to the cache, so the
  no_cache setup pays $0.125/1M on most of its input, not the $0.1/1M that
  Problem 2 assumed. At the plain input price the no_cache run would have cost
  $0.026891 ($0.002241 per document).
- **Output tokens** were left out of Problem 2. They are a small share here.

The savings percentage still lands close to the estimate. Caching cuts the per-document bill by roughly an
order of magnitude.

## 3. Monthly projection (1,000 documents/day x 30 days = 30,000 documents)

The projection uses the **steady-state** cost per document: the average of every run except the first one in each
setup, which paid this test's one-time cold cache write. (Averaging that cold write into every document would
charge it 30,000 times a month.)

| Setup | Calculation | Per month |
|---|---|---:|
| cached | 30,000 x $0.000316 | **$9.48** |
| no_cache | 30,000 x $0.002780 | **$83.40** |
| Savings | | **$73.92 / month (88.6%)** |

At 1,000 documents a day the cache stays warm all day, so nearly every call is a cache hit, and the cold write is paid
roughly once per cache lifetime, not once per document. Including the cold write in the average (as in section 1) gives
$12.54 cached vs $83.39 no-cache per month.

## 4. Unexpected findings

1. **Portkey's gateway cache.** It silently replayed responses and their usage. In Problem 3 the p01 run finished
   in 0.81 s for 2 requests, which is probably a replay. Without the force-refresh header the no_cache test
   would have reported tokens and costs for calls that never reached the model.
2. **Caching is on by default and has no off switch.** The provider caches automatically, so "without caching"
   had to be built by giving each request its own cache key. A plain agent with no key would already get most
   of the caching benefit by accident.
3. **"No caching" costs more than plain input pricing.** Each new prefix is written to the cache at
   $0.125/1M, 25% above the $0.1/1M input price. So turning caching "off" this way
   is slightly worse than the true no-cache baseline in Problem 2.
4. **The first cached call is the most expensive.** It is p01_bluehen_quote.html ($0.001542), because it pays the cache write; its second request already reads the cache.
5. **New tokens are billed as cache writes, not plain input.** Only about 126 tokens per call
   are billed as plain uncached input. Everything new in a request is written to the cache at
   $0.125/1M: the whole prefix in the no_cache setup, and in the cached setup the
   document-specific part (about 150-300 tokens). So even the cached setup pays a small write charge on
   every document ($0.001606 in total, 32% of its bill).
6. **Run time is not a reliable caching signal here.** Most documents took about 3.6 s in either setup. The slowest was p07_longwharf_quote.pdf (cached, 34.9 s), a one-off latency spike that also explains most of the difference in total run time between the setups.
7. **Decisions do not depend on caching, but they are not fully stable.** 9/12 (cached) and
   9/12 (no_cache) decisions match `practice_key.json`. Mismatches: p02_elmcity_quote.html (cached: recommend); p08_chapelst_email.eml (cached: do_not_recommend); p12_bluehen_quote.pdf (cached: recommend); p02_elmcity_quote.html (no_cache: recommend); p09_westville_email.eml (no_cache: recommend); p12_bluehen_quote.pdf (no_cache: recommend). Most come from text inside the documents that claims a 'revised' price or lead time, which the agent believed (a prompt-injection / safety issue for the later problems). Because the same document can flip between runs, these differences are model variance, not an effect of caching.
