# Battery Regulation Navigator

An open-source AI-powered regulatory navigator for global battery lifecycle regulations.

Describe what you're building, transporting, selling, recycling, or importing, and the agent identifies which regulations apply — anywhere in the world — walks you through what you need to do step by step, cites the exact articles/sections that govern each step, and flags deadlines and gaps.

## What it does

The agent operates in three modes:

### 1. Situation-based guidance

You describe your situation. The agent maps it to applicable regulations from any jurisdiction and gives step-by-step actionable guidance with citations.

> **Q: I want to ship lithium batteries from Czech Republic to Slovakia.**
>
> A: This is an intra-EU shipment of lithium batteries, so it's governed by the EU Battery Regulation's transport and labelling provisions plus ADR dangerous-goods rules. You'll need: UN 38.3 test summary documentation, ADR-compliant packaging and marking (Regulation (EU) 2023/1542, Article 13), and hazard labelling for the shipment. ...

### 2. Regulatory lookup

You ask about a specific topic or provision. The agent retrieves and explains it with citations.

> **Q: What are the EU recycled content thresholds?**
>
> A: Article 8 of Regulation (EU) 2023/1542 sets minimum recycled content percentages by material (cobalt, lead, lithium, nickel), phased in from 2031, with a further increase from 2036. ...

### 3. Lifecycle mapping

You describe your product and target markets. The agent generates a full regulatory roadmap across the entire lifecycle, with deadlines and priorities.

> **Q: I'm developing a 48V LFP battery for e-bikes, selling in EU and California.**
>
> A: Across the lifecycle you'll need to address: carbon footprint declaration (Article 7), recycled content (Article 8), supply-chain due diligence (Articles 47–53), CE marking and conformity assessment, battery passport (Chapter IX), and California EPR registration for the US market. ...

In all modes, the agent proactively surfaces every applicable obligation rather than waiting to be asked about each one individually.

## Current coverage

The verified corpus is deeply ingested and chunked at article/section level, with every chunk citation-linked back to the source:

- **EU** — Regulation (EU) 2023/1542 (the Battery Regulation): 96 articles, 143 recitals, sourced from the EUR-Lex consolidated text
- **US Federal** — 40 CFR Part 273 (Universal Waste Rule)
- **US Federal** — 49 CFR 173.185 (DOT/PHMSA lithium battery transport)

The architecture is jurisdiction-agnostic — adding a new jurisdiction means writing a new parser, not redesigning the system. Community contributions for new jurisdictions (China GB standards, Korea K-REACH, Japan, India, Brazil, additional US state EPR laws, etc.) are welcome.

## Quick start

```bash
# 1. Clone the repo
git clone https://github.com/<org>/battery-reg-agent.git
cd battery-reg-agent

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install Node dependencies
cd web && npm install && cd ..

# 4. Start Postgres + pgvector
docker-compose up -d postgres

# 5. Load the verified corpus (parses + chunks + embeds + inserts)
python -m ingestion.load

# 6. Set your Groq API key
export GROQ_API_KEY=your_key_here   # Windows PowerShell: $env:GROQ_API_KEY = "your_key_here"

# 7. Start the backend
uvicorn api.main:app --reload

# 8. Start the frontend (in a separate terminal)
cd web && npm run dev
```

The frontend runs at `http://localhost:3000` and talks to the backend at `http://localhost:8000` by default (override with `NEXT_PUBLIC_API_BASE_URL`).

## Tech stack

- **Backend**: Python 3.11, FastAPI
- **Frontend**: Next.js
- **Database**: Postgres with pgvector (hybrid storage: raw text + tsvector for BM25, embeddings for vector search)
- **LLM**: Groq (Llama 3.3)
- **Embeddings**: sentence-transformers (`all-MiniLM-L6-v2`)
- **Retrieval**: hybrid BM25 (tsvector) + vector search, result fusion

## How it works

1. **Ingestion** — per-jurisdiction parsers (`ingestion/parsers/`) pull source documents (EUR-Lex, eCFR, state statutes) and normalize them into structured chunks.
2. **Chunking** — chunks are split at article/section level, each carrying its chapter/part header as context and a standard metadata schema (jurisdiction, instrument, section reference, deep link, version date).
3. **Hybrid retrieval** — queries run against both BM25 (tsvector) and vector search (pgvector) in parallel, with results fused before ranking.
4. **LLM synthesis** — the agent (Groq/Llama 3.3) orchestrates tool calls (`search`, `get_section`, `obligations_for`, `list_deadlines`, `compare_jurisdictions`) and synthesizes an answer following the fixed answer contract: situational understanding, applicable regulations, step-by-step guidance, deadlines, caveats, and a disclaimer.
5. **Cited response** — every claim resolves to a specific article/section with a deep link back to the official source, distinguishing verified-corpus answers from web-search fallback.

## Contributing

New jurisdiction parsers are welcome — China GB standards, Korea K-REACH, Japan, India, Brazil, additional US state EPR laws, and more. Each parser should output chunks matching the standard metadata schema described in `CLAUDE.md`.

Per the project's working conventions, any new parser must ship with **at least 10 test questions in `evals/` with verified correct citations** before it can be merged. Citation accuracy is the core product guarantee — treat citation regressions as more severe than fluency regressions.

See `CLAUDE.md` for the full architecture, chunk metadata schema, and working conventions.

## License

Apache-2.0
