"""Comprehensive test suite for LegalGuard Pro:
Retriever, ContextBuilder, SLMAdapter, ClaimVerifier, and FastAPI endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from api_server import app
from claim_verifier import ClaimVerifier
from context_builder import ContextBuilder
from slm_adapter import DeterministicRuleBasedSLMAdapter, _parse_slm_json


client = TestClient(app)


def test_api_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "consumer_protection_act_2019" in data["act_id"]
    assert "keyword" in data["supported_modes"]
    assert "graph" in data["supported_modes"]


def test_context_builder_budgeting():
    builder = ContextBuilder(max_context_tokens=1500, reserved_response_tokens=500)
    fake_evidence = [
        {
            "id": "sec1",
            "citation": "Section 1",
            "text": "Short introductory provision text " * 5,
            "node_type": "Section",
            "retrieval_score": 10.0,
            "reranker_score": 2.0,
        },
        {
            "id": "sec2",
            "citation": "Section 2",
            "text": "Very long provision text " * 150,
            "node_type": "Section",
            "retrieval_score": 9.0,
            "reranker_score": 1.5,
        },
    ]

    bundle, prompt = builder.build_evidence_bundle(fake_evidence, "What is Section 1?", "keyword")
    assert len(bundle) == 1
    assert bundle[0]["evidence_id"] == "E1"
    assert "E1" in prompt
    assert builder.count_tokens(prompt) <= 1000


def test_slm_json_parser_robustness():
    # Test markdown fenced JSON
    markdown_json = """```json
    {
      "answer": "Test answer",
      "claims": [
        {
          "claim_id": "C1",
          "text": "Claim text",
          "evidence_ids": ["E1"],
          "supporting_quote": "Exact quote"
        }
      ],
      "insufficient_evidence": false
    }
    ```"""
    parsed = _parse_slm_json(markdown_json)
    assert parsed["answer"] == "Test answer"
    assert len(parsed["claims"]) == 1
    assert parsed["claims"][0]["claim_id"] == "C1"


def test_claim_verifier_supported_and_scoring():
    verifier = ClaimVerifier()
    evidence_bundle = [
        {
            "evidence_id": "E1",
            "citation": "Section 38(2)(a)",
            "text": "the District Commission shall refer a copy of the admitted complaint within a period of thirty days and may grant an extension not exceeding fifteen days",
            "source_url": "https://consumeraffairs.gov.in/public/upload/files/CP%20Act%202019_1732700731.pdf",
            "source_title": "The Consumer Protection Act, 2019",
            "source_publisher": "Government of India",
            "source_publication_date": "2019-08-09",
            "chapter_title": "CONSUMER DISPUTES REDRESSAL COMMISSION",
            "reranker_score": 2.5,
        }
    ]

    claims = [
        {
            "claim_id": "C1",
            "text": "The District Commission shall refer a copy of the admitted complaint within thirty days.",
            "evidence_ids": ["E1"],
            "supporting_quote": "within a period of thirty days",
        }
    ]

    verified = verifier.verify_claims(claims, evidence_bundle, "What is the procedure under Section 38?")
    assert len(verified) == 1
    c1 = verified[0]

    assert c1["verification_status"] == "SUPPORTED"
    assert c1["evidence_strength_score"] >= 80.0
    assert c1["evidence_label"] in ("Strong evidence", "Medium evidence")
    assert c1["component_scores"]["citation_validity"] == 100.0
    assert c1["component_scores"]["entailment"] >= 80.0


def test_claim_verifier_unsupported_on_missing_quote():
    verifier = ClaimVerifier()
    evidence_bundle = [
        {
            "evidence_id": "E1",
            "citation": "Section 21(1)",
            "text": "The Central Authority may issue directions to discontinue misleading advertisements.",
            "source_url": "https://consumeraffairs.gov.in/public/upload/files/CP%20Act%202019_1732700731.pdf",
        }
    ]

    claims = [
        {
            "claim_id": "C1",
            "text": "The Central Authority can shut down all retail shops permanently.",
            "evidence_ids": ["E1"],
            "supporting_quote": "shut down all retail shops permanently",  # Does NOT exist in provision
        }
    ]

    verified = verifier.verify_claims(claims, evidence_bundle, "What can CCPA do?")
    assert len(verified) == 1
    c1 = verified[0]

    assert c1["verification_status"] == "UNSUPPORTED"
    assert c1["evidence_label"] == "Unsupported"
    assert c1["evidence_strength_score"] == 0.0


def test_claim_verifier_contradicted():
    verifier = ClaimVerifier()
    evidence_bundle = [
        {
            "evidence_id": "E1",
            "citation": "Section 41",
            "text": "Any person aggrieved by an order made by the District Commission may prefer an appeal against such order to the State Commission; and no appeal shall lie unless 50 percent deposited",
            "source_url": "https://consumeraffairs.gov.in/public/upload/files/CP%20Act%202019_1732700731.pdf",
        }
    ]

    claims = [
        {
            "claim_id": "C1",
            "text": "A party may proceed without any appeal available under this law.",
            "evidence_ids": ["E1"],
            "supporting_quote": "appeal shall lie",
        }
    ]

    verified = verifier.verify_claims(claims, evidence_bundle, "Can an appeal be filed?")
    assert len(verified) == 1
    c1 = verified[0]

    assert c1["verification_status"] == "CONTRADICTED"
    assert "appeal" in c1["status_reason"].lower()


def test_abstention_on_unanswerable_query():
    adapter = DeterministicRuleBasedSLMAdapter()
    evidence = [
        {
            "evidence_id": "E1",
            "citation": "Section 2(1)",
            "text": "In this Act, advertisement means any audio or visual publicity...",
        }
    ]

    res = adapter.generate_answer(
        prompt="Test prompt",
        question="What is the speed limit on Interstate 95 in the United States?",
        retrieval_mode="keyword",
        evidence=evidence,
    )

    assert res["insufficient_evidence"] is True
    assert len(res["claims"]) == 0


def test_chat_endpoint_e2e():
    response = client.post(
        "/api/chat",
        json={
            "question": "What can the Central Authority do about a misleading advertisement?",
            "mode": "keyword",
            "top_k": 3,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "claims" in data
    assert len(data["claims"]) > 0
    assert "evidence_bundle" in data
    assert data["mode"] == "keyword"
    first_claim = data["claims"][0]
    assert first_claim["verification_status"] in ("SUPPORTED", "UNSUPPORTED")
    assert "component_scores" in first_claim
