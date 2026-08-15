# battery-reg-agent

Open-source agentic RAG system that serves as a global regulatory navigator for battery lifecycle regulations. Users describe their situation — what they're building, transporting, selling, recycling, or importing — and the agent identifies which regulations apply anywhere in the world, walks them through what they need to do step by step, cites the exact articles/sections that govern each step, and flags deadlines and gaps.

The system covers the full battery value chain: raw material sourcing, manufacturing, market placement, transport, use phase, second life/reuse, and end-of-life recycling.

Architecture is jurisdiction-agnostic: a pluggable ingestion pipeline accepts regulations from any country through the same flow (source document → parser → structured chunks with standard metadata). Adding a new jurisdiction means writing a new parser, not redesigning the system.

License: Apache-2.0

## Sources of truth

### Verified corpus (v1)

Deeply ingested, article/section-level chunked, citation-linked:

**EU:**
- Regulation (EU) 2023/1542 (the Battery Regulation) — sourced from EUR-Lex consolidated text
- ADR (European Agreement concerning the International Carriage of Dangerous Goods by Road) — for transport queries
- Key delegated and implementing acts as they are adopted

**US Federal:**
- Mercury-Containing and Rechargeable Battery Management Act (1996)
- 40 CFR Part 273 (Universal Waste Rule)
- 49 CFR 173.185 (DOT/PHMSA lithium battery transport)
- EPA voluntary battery EPR framework

**US State EPR laws (v1 targets):**
- California (SB-1215)
- Washington State (HB 1377)
- New Jersey (Electric and Hybrid Vehicle Battery Management Act)
- Illinois (Portable and Medium-Format Battery Stewardship Act)

### Expansion model

- **Community-contributed parsers**: open-source contributors can add parsers for new jurisdictions (China GB standards, Korea K-REACH, Japan, India, Brazil, etc.). Each parser must output chunks in the standard metadata schema.
- **Admin upload portal**: new regulation documents can be submitted, processed into the corpus, and flagged for review before going live.
- **Automated monitoring**: for jurisdictions with structured feeds (EUR-Lex amendment feed, US Federal Register API), a scheduled job checks for new or amended regulations and flags them for ingestion. Version-tag all chunks so answers can reference "as amended [date]".
- **Web search fallback**: when the agent cannot find an answer in the verified corpus, it searches the web. Answers from web search are clearly marked as "sourced from web search — not from verified corpus" and flagged for potential ingestion into the verified corpus.

Every answer from the verified corpus is traceable to a specific article/section. Citation accuracy is the core product guarantee — treat regressions in citation correctness as more severe than regressions in fluency.

## Agent modes

**1. Situation-based guidance**
User describes their situation. Agent maps it to applicable regulations from any jurisdiction and gives step-by-step actionable guidance with citations.
Example: "I want to ship lithium batteries from Czech Republic to Slovakia" → agent identifies EU Reg 2023/1542 transport provisions, ADR requirements, labelling obligations, tells user what they need (documentation, packaging, markings) with article-level citations.

**2. Regulatory lookup**
User asks about a specific topic or provision. Agent retrieves and explains with citations.
Example: "What are the EU recycled content thresholds?" → Article 8 reference, specific percentages by material and deadline.

**3. Lifecycle mapping**
User describes their product and target markets. Agent generates a full regulatory roadmap across the entire lifecycle with deadlines and priorities.
Example: "I'm developing a 48V LFP battery for e-bikes, selling in EU and California" → maps every obligation from manufacturing through end-of-life: carbon footprint (Article 7), recycled content (Article 8), due diligence (Articles 47-53), CE marking, battery passport (Chapter IX), California EPR registration — each cited with deadlines.

In all modes, the agent proactively identifies all applicable obligations and recommends what to do based on the regulations. It does not wait to be asked about each obligation individually.

## Answer contract

Every response follows this structure:

1. **Situational understanding** — restate what the user is trying to do to confirm understanding
2. **Applicable regulations** — list which instruments and provisions apply, noting whether each comes from the verified corpus or web search
3. **Step-by-step guidance** — what they need to do, in order, with each step citing the specific article/section and deep link
4. **Deadlines and timelines** — when obligations kick in or when action is needed by
5. **Caveats** — pending delegated acts, jurisdiction-specific variation, areas where the corpus has no coverage
6. **Disclaimer** — "This is an informational tool, not legal advice."

The agent must never skip steps 2-6.

## Agent tools

- `search(query, jurisdiction?)` — hybrid retrieval over the verified corpus, filterable by jurisdiction
- `get_section(instrument, article)` — fetch full text of a specific article/section for deep reading or when user asks "show me the actual regulation"
- `compare_jurisdictions(topic, jurisdictions[])` — parallel searches across jurisdictions, synthesized into a comparison
- `list_deadlines(topic, jurisdiction?)` — curated deadline lookup (deadlines are the most-asked and most-hallucinated thing, so these are a verified lookup table, not retrieval)
- `obligations_for(battery_category, capacity, markets[])` — given battery specs and target markets, return the checklist of applicable provisions with citations
- `recommend_steps(user_situation)` — chains the other tools to produce step-by-step guidance for a described situation
- `web_search_fallback(query)` — searches the web when the verified corpus has no answer, clearly marking results as unverified

## Stack

- **Backend**: Python 3.11, FastAPI
- **Frontend**: Next.js
- **Database**: Postgres with pgvector (hybrid storage: raw text + tsvector for BM25, embeddings for vector search)
- **Local infra**: docker-compose.yml runs Postgres+pgvector (pgvector/pgvector:pg16)
- **LLM**: Claude API with tool use for the agent layer
- **Embeddings**: configurable provider (voyage-law, text-embedding-3-large, or open-source alternatives)

## Folder structure

```
ingestion/   Pluggable per-jurisdiction parsers (EU, US federal, US state, community-contributed); normalizes source documents into structured chunks with standard metadata
db/          Schema, migrations, and connection/session helpers
             db/init/       - scripts mounted into the Postgres container on first boot
             db/migrations/ - schema migrations
retrieval/   Hybrid retrieval: BM25 (tsvector) + vector search over pgvector, result fusion/reranking, cross-jurisdiction search
agent/       Agent modes (situation-based guidance, regulatory lookup, lifecycle mapping), tool orchestration, answer-contract synthesis
evals/       Retrieval and answer-quality evals, incl. citation accuracy and deadline-lookup accuracy checks
api/         FastAPI app - routes, request/response schemas, admin upload portal endpoints, wiring between agent/ and retrieval/
web/         Next.js frontend
```

Each Python directory is its own package (`__init__.py`). Keep parser logic cleanly separated per jurisdiction since each source has different document structure, format, and update cadence.

## Chunk metadata schema

Every chunk in the database must have:
- `jurisdiction` (string) — e.g. "EU", "US-federal", "US-CA", "US-WA", "CN", "KR"
- `instrument` (string) — e.g. "Regulation (EU) 2023/1542", "40 CFR Part 273"
- `instrument_short` (string) — e.g. "EU Battery Reg", "Universal Waste Rule"
- `section_ref` (string) — e.g. "Article 77", "§ 273.13", "Section 4(a)"
- `section_title` (string) — e.g. "Battery passport"
- `parent_context` (string) — chapter/part title prepended for retrieval context
- `text` (string) — the chunk text
- `url` (string) — deep link to the official source
- `version_date` (date) — when this version was ingested
- `source_type` (string) — "verified_corpus" or "web_search"

## Working conventions

- **Citation granularity**: always resolve to the specific article/section, never just the instrument as a whole.
- **Hybrid retrieval is first-class**: BM25 and vector search are both primary, not vector-with-a-fallback. Changes to retrieval/ must preserve both.
- **Evals before merging**: run evals/ whenever retrieval/ or agent/ logic changes. Citation accuracy regressions are blocking.
- **Chunking rules**: EU articles split by paragraph if long, but always prepend article header (chapter, article number, title) to every chunk. Recitals ingested separately and tagged as interpretive context ("recital"). US federal regs chunk at § level. State laws chunk by section.
- **Proactive advisory**: the agent's default behavior is to identify all applicable obligations when a user describes a situation, not wait to be asked about each one.
- **Web search transparency**: answers sourced from web search must be visually and structurally distinct from verified corpus answers. Never mix them without clear labelling.
- **New jurisdiction contributions**: any new parser must include at least 10 test questions in evals/ with verified correct citations before merging.
- Local dev DB comes up via `docker-compose up -d postgres`. Schema/init scripts belong in db/init/ (first-boot) and db/migrations/ (ongoing changes).
