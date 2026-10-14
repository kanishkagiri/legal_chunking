# Legalguard: work completed so far

## Act text and provision nodes

The source is the official Government of India PDF for the Consumer Protection Act, 2019: [official PDF](https://consumeraffairs.gov.in/public/upload/files/CP%20Act%202019_1732700731.pdf). Its title, Act number, publisher, source host, publication date, PDF page count, and URL are stored on an `Act` node so retrieved provisions can return the source.

The parsed Act contains **8 chapters, 107 sections, and 225 numbered subsections**. Numbered subsections such as `(1)` and `(2)` are separate `Subsection` nodes. Nested `(a)`, `(b)`, `(i)`, and similar markers stay inside that subsection's `text`.

| Node label | Role and main properties |
|---|---|
| `Act` | Document record: `id`, `title`, `act_number`, `source_url`, `source_title`, `source_publisher`, `source_host`, `source_publication_date`, `source_type`, and `source_pdf_pages`. |
| `Chapter` | `id`, `act_id`, chapter number and Roman numeral, title, source file. |
| `Section` | Section identifier/number, chapter identifiers and title, citation, order, `has_subsections`, subsection count, source file, and section-level `text`. Where numbered subsections exist, this text excludes their bodies; a section with no subsections holds its full text. |
| `Subsection` | Its section/chapter numbers, numeric marker, ordinal, citation, source file, and the subsection body including nested lettered and Roman-numeral items. |
| `Passage` | Derived smaller retrieval text from long subsections: parent subsection ID, citation, section/subsection metadata, passage number/count/order, source file, and passage `text`. The parent subsection remains the full source text. |
| `LegalEntity` | A canonical legal concept such as a Commission, appeal, complaint, or remedy. Properties include `canonical_id`, `name`, `entity_type`, aliases, provision degree, and `expansion_eligible`. |

`SearchUnit` is an additional label on embedded `Section`, `Subsection`, and `Passage` nodes. It is not a separate graph node. The stored vectors use `BAAI/bge-small-en-v1.5` (384 dimensions). A subsection up to 220 words receives a whole-subsection embedding; a longer subsection receives linked, logically split `Passage` embeddings.

## Graph relationships

Structural relationships:

- `(Act)-[:HAS_CHAPTER]->(Chapter)`
- `(Chapter)-[:HAS_SECTION]->(Section)`
- `(Section)-[:HAS_SUBSECTION]->(Subsection)`
- `(Subsection)-[:HAS_PASSAGE]->(Passage)`
- `(Passage)-[:NEXT_PASSAGE]->(Passage)` for passage order

`CITES` connects a provision to another section or subsection when the Act explicitly references it. The import resolves the referenced provision within the parsed Act. Those deterministic citation edges currently carry `review_status: accepted`.

The ontology has **38 `LegalEntity` nodes, 351 typed provision-to-entity edges, and 85 `CITES` edges** in the saved extraction report. The 13 ontology relationship types are:

`DEFINES`, `ESTABLISHES`, `APPLIES_TO`, `IMPOSES_DUTY_ON`, `PROHIBITS`, `GRANTS_POWER_TO`, `ASSIGNS_JURISDICTION_TO`, `GOVERNS_PROCEDURE_FOR`, `MAKES_LIABLE`, `PROVIDES_RELIEF`, `PRESCRIBES_PENALTY_FOR`, `EXEMPTS_OR_LIMITS`, and `APPEALS_TO`.

Ontology relationship properties include `evidence_text`, `evidence_key`, `extraction_method`, `review_status`, and `act_id`. The concepts were extracted with controlled aliases and deterministic legal-cue rules, then filtered to concepts linking multiple provisions. **The ontology edges are still marked `unreviewed`**: use them as retrieval candidates, not as verified legal conclusions. See [legal_ontology.md](legal_ontology.md) for the full controlled vocabulary and intended meanings.

## Implemented retrieval pipeline

1. The caller selects `keyword`, `vector`, or `graph`.
2. A deterministic analyzer preserves the question (normalizing whitespace), extracts searchable terms, and recognizes explicit section citations. No Gemini key or query-analysis model is required.
3. Keyword mode searches the Neo4j full-text index over `Section`/`Subsection` text and citations. It uses OR across the extracted terms and explicit citations.
4. Vector mode embeds the normalized question with the same local BGE model used for the graph's vectors, then searches `SearchUnit` nodes in the Neo4j vector index.
5. Graph mode starts from vector matches, follows eligible provision → `LegalEntity` → provision links and `CITES`, and attaches relationship names and properties to expanded candidates. Passage seeds are resolved to their parent subsection for expansion. The combined graph candidate pool is capped.
6. All three modes pass their candidates to the same local `jinaai/jina-reranker-v1-turbo-en` cross-encoder, then return the requested top K with provision text, citations, official source metadata, and any graph expansion evidence.
7. The response includes grounding/abstention rules and stops before answer generation.

The current implementation is a Python retrieval service/CLI in [rag_backend.py](rag_backend.py), not yet a web server. The evaluator is [evaluate_retrieval.py](evaluate_retrieval.py). Keyword and vector command-line scripts remain available as standalone tools.

## Completed SLM, Verification, and Frontend Stack

1. **HTTP Backend API ([api_server.py](api_server.py))**:
   - FastAPI server exposing `/api/chat`, `/api/retrieve`, and `/api/health`.
   - Returns structured evidence items with stable IDs (`E1`, `E2`, ...), provision citations, source URLs, retrieval scores, reranker scores, and graph provenance metadata.
   - Built-in graceful offline failover ([offline_store.py](offline_store.py)) when Neo4j Aura is paused or unreachable.

2. **Context Token Budgeting ([context_builder.py](context_builder.py))**:
   - Enforces context token budgeting and avoids duplicate passages.
   - Preserves parent citations, statutory context, and official Government of India metadata.

3. **Provider-Neutral SLM Adapter ([slm_adapter.py](slm_adapter.py))**:
   - Provider interface supporting Qwen 2.5 (`LocalQwenSLMAdapter`), OpenAI/Ollama compatible endpoints (`OpenAICompatibleSLMAdapter`), and deterministic legal claim extraction (`DeterministicRuleBasedSLMAdapter`).
   - Enforces strict grounded output with structured atomic propositions and exact supporting quotes.

4. **Claim-to-Evidence Verification & Scoring ([claim_verifier.py](claim_verifier.py))**:
   - Validates supporting quotes against provision text and checks for statutory contradictions.
   - Classifies claims into `SUPPORTED`, `CONTRADICTED`, and `UNSUPPORTED`.
   - Computes weighted 4-factor evidence-strength score:
     $$\text{score} = 0.40 \times \text{entailment} + 0.25 \times \text{relevance} + 0.20 \times \text{citation} + 0.15 \times \text{conditions}$$
   - Maps scores into provisional evidence bands: Strong (85–100), Medium (70–84), Limited (50–69), Weak (0–49), and Unsupported.

5. **Legal Web Frontend ([static/](static/))**:
   - Glassmorphism dark-mode UI with gold and obsidian legal aesthetics.
   - Mode switching: Keyword, Vector, Graph Hybrid.
   - Interactive claim cards with status badges, strength progress bars, and score breakdowns.
   - Modal drawer displaying full statutory text and official Gazette PDF download link.
   - Explicit statutory abstention banner when evidence is insufficient.

6. **Test Suite ([test_legalguard.py](test_legalguard.py) & [test_live.py](test_live.py))**:
   - Pytest suite covering token budgeting, SLM parsing, claim verification, contradiction detection, abstention, and API endpoints (100% pass rate).

## Current limits

- Per-provision PDF page numbers are not yet stored; provision citations link directly to the official Act Gazette PDF.
- Ontology relationships remain marked `unreviewed` as retrieval navigation metadata. Only statutory provision text supports legal claims.

