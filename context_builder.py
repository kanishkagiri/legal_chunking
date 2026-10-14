"""Builds bounded context, handles token budgeting, and formats prompt for SLM."""

from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT_TEMPLATE = """You are an authoritative legal intelligence assistant specializing in the Consumer Protection Act, 2019 and Indian statutory law.

INSTRUCTIONS:
1. Provide a detailed, direct, and helpful legal answer to the user's question using the selected provisions below.
2. Write the answer as numbered points, with one complete rule or conclusion per point. Explain relevant procedures, responsible actors, conditions, time limits, exceptions, and remedies when the retrieved text supports them. Include enough points to answer fully; do not pad or repeat.
3. Ground your reasoning in the retrieved statutory provisions below whenever relevant.
4. The indexed source is the Consumer Protection Act, 2019. If the question requires another law or information not present in the retrieved provisions, say that the available Act text does not establish it; do not invent or imply unsupported legal rules.
5. Extract key atomic legal claims into the "claims" list. For each claim, cite the relevant evidence_id and copy an exact quote from the retrieved text if available (or use empty string if explaining a general legal principle).
6. Always return valid JSON matching the schema below.

Question:
{question}

Selected retrieval mode:
{retrieval_mode}

Retrieved statutory provisions:
{evidence_json}

Return format:
{{
  "answer": "",
  "claims": [],
  "insufficient_evidence": false
}}

The empty answer and claims above show the JSON shape only. Fill them with substantive, evidence-grounded content; never copy placeholder or example text."""


class ContextBuilder:
    """Manages token budgeting, evidence deduplication, and prompt formatting."""

    def __init__(self, max_context_tokens: int = 3072, reserved_response_tokens: int = 1024, tokenizer: Any = None):
        self.max_context_tokens = max_context_tokens
        self.reserved_response_tokens = reserved_response_tokens
        self.tokenizer = tokenizer

    def count_tokens(self, text: str) -> int:
        if self.tokenizer is not None:
            try:
                if hasattr(self.tokenizer, "encode"):
                    return len(self.tokenizer.encode(text))
            except Exception:
                pass
        # Robust fallback estimation (~4 chars per token for English legal text)
        return max(1, len(text) // 4)

    def build_evidence_bundle(
        self,
        raw_evidence: list[dict[str, Any]],
        question: str,
        mode: str,
    ) -> tuple[list[dict[str, Any]], str]:
        """Filters, deduplicates, budgets tokens, and produces evidence bundle & formatted prompt."""
        budget_for_prompt = self.max_context_tokens - self.reserved_response_tokens

        seen_texts: set[str] = set()
        budgeted_evidence: list[dict[str, Any]] = []

        for item in raw_evidence:
            text = (item.get("text") or "").strip()
            citation = item.get("citation") or ""
            key = f"{citation}:{text[:60]}"
            if not text or key in seen_texts:
                continue
            seen_texts.add(key)

            evidence_item = {
                "evidence_id": item.get("evidence_id") or f"E{len(budgeted_evidence) + 1}",
                "citation": citation,
                "node_type": item.get("node_type", "Section"),
                "text": text,
                "chapter_title": item.get("chapter_title", ""),
                "section_number": item.get("section_number"),
                "subsection_number": item.get("subsection_number"),
                "act_title": item.get("act_title", "Consumer Protection Act, 2019"),
                "source_url": item.get("source_url", "https://consumeraffairs.gov.in/public/upload/files/CP%20Act%202019_1732700731.pdf"),
                "source_title": item.get("source_title", "The Consumer Protection Act, 2019"),
                "source_publisher": item.get("source_publisher", "Government of India"),
                "source_publication_date": item.get("source_publication_date", "2019-08-09"),
                "retrieval_source": item.get("retrieval_source", mode),
                "retrieval_score": round(float(item.get("retrieval_score") or 0.0), 4),
                "reranker_score": round(float(item.get("reranker_score") or 0.0), 4),
            }

            if item.get("bridge_entity"):
                evidence_item["bridge_entity"] = item.get("bridge_entity")
                evidence_item["bridge_entity_name"] = item.get("bridge_entity_name")
            if item.get("expansion_relationships"):
                evidence_item["expansion_relationships"] = item.get("expansion_relationships")
                evidence_item["relationship_review_status"] = item.get("relationship_review_status", "unreviewed")

            test_list = budgeted_evidence + [evidence_item]
            test_json = json.dumps(test_list, indent=2, ensure_ascii=False)
            test_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                question=question,
                retrieval_mode=mode,
                evidence_json=test_json,
            )

            if self.count_tokens(test_prompt) <= budget_for_prompt or len(budgeted_evidence) == 0:
                budgeted_evidence.append(evidence_item)
            else:
                break

        # Re-index evidence_ids cleanly E1..En
        for idx, ev in enumerate(budgeted_evidence, start=1):
            ev["evidence_id"] = f"E{idx}"

        prompt_evidence = [
            {
                "evidence_id": ev["evidence_id"],
                "citation": ev["citation"],
                "text": ev["text"],
            }
            for ev in budgeted_evidence
        ]
        evidence_json = json.dumps(prompt_evidence, indent=2, ensure_ascii=False)
        final_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            question=question,
            retrieval_mode=mode,
            evidence_json=evidence_json,
        )
        return budgeted_evidence, final_prompt
