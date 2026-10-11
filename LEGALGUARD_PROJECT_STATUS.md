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

## Current limits

- No SLM answer generation, atomic-claim extraction, claim verification, confidence display, or chat frontend has been implemented.
- The query analyzer is deliberately simple. It does not perform synonym expansion, legal reasoning, or model-based query rewriting.
- The parser records source file and provision citation but does not provide verified PDF page numbers for each provision. Section links to the official PDF can be displayed now; precise page anchors need page mapping added to the parser/metadata.
- The nine-question retrieval evaluation is a small manually labeled sample. It measures citation retrieval after reranking, not legal answer correctness.
