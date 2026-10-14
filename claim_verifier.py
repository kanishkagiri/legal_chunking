"""Claim-to-evidence verifier and 4-factor evidence-strength scoring engine."""

from __future__ import annotations

import re
from typing import Any


class ClaimVerifier:
    """Verifies atomic claims against retrieved evidence provisions and calculates evidence-strength."""

    def __init__(self):
        pass

    def verify_claims(
        self,
        claims: list[dict[str, Any]],
        evidence_bundle: list[dict[str, Any]],
        question: str,
    ) -> list[dict[str, Any]]:
        evidence_map: dict[str, dict[str, Any]] = {}
        for ev in evidence_bundle:
            eid = ev.get("evidence_id")
            if eid:
                evidence_map[eid] = ev
            cit = ev.get("citation", "").lower()
            if cit:
                evidence_map[cit] = ev
            sec = str(ev.get("section_number") or "").strip()
            if sec:
                evidence_map[f"section {sec}"] = ev
                evidence_map[sec] = ev

        verified_claims = []
        for claim in claims:
            verified = self._verify_single_claim(claim, evidence_map, evidence_bundle, question)
            verified_claims.append(verified)

        return verified_claims

    def extract_atomic_claims_from_answer(
        self,
        answer: str,
        evidence_bundle: list[dict[str, Any]],
        existing_claims: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Ensures at least 2-4 structured atomic claims are extracted and linked to evidence."""
        valid_existing = [
            c for c in (existing_claims or [])
            if isinstance(c, dict) and len((c.get("text") or "").strip()) >= 20
        ]
        if len(valid_existing) >= 3:
            return valid_existing

        if not answer or not evidence_bundle:
            return valid_existing

        # Extract sentences from answer
        raw_sentences = re.split(r"(?<=[.!?])\s+", answer.strip())
        claims_list = []
        for c in valid_existing:
            claims_list.append({**c, "claim_id": f"C{len(claims_list) + 1}"})

        claim_counter = len(claims_list) + 1

        for raw_s in raw_sentences:
            s = raw_s.strip()
            if len(s) < 22 or s.startswith(("In summary", "Based on", "According to", "Overall")):
                continue
            # Check if this sentence is already covered
            if any(s.lower() in (c.get("text", "").lower()) for c in claims_list):
                continue

            # Find best matching evidence item
            s_tokens = set(re.findall(r"[a-z0-9]{3,}", s.lower()))
            best_ev = None
            best_overlap = 0

            for ev in evidence_bundle:
                ev_tokens = set(re.findall(r"[a-z0-9]{3,}", ev.get("text", "").lower()))
                overlap = len(s_tokens & ev_tokens)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_ev = ev

            if best_ev and best_overlap >= 2:
                claims_list.append({
                    "claim_id": f"C{claim_counter}",
                    "text": s,
                    "evidence_ids": [best_ev.get("evidence_id", "E1")],
                    "supporting_quote": "",  # will be auto-resolved from statutory text
                })
                claim_counter += 1
                if len(claims_list) >= 4:
                    break

        return claims_list if claims_list else valid_existing

    def _verify_single_claim(
        self,
        claim: dict[str, Any],
        evidence_map: dict[str, dict[str, Any]],
        evidence_bundle: list[dict[str, Any]],
        question: str,
    ) -> dict[str, Any]:
        claim_id = claim.get("claim_id", "C1")
        claim_text = (claim.get("text") or "").strip()
        evidence_ids = claim.get("evidence_ids", [])
        supporting_quote = (claim.get("supporting_quote") or "").strip()

        # Step 1: Citation & Evidence Existence
        primary_ev = None
        matched_ev_id = None

        if evidence_ids and isinstance(evidence_ids, list):
            for eid in evidence_ids:
                eid_clean = str(eid).strip()
                if eid_clean in evidence_map:
                    primary_ev = evidence_map[eid_clean]
                    matched_ev_id = primary_ev.get("evidence_id", eid_clean)
                    break
                eid_lower = eid_clean.lower()
                if eid_lower in evidence_map:
                    primary_ev = evidence_map[eid_lower]
                    matched_ev_id = primary_ev.get("evidence_id", eid_clean)
                    break

        # Fallback: Search evidence bundle for best matching provision by token overlap
        if not primary_ev and evidence_bundle:
            c_tokens = set(re.findall(r"[a-z0-9]{3,}", claim_text.lower()))
            best_ev = None
            best_score = 0
            for ev in evidence_bundle:
                cit_lower = ev.get("citation", "").lower()
                if cit_lower and cit_lower in claim_text.lower():
                    best_ev = ev
                    break
                ev_tokens = set(re.findall(r"[a-z0-9]{3,}", ev.get("text", "").lower()))
                overlap = len(c_tokens & ev_tokens)
                if overlap > best_score:
                    best_score = overlap
                    best_ev = ev
            if best_ev and (best_score >= 2 or not evidence_ids):
                primary_ev = best_ev
                matched_ev_id = best_ev.get("evidence_id", "E1")

        if not primary_ev:
            return {
                "claim_id": claim_id,
                "text": claim_text,
                "evidence_ids": evidence_ids,
                "supporting_quote": supporting_quote,
                "verification_status": "UNSUPPORTED",
                "evidence_label": "Unsupported",
                "evidence_strength_score": 0.0,
                "component_scores": {
                    "entailment": 0.0,
                    "relevance": 0.0,
                    "citation_validity": 0.0,
                    "conditions_coverage": 0.0,
                },
                "status_reason": f"Cited evidence ID {evidence_ids} does not exist in the retrieved evidence bundle.",
                "citation": None,
                "official_source": None,
            }

        provision_text = primary_ev.get("text", "")
        citation = primary_ev.get("citation", "")

        # Step 2: Supporting Quote Validation & Fallback Extraction
        quote_found, quote_match_type, resolved_quote = self._resolve_and_validate_quote(
            supporting_quote, claim_text, provision_text
        )

        # Step 3: Check for Contradiction
        is_contradicted, contradiction_reason = self._check_contradiction(claim_text, provision_text)

        # Step 4: Calculate 4 Component Scores (0 to 100)
        # Component 1: Entailment (40%)
        entailment_score = self._calc_entailment(
            claim_text, provision_text, quote_found, quote_match_type, resolved_quote
        )

        # Component 2: Evidence Relevance (25%)
        relevance_score = self._calc_relevance(claim_text, question, primary_ev)

        # Component 3: Citation Validity (20%)
        citation_validity_score = self._calc_citation_validity(primary_ev)

        # Component 4: Conditions & Exceptions Coverage (15%)
        conditions_score = self._calc_conditions_coverage(claim_text, provision_text)

        # Step 5: Weighted Evidence Strength Score
        weighted_score = (
            0.40 * entailment_score
            + 0.25 * relevance_score
            + 0.20 * citation_validity_score
            + 0.15 * conditions_score
        )
        weighted_score = round(max(0.0, min(100.0, weighted_score)), 1)

        # Step 6: Determine Verification Status & Evidence Label
        if is_contradicted:
            status = "CONTRADICTED"
            label = "Contradicted"
            status_reason = contradiction_reason
        elif not quote_found or entailment_score < 40.0:
            status = "UNSUPPORTED"
            label = "Unsupported"
            status_reason = (
                "Supporting quote not found in provision text."
                if not quote_found
                else "Provision text does not sufficiently entail the legal claim."
            )
        else:
            status = "SUPPORTED"
            if weighted_score >= 80.0:
                label = "Strong evidence"
            elif weighted_score >= 65.0:
                label = "Medium evidence"
            elif weighted_score >= 50.0:
                label = "Limited evidence"
            else:
                label = "Weak evidence"
            status_reason = f"Grounding verified against {citation}."

        official_source = {
            "title": primary_ev.get("source_title", "The Consumer Protection Act, 2019"),
            "publisher": primary_ev.get("source_publisher", "Government of India"),
            "date": primary_ev.get("source_publication_date", "2019-08-09"),
            "url": primary_ev.get("source_url", "https://consumeraffairs.gov.in/public/upload/files/CP%20Act%202019_1732700731.pdf"),
            "citation": citation,
            "chapter_title": primary_ev.get("chapter_title", ""),
            "passage_text": provision_text,
        }

        return {
            "claim_id": claim_id,
            "text": claim_text,
            "evidence_ids": [matched_ev_id or primary_ev.get("evidence_id", "E1")],
            "supporting_quote": resolved_quote,
            "verification_status": status,
            "evidence_label": label,
            "evidence_strength_score": weighted_score if status != "UNSUPPORTED" else 0.0,
            "component_scores": {
                "entailment": entailment_score,
                "relevance": relevance_score,
                "citation_validity": citation_validity_score,
                "conditions_coverage": conditions_score,
            },
            "status_reason": status_reason,
            "citation": citation,
            "official_source": official_source,
        }

    def _resolve_and_validate_quote(
        self, quote: str, claim_text: str, provision_text: str
    ) -> tuple[bool, str, str]:
        """Validates provided quote or dynamically extracts matching statutory excerpt."""
        clean_text = " ".join(provision_text.split()).lower()

        # 1. If non-empty quote was provided, attempt matching
        if quote and quote.strip():
            clean_quote = " ".join(quote.split()).lower()
            if clean_quote in clean_text:
                return True, "exact", quote.strip()

            sub_q = re.sub(r"[^\w\s]", "", clean_quote)
            sub_t = re.sub(r"[^\w\s]", "", clean_text)
            if sub_q and sub_q in sub_t:
                return True, "normalized", quote.strip()

            q_words = sub_q.split()
            if len(q_words) >= 4:
                subsequence = " ".join(q_words[:max(3, int(len(q_words) * 0.75))])
                if subsequence in sub_t:
                    return True, "partial", quote.strip()

            # If quote was provided but has 0 token overlap with the provision, it is fabricated
            q_tokens = set(re.findall(r"[a-z0-9]{3,}", clean_quote))
            t_tokens = set(re.findall(r"[a-z0-9]{3,}", clean_text))
            if len(q_tokens & t_tokens) == 0:
                return False, "not_found", quote.strip()

        # 2. Extract best matching sentence/clause from statutory provision
        sentences = [s.strip() for s in re.split(r"(?<=[.;\n])\s+", provision_text) if len(s.strip()) > 15]
        if not sentences:
            sentences = [provision_text.strip()]

        claim_tokens = set(re.findall(r"[a-z0-9]{3,}", claim_text.lower()))
        quote_tokens = set(re.findall(r"[a-z0-9]{3,}", (quote or "").lower()))
        target_tokens = claim_tokens | quote_tokens

        best_sentence = ""
        best_overlap = 0

        for s in sentences:
            s_tokens = set(re.findall(r"[a-z0-9]{3,}", s.lower()))
            overlap = len(target_tokens & s_tokens)
            if overlap > best_overlap:
                best_overlap = overlap
                best_sentence = s

        if best_overlap >= 2 and best_sentence:
            return True, "extracted", best_sentence

        # Fallback to provided quote if not empty, otherwise empty
        return False, "not_found", quote.strip() if quote else ""

    def _check_contradiction(self, claim: str, text: str) -> tuple[bool, str]:
        claim_lower = claim.lower()
        text_lower = text.lower()

        # Check explicit contradictory statutory patterns
        if "without any appeal" in claim_lower and "appeal shall lie" in text_lower:
            return True, "Act explicitly provides for an appeal contrary to claim."

        if "no appeal shall lie" in claim_lower and "may prefer an appeal" in text_lower:
            return True, "Act explicitly provides for an appeal contrary to claim."

        if "no penalty" in claim_lower and ("penalty" in text_lower or "imprisonment" in text_lower):
            return True, "Act prescribes penalty or imprisonment contrary to claim."

        if "exempt from liability" in claim_lower and "shall be liable" in text_lower:
            return True, "Act imposes liability contrary to claim."

        return False, ""

    def _calc_entailment(
        self, claim: str, text: str, quote_found: bool, quote_type: str, resolved_quote: str = ""
    ) -> float:
        if not quote_found:
            return 20.0

        score = 65.0
        if quote_type == "exact":
            score += 25.0
        elif quote_type in ("normalized", "extracted"):
            score += 20.0
        else:
            score += 15.0

        claim_lower = claim.lower()
        ref_text = (resolved_quote or text).lower()

        # Check modal verb / actor alignment ("may", "shall", "must", "order", "direct")
        for modal in ("shall", "may", "direct", "penalty", "order", "within", "appeal", "deposit", "commission", "days"):
            if modal in claim_lower and modal in ref_text:
                score += 2.0

        return min(100.0, score)

    def _calc_relevance(self, claim: str, question: str, ev: dict[str, Any]) -> float:
        reranker_score = ev.get("reranker_score", 0.0)
        # Handle normalized reranker score (0.0 to 1.0) or logit
        if 0.0 <= float(reranker_score) <= 1.0:
            base = 65.0 + (float(reranker_score) * 25.0)
        else:
            base = 70.0 + (float(reranker_score) * 6.0)
        base = max(40.0, min(95.0, base))

        q_tokens = set(re.findall(r"[a-z0-9]+", question.lower()))
        c_tokens = set(re.findall(r"[a-z0-9]+", claim.lower()))
        overlap = len(q_tokens & c_tokens)
        if overlap >= 3:
            base += 5.0

        return min(100.0, round(base, 1))

    def _calc_citation_validity(self, ev: dict[str, Any]) -> float:
        url = ev.get("source_url", "")
        citation = ev.get("citation", "")
        if "consumeraffairs.gov.in" in url and citation:
            return 100.0
        elif citation:
            return 85.0
        return 40.0

    def _calc_conditions_coverage(self, claim: str, text: str) -> float:
        score = 80.0
        claim_lower = claim.lower()
        text_lower = text.lower()

        # Check time periods (e.g., "30 days", "fifteen days", "forty-five days")
        time_patterns = re.findall(r"\b(?:\d+|thirty|fifteen|twenty|forty-five|sixty)\s+days?\b", text_lower)
        for tp in time_patterns:
            if tp in text_lower:
                if tp in claim_lower:
                    score += 10.0
                else:
                    score -= 5.0

        # Check condition words
        for cond in ("provided that", "subject to", "unless", "except", "not exceeding"):
            if cond in text_lower:
                if cond in claim_lower:
                    score += 5.0

        return max(30.0, min(100.0, score))
