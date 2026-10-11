# Retrieval Mode Comparison

Run time (UTC): 2026-10-11T13:14:06.408017+00:00

## Scope and setup

Nine manually labeled questions over the Consumer Protection Act 2019; retrieval-only evaluation, no generated answers.

Candidate pool: up to 25; final reranked context: top 5. Query embeddings use BAAI/bge-small-en-v1.5; reranking uses jinaai/jina-reranker-v1-turbo-en.

Query analysis providers: deterministic_rules: 9.

## Run the retrieval pipeline

From the project directory, run the CLI with the chosen retrieval mode:

```powershell
.venv\Scripts\python.exe rag_backend.py "What can the Central Authority do about a misleading advertisement?" --mode graph --top-k 5 --candidate-limit 25
```

Valid modes are `keyword`, `vector`, and `graph`. The response contains the reranked top-k evidence, Act source metadata, and graph relationship names/properties when expansion supplied a candidate. It stops before SLM generation and includes answer-grounding rules for the next stage.

Metrics are calculated at the citation level after reranking. Precision@5 uses five as the fixed context budget; Recall@5 counts labeled relevant citations found; MRR@5 rewards the earliest relevant citation; nDCG@5 rewards relevant citations near the top; Hit@5 records whether at least one gold citation appears.

This measures retrieval ranking only. There is no SLM answer generation, so the table does not measure answer correctness, hallucination rate, or citation faithfulness. The questions and gold citations are a small manually labeled sample, not a general benchmark.

## Average metrics

| Mode | precision@5 | recall@5 | mrr@5 | ndcg@5 | hit@5 |
|---|---:|---:|---:|---:|---:|
| keyword | 0.178 | 0.583 | 0.481 | 0.489 | 0.667 |
| vector | 0.222 | 0.806 | 0.615 | 0.656 | 0.889 |
| graph | 0.244 | 0.833 | 0.704 | 0.734 | 0.889 |

## Per-question results

| Question | Expected strength | Gold citations | Keyword (ranked citations) | Vector (ranked citations) | Graph (ranked citations) |
|---|---|---|---|---|---|
| What practices are included in the definition of unfair trade practice? | keyword | Section 2(47) | Section 2(47) (1), Section 2(9) (2), Section 18(2) (3), Section 2(41) (4), Section 18(1) (5) | Section 2(47) (1), Section 35(1) (2), Section 2(41) (3), Section 2(6) (4), Section 2(28) (5) | Section 2(47) (1), Section 35(1) (2), Section 18(2) (3), Section 2(41) (4) |
| What can the Central Authority do under Section 21(1) about a misleading advertisement? | keyword | Section 21(1) | Section 21(1) (1), Section 21(3) (2), Section 21(2) (3), Section 21(4) (4), Section 18(1) (5) | Section 21(1) (1), Section 21(3) (2), Section 21(2) (3), Section 21(4) (4), Section 18(1) (5) | Section 21(1) (1), Section 21(3) (2), Section 21(2) (3), Section 21(4) (4), Section 18(1) (5) |
| Which provision says a consumer can seek compensation for loss or injury caused by negligence? | keyword | Section 2(11), Section 39(1) | Section 39(1) (1), Section 2(11) (2), Section 90(1) (3), Section 91(1) (4), Section 82 (5) | Section 39(1) (1), Section 2(11) (2), Section 91(1) (3), Section 82 (4) | Section 39(1) (1), Section 2(11) (2), Section 90(1) (3), Section 91(1) (4) |
| If something bought online is faulty, what remedies can the consumer forum grant? | vector | Section 39(1) | Section 1(1) (1), Section 74(3) (2), Section 87(3) (3), Section 81(3) (4), Section 2(25) (5) | Section 35(2) (1), Section 94 (2), Section 87(3) (3), Section 87(1) (4), Section 39(1) (5) | Section 35(2) (1), Section 94 (2), Section 39(1) (3), Section 49(1) (4), Section 59(1) (5) |
| Can a group of people affected in the same way bring one case together? | vector | Section 2(5), Section 35(1) | Section 38(6) (1), Section 21(7) (2), Section 36(1) (3), Section 21(1) (4), Section 62 (5) | Section 36(1) (1), Section 62 (2), Section 65(4) (3), Section 48 (4), Section 35(2) (5) | Section 73(2) (1), Section 36(1) (2), Section 62 (3), Section 65(4) (4), Section 48 (5) |
| What happens when deciding whether a product is defective requires specialist testing? | vector | Section 38(2) | Section 83 (1), Section 2 (2), Section 82 (3), Section 48 (4), Section 38(7) (5) | Section 38(2) (1), Section 83 (2), Section 82 (3), Section 39(1) (4), Section 85 (5) | Section 38(2) (1), Section 83 (2), Section 82 (3), Section 39(1) (4) |
| What procedure applies to an analysis or test of articles other than those covered by Section 38(2)? | graph | Section 38(5), Section 38(2) | Section 22(5) (1), Section 38(2) (2), Section 38(12) (3), Section 38(5) (4), Section 38(3) (5) | Section 22(5) (1), Section 38(2) (2), Section 38(5) (3), Section 38(3) (4) | Section 22(5) (1), Section 38(2) (2), Section 38(5) (3) |
| Where can a consumer appeal a District Commission order, and what is the statutory route? | graph | Section 41 | Section 28(2) (1), Section 81(1) (2), Section 41 (3), Section 38(11) (4), Section 42(3) (5) | Section 28(2) (1), Section 41 (2), Section 38(8) (3), Section 28(1) (4), Section 73(2) (5) | Section 41 (1), Section 42(3) (2), Section 28(1) (3), Section 68 (4), Section 24 (5) |
| How does the Act connect misleading advertisements with unfair trade practices? | graph | Section 2(28), Section 2(47), Section 17, Section 21 | Section 18(1) (1), Section 2(28) (2), Section 10(1) (3), Section 22(1) (4), Section 19(1) (5) | Section 18(1) (1), Section 39(1) (2), Section 2(28) (3), Section 10(1) (4), Section 19(1) (5) | Section 39(1) (1), Section 2(28) (2), Section 16 (3), Section 17 (4), Section 21(1) (5) |

## Interpretation

Best average mode(s) by metric: precision@5: graph; recall@5: graph; mrr@5: graph; ndcg@5: graph; hit@5: vector, graph.

The exact Section 21(1) question put the gold citation first in keyword, vector, and graph results. Graph mode ranked Section 41 first for the appeal question (vector ranked it second) and surfaced Sections 17 and 21 among the related-concepts results. On the explicit cross-reference question it returned both labeled citations within the top three, comparable to vector mode. It did not recover every labeled citation on every query. These observations apply to this small manually labeled set, not to all legal questions.

Graph expansion exposes the connecting relationship types and stored relationship properties with each expanded candidate. Ontology edges were previously marked `unreviewed`; they are surfaced as candidate expansion evidence and should not be treated as verified legal conclusions. Explicit `CITES` edges are also returned with their stored reference/evidence properties.
