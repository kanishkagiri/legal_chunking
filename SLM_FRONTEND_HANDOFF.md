# Next phase: SLM answers, atomic claim checks, and the frontend

## Current stopping point

The retrieval service now returns the reranked top K evidence for the selected mode, including provision text, citation, official source metadata, and graph relationship evidence where applicable. It stops before answer generation. There is not yet an HTTP chat API, SLM adapter, claim verifier, or frontend.

## Proposed request flow

1. **Frontend sends the request to the backend.** Send the user's question, selected mode (`keyword`, `vector`, or `graph`), and conversation ID if needed. Do not send provider keys from the browser.
2. **Backend retrieves evidence.** Call `LegalRAGRetriever.retrieve(...)`. Keep the original question and normalized query in the request trace.
3. **Build a bounded context.** Pass evidence records with an evidence ID, citation, text, section/subsection metadata, Act title, publisher, date, and official source URL. Count tokens with the chosen Qwen tokenizer and stay below its actual configured context limit, reserving tokens for the prompt and answer. Prefer directly retrieved passages and avoid duplicate passages with the same citation when they add no new text.
4. **Handle graph metadata carefully.** Return the relationship type, bridge concept, `evidence_text`, `reference_text`, and edge `review_status` as navigation/provenance metadata. An ontology connection marked `unreviewed` is a retrieval lead. The SLM must ground legal claims in the provision text itself; graph proximity alone is not legal evidence.
5. **Ask the SLM for structured answer claims.** Use a provider-neutral model adapter so Qwen 2.5 3B can be connected when available. Require JSON output with an answer made of atomic claims and evidence IDs per claim.
6. **Verify every claim before display.** Validate evidence IDs and citations against the retrieved bundle, validate any quoted text against that evidence, and classify the claim as `SUPPORTED`, `CONTRADICTED`, or `UNSUPPORTED`. A separate verifier prompt can help assess entailment, but the verifier is still a model and must be evaluated. Keep human review available for high-impact or ambiguous claims.
7. **Attach the Act source to every claim.** Build source links on the backend from the matched evidence node's `source_url`, `source_title`, `source_publisher`, and `source_publication_date`. Do not accept arbitrary URLs invented by the SLM. The current graph stores the official PDF URL but not a verified source PDF page for every provision, so do not claim page-level linking until page metadata is added.
8. **Return structured results to the frontend.** The UI displays the answer, individual claim text, status/evidence-strength badge, provision citation, and a clickable official source link with the supporting excerpt.

## Suggested model output contract

Have the SLM return a constrained object like this. The model proposes the claims and evidence IDs; the backend owns source URLs and final verification status.

```json
{
  "answer": "The District Commission may give the opposite party 30 days to submit its version and may grant an extension of up to 15 days.",
  "claims": [
    {
      "claim_id": "C1",
      "text": "The District Commission may give the opposite party 30 days to submit its version.",
      "evidence_ids": ["E1"],
      "supporting_quote": "within a period of thirty days"
    },
    {
      "claim_id": "C2",
      "text": "The Commission may grant an extension not exceeding 15 days.",
      "evidence_ids": ["E1"],
      "supporting_quote": "such extended period not exceeding fifteen days"
    }
  ],
  "insufficient_evidence": false
}
```

This example is based on Section 38(2)(a). Split sentences containing independent legal propositions into separate claims. Preserve actors, time limits, conditions, provisos, and exceptions. If the context does not support a claim, the SLM should omit it and set `insufficient_evidence` when it cannot answer the question from the supplied Act text.

## Draft system prompt for the SLM

```text
You answer questions only from the supplied Consumer Protection Act, 2019 evidence.

Rules:
1. Do not use outside knowledge, assumptions, or facts that are not in the evidence.
2. If the evidence does not establish an answer, say that the retrieved Act text is insufficient. Do not guess.
3. Break the answer into atomic claims: one independently checkable legal proposition per claim. Split claims joined by “and” when either part can be true or false independently.
4. For every claim, include one or more evidence_ids from the supplied evidence bundle and a short exact supporting_quote copied from that evidence.
5. Do not invent citations, evidence IDs, source URLs, page numbers, dates, or publishers. Use only citations present in the evidence. The backend adds official source metadata.
6. Preserve the provision's actor, action, conditions, negation, deadlines, amounts, provisos, and exceptions. Do not turn a permission into a duty or omit a limiting condition.
7. Graph relationship names and unreviewed ontology links can help you find related provisions. They are not themselves proof of a legal rule. Ground claims in the supplied provision text.
8. Return only JSON matching the requested schema. Do not add a confidence percentage; the backend calculates a provisional evidence-strength score after checking each claim.

Question:
{question}

Selected retrieval mode:
{retrieval_mode}

Evidence bundle:
{evidence_json}

Return:
{
  "answer": "short answer assembled only from the claims below",
  "claims": [
    {
      "claim_id": "C1",
      "text": "one atomic claim",
      "evidence_ids": ["E1"],
      "supporting_quote": "exact quote from the evidence"
    }
  ],
  "insufficient_evidence": false
}
```

## Claim verification and evidence labels

Keep **verification status** separate from the numeric evidence-strength score:

- **SUPPORTED**: the cited Act text directly entails the claim, including material conditions and exceptions.
- **CONTRADICTED**: authoritative retrieved Act text states the opposite or an applicable exception excludes the claim. Contradiction is not the same as missing evidence.
- **UNSUPPORTED**: no cited provision directly supports or contradicts the claim, or the citation/quote cannot be validated. A graph edge alone is insufficient support.

Suggested first-pass weighted evidence-strength score for each claim (all component scores are 0–100):

```text
score = 0.40 × entailment
      + 0.25 × evidence relevance
      + 0.20 × citation validity
      + 0.15 × conditions-and-exceptions coverage
```

Where:

- **Entailment (40%)**: how directly the provision text supports the atomic claim.
- **Evidence relevance (25%)**: how directly the retrieved passage addresses this specific claim, rather than only the topic.
- **Citation validity (20%)**: whether the evidence ID and provision citation exist and the displayed source URL comes from the Act node.
- **Conditions/exceptions coverage (15%)**: whether the claim preserves the rule's actor, scope, negation, provisos, time/amount limits, and exceptions.

Example for the two Section 38(2)(a) claims above: if the verifier gives entailment 90, relevance 80, citation validity 100, and qualifier coverage 70, then `0.40×90 + 0.25×80 + 0.20×100 + 0.15×70 = 86.5`, which maps to **Strong evidence** under the provisional bands below. The claims would still need a `SUPPORTED` status from verification. If an applicable text contradicts a claim, mark it `CONTRADICTED` regardless of the weighted average. If no valid supporting or contradicting text exists, mark it `UNSUPPORTED` rather than letting a high relevance score imply legal support.

Provisional user-facing labels:

| Score | Evidence label |
|---:|---|
| 85–100 | Strong evidence |
| 70–84 | Medium evidence |
| 50–69 | Limited evidence |
| 0–49 | Weak evidence |
| No valid evidence / no entailment | Unsupported (status, not a numeric band) |

Call this an **evidence-strength estimate**, not a calibrated probability or legal confidence. A model's self-reported confidence is not a score. Before showing this metric to users, label a set of atomic claims with legal reviewers, compare component scores and final bands to those labels, tune weights/thresholds, and measure false-supported and false-contradicted rates. If an authoritative contradiction is detected, it takes priority over the average.

## Frontend presentation

- Provide a retrieval-mode selector with plain labels: Keyword, Vector, and Graph hybrid.
- Display the short answer, then one card per atomic claim. Each card shows its claim text, `SUPPORTED` / `CONTRADICTED` / `UNSUPPORTED`, and evidence-strength label/score when applicable.
- Add inline citation chips (for example, `Section 38(2)(a)`) beside the specific claim they support.
- Clicking a citation opens the official Act PDF URL and shows the exact retrieved excerpt in the app. Add a page fragment only after provision-to-PDF-page mapping is stored and verified.
- Keep a sources panel with official document title, publisher, publication date, and URL. For graph-expanded evidence, optionally show “related via [relationship]” with the review status, visually separated from direct statutory evidence.
- Show an insufficient-evidence message when the response abstains. Do not show a high confidence badge for a response with unsupported or contradicted claims.

## To do

1. Add an HTTP backend endpoint that accepts `question` and `retrieval_mode`, calls the existing retriever, and returns a stable typed evidence schema. Add request validation, safe errors, and CORS for the local frontend.
2. Define the evidence bundle and claim-response schemas; assign stable evidence IDs to each returned result.
3. Add a provider interface for text generation and connect Qwen 2.5 3B when available. Keep model and API configuration on the backend.
4. Add context token budgeting using the selected SLM tokenizer. Include only top-ranked evidence within budget while retaining parent citation and source information for passages.
5. Implement the grounded-answer prompt and JSON parsing. Retry or abstain on invalid schema; never silently strip unsupported claims.
6. Implement claim-to-evidence verification, exact quote validation, citation/source validation, and the separate supported/contradicted/unsupported status.
7. Build the ChatGPT-style legal frontend with mode selection, claim cards, source citations, supporting excerpts, and an explicit insufficient-evidence state.
8. Evaluate retrieval and answer quality separately: retrieval Recall/MRR/nDCG; claim citation coverage; supported/contradicted/unsupported classification; and abstention on unanswerable questions.

## Prompt for a coding AI to continue the project

Copy the following prompt into the coding model that will implement the next phase:

```text
Continue the Legalguard Consumer Protection Act RAG project in the current repository. First inspect the existing files and follow their graph schema; do not recreate or re-import the graph.

Current implementation:
- Neo4j stores Act, Chapter, Section, Subsection, Passage, and LegalEntity nodes.
- SearchUnit is a label on embedded Section/Subsection/Passage nodes, not a separate node.
- Relationships include HAS_CHAPTER, HAS_SECTION, HAS_SUBSECTION, HAS_PASSAGE, NEXT_PASSAGE, explicit CITES, and the typed ontology relationships documented in LEGALGUARD_PROJECT_STATUS.md and legal_ontology.md.
- rag_backend.py supports keyword, vector, and graph hybrid retrieval, a shared local reranker, Act source metadata, and answer-grounding rules. It stops after returning top K; no answer model or frontend exists yet.
- Query analysis is deterministic and model-free. Do not add a Gemini dependency.
- The official Act PDF URL and publisher/date are attached to the Act record. Per-provision PDF page numbers are not yet stored.
- Ontology relationships are marked unreviewed. Never treat graph connectivity alone as proof of a legal claim.

Implement the remaining pipeline in small reviewable steps:
1. Add a backend HTTP API for retrieval and chat. Validate the selected mode and return typed evidence items with stable evidence IDs, provision citation, text, source URL/title/publisher/date, retrieval scores, and graph relationship names/properties/status where relevant. Never send credentials to the browser.
2. Add a provider-neutral SLM adapter and configure it for Qwen 2.5 3B when the model becomes available. Keep the current retrieval backend independent of the answer model. Enforce a context token budget using the answer model's tokenizer.
3. Use a strict grounded prompt: answer only from supplied Act text; preserve conditions, provisos, negation, deadlines, amounts, and exceptions; abstain if evidence is insufficient; never invent citations or URLs.
4. Require structured JSON with an answer and atomic claims. Each claim must have one independently checkable proposition, evidence IDs, and an exact short supporting quote. Do not ask the SLM to self-score confidence.
5. Verify every claim against its cited evidence. Validate IDs/citations/quotes, then classify it as SUPPORTED, CONTRADICTED, or UNSUPPORTED. Keep graph edges as navigation metadata; only provision text supports a claim. Add a provisional evidence-strength estimate using entailment 40%, relevance 25%, citation validity 20%, and conditions/exceptions coverage 15%, with bands: Strong 85-100, Medium 70-84, Limited 50-69, Weak 0-49. Unsupported is a separate status, not a low-confidence synonym. Do not present the score as calibrated probability until evaluated against human labels.
6. Build a legal-themed chat frontend with retrieval-mode selection, atomic claim cards, inline provision citations, official source links, supporting excerpts, evidence status, and abstention state. Display page links only if verified page metadata exists.
7. Keep retrieval evaluation separate from answer/claim evaluation. Add test cases for exact citations, paraphrases, cross-references, exceptions/negation, multi-provision questions, and questions unanswerable from this Act.

Do not modify the Act text or mutate Neo4j as part of this phase unless specifically required. Do not expose .env values. Before implementation, report a short plan and any schema assumptions; then implement and document the API/request/response contract, prompt, verification logic, frontend flow, tests, and known limitations.
```
