# Rumah123 Weekly Property News IG Post Generator

Automated weekly content pipeline that ingests Indonesian property and mortgage (KPR) news from the past 7 days, filters syndicated duplicates and off-topic noise, generates plain-text Instagram captions in the `@rumah123com` voice, and validates every draft through a deterministic quality gate before human review.

Ships in two synchronized runtimes sharing identical filtering, prompts, and linting rules:
1. [`workflow.json`](workflow.json): Importable **n8n** workflow (`Schedule Trigger` -> `RSS Feed Read` -> `Code` -> `Basic LLM Chain + Google Gemini 2.5 Flash` -> `Quality Gate Code`).
2. [`generator.py`](generator.py): Zero-dependency **Python 3 stdlib** CLI mirroring the exact n8n pipeline for CI testing, prompt regression checks, and headless runs.

## Pipeline Architecture

```text
[1. Schedule Trigger]  Every Monday 08:00 WIB
          |
          v
[2. Google News ID RSS (7d)]
    Query: ("suku bunga KPR" OR "harga rumah" OR "pasar properti"
            OR "beli rumah" OR "rumah subsidi") when:7d (hl=id, gl=ID)
          |
          v
[3. Relevance Scorer & Jaccard Deduplicator]
    - Drops negative noise (foreign housing, celebrity gossip, flight/EV PPN DTP)
    - Scores Indonesian KPR/housing signals + Tier-1 financial outlets
    - Deduplicates rewritten headlines (token Jaccard >= 0.32, preserves decimals like 8,9)
    - Enforces max 2 articles per media outlet -> outputs Top 3 distinct angles
          |
          v
[4. Rumah123 Brand Caption LLM]
    - Grounded to RSS headline/outlet/date (blocks fabricated article body statistics)
    - Enforces warm "kamu" voice, <=14-word hook, 3 actionable KPR/buying checks,
      natural Rumah123 feature tie-in (Simulasi KPR / secondary listing filter), A/B comment CTA
          |
          v
[5. Deterministic Caption Quality Gate]
    - Strips leaked Markdown (**bold**, # headings) & normalizes punctuation/Unicode spaces
    - Checks hook <= 16 words, body 95-250 words, 3-6 hashtags, Rumah123 mention,
      and rejects stiff formal "Anda" pronouns -> marks READY_FOR_REVIEW or NEEDS_REVISION
```

## Engineering Post-Mortem: What Went Wrong & How We Fixed It

1. **NewsAPI Free Tier HTTP 426 & 24-Hour Lag**
   - *Issue*: NewsAPI `/v2/everything` returns `HTTP 426 Upgrade Required` on non-localhost workflow runners and delays articles by 24 hours. Exporting raw HTTP Request nodes also risks leaking query-string API keys.
   - *Fix*: Migrated primary ingestion to Google News Indonesia RSS XML (`hl=id&gl=ID&ceid=ID:id`) with an explicit `when:7d` window. Zero API keys required for news ingestion, and credentials in `workflow.json` strictly reference n8n's credential store.

2. **Boolean Precedence & Off-Topic Tax/Celebrity Noise**
   - *Issue*: Unparenthesized `OR PPN DTP Indonesia` matched domestic airline ticket and electric-vehicle tax incentives. Even scoped to `beli rumah`, raw RSS returned foreign housing drops (Australia, Portugal) and billionaire gossip (Mark Zuckerberg).
   - *Fix*: Wrapped exact Indonesian phrases in parentheses with `when:7d` and added deterministic negative-keyword filtering plus domain-weighted scoring (`kpr`, `cicilan`, `subsidi`, `rumah bekas`, `bphtb`).

3. **Multi-Outlet Syndication Collisions**
   - *Issue*: Multiple outlets rewrite the same viral number on the same morning (for example, Kompas.com *"Punya Gaji Rp 8,9 Juta, Apakah Bisa Beli Rumah Impian?"* vs Demokratis *"Gaji Rp 8,9 Juta Membuka Peluang Pekerja Muda Beli Rumah"*). Naive `slice(0, 3)` produced two nearly identical posts.
   - *Fix*: Added Indonesian stopword removal + decimal-preserving tokenizer (`\d+(?:[.,]\d+)?`) + token Jaccard similarity (`>= 0.32`) and a max-2-per-outlet cap.

4. **Headline-Only Hallucinations & Instagram Formatting Leaks**
   - *Issue*: RSS feeds only supply headlines, not full article bodies. Unconstrained LLMs invented survey numbers or assumed "Yes" on question-mark headlines (*"RI Termasuk?"*), drifted into stiff `"Anda"` pronouns, and leaked `**Markdown**` asterisks onto Instagram.
   - *Fix*: Added explicit epistemic rules in `SYSTEM_PROMPT` (never assume unverified article conclusions; note regional/marital rules on KPR Subsidi income caps) and built `lint_caption()` as a hard post-generation gate.

## Quick Start

### Option 1: Run Python Pipeline Locally (Zero Dependencies)

```bash
# Live run with Gemini API
export GEMINI_API_KEY="your-key"
python generator.py --top-k 3 --output sample_outputs.json

# Live run with OpenAI-compatible / Groq API
export GROQ_API_KEY="your-key"
python generator.py --top-k 3 --output sample_outputs.json

# Offline deterministic smoke run (no network or API keys required)
python generator.py --offline --output sample_outputs.json
```

### Option 2: Import into n8n

1. Open n8n -> **Workflows** -> **Import from File** -> select [`workflow.json`](workflow.json).
2. Open the **Google Gemini 2.5 Flash** node and select your `Google Gemini(PaLM) Api` credential.
3. Click **Test Workflow** to inspect the ranked RSS items, generated captions, and quality gate metrics.

## Running Unit Tests

```bash
python -m unittest discover -v
```

Covers RSS XML extraction, outlet suffix stripping, syndicated duplicate removal, noise rejection, Markdown/pronoun caption linting, and secret-free `workflow.json` validation. Real run outputs are stored in [`sample_outputs.json`](sample_outputs.json).
