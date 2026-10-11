# Which retrieval mode helped on which questions?

## Experiment setup

The comparison used nine hand-labeled questions, one shared deterministic query analyzer, the same BGE question embedding model, a 25-candidate limit, the same local cross-encoder reranker, and the top five citations. Metrics are citation-level and are not answer-quality or hallucination measures. The full ranked outputs are in [retrieval_comparison.md](retrieval_comparison.md) and [parsed_output/retrieval_comparison.json](parsed_output/retrieval_comparison.json).

## Average metric results

| Retrieval mode | Precision@5 | Recall@5 | MRR@5 | nDCG@5 | Hit@5 |
|---|---:|---:|---:|---:|---:|
| Keyword | 0.178 | 0.583 | 0.481 | 0.489 | 0.667 |
| Vector | 0.222 | 0.806 | 0.615 | 0.656 | 0.889 |
| Graph hybrid | **0.244** | **0.833** | **0.704** | **0.734** | **0.889** |

Graph hybrid led the average precision, recall, reciprocal rank, and nDCG in this sample. Vector and graph tied on Hit@5. The sample is small; treat this as an initial result, not proof that graph retrieval is best for every query or corpus.

## Query types and examples

### Keyword retrieval

Keyword retrieval is a good fit when a question uses statutory wording, names a legal body or practice, or gives an exact citation. It is especially useful when a provision number or a phrase is known.

Example: **“What can the Central Authority do under Section 21(1) about a misleading advertisement?”** Keyword returned `Section 21(1)` at rank 1. All three modes returned it at rank 1, so this exact-citation example does not show keyword outperforming the other modes. On the definition question **“What practices are included in the definition of unfair trade practice?”**, keyword also put `Section 2(47)` first.

### Vector retrieval

Vector retrieval is useful when the user paraphrases a legal concept, uses everyday terms, or describes a scenario without repeating statutory wording.

Example: **“What happens when deciding whether a product is defective requires specialist testing?”** Vector and graph both returned `Section 38(2)` at rank 1; keyword did not place it in its top five. For **“If something bought online is faulty, what remedies can the consumer forum grant?”**, vector found `Section 39(1)` at rank 5, while graph placed it at rank 3. This demonstrates the possibility of a semantic match, but rank 5 is a weak result for a top-five context.

### Graph hybrid retrieval

Graph hybrid is useful when a question asks how provisions connect, asks about an explicit cross-reference, or describes a multi-step legal route. It starts from vector matches and adds bounded candidates reachable through eligible legal concepts and `CITES` relationships.

Examples:

- **“Where can a consumer appeal a District Commission order, and what is the statutory route?”** Graph returned `Section 41` at rank 1; vector ranked it second and keyword third.
- **“How does the Act connect misleading advertisements with unfair trade practices?”** Graph surfaced `Sections 17` and `21` in its top five, alongside `Section 2(28)`. Vector and keyword found `Section 2(28)`, but did not return `Sections 17` and `21` in their top five.
- **“What procedure applies to an analysis or test of articles other than those covered by Section 38(2)?”** Graph returned `Sections 38(2)` and `38(5)` in its top three. Vector also found both in its top four, so the sample shows a good result but not a graph-only win.

## Practical choice

Keep all three modes available. Use keyword for exact terms and citations, vector for natural-language paraphrases, and graph hybrid for questions that need related provisions or explicit legal routes. The evaluation can identify weak queries for each mode; do not infer a universal winner from nine examples.

The graph mode currently uses ontology edges that are marked `unreviewed`, so expanded graph candidates carry the relationship evidence and review status. Before allowing an SLM to rely on an expanded candidate as legal support, validate the passage text itself and its citation. Graph reachability is a retrieval hint, not a substitute for source text.
