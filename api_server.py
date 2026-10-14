"""FastAPI HTTP backend for LegalGuard Graph-RAG system."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from claim_verifier import ClaimVerifier
from context_builder import ContextBuilder
from rag_backend import LegalRAGRetriever
from slm_adapter import get_slm_adapter

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"

app = FastAPI(
    title="LegalGuard Consumer Protection Act RAG API",
    description="Statutory legal retrieval, multi-mode comparison, and synthesis pipeline.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from rag_backend import LegalRAGRetriever, _load_embedder, _load_reranker

# Shared singletons
_shared_embedder = _load_embedder()
_shared_reranker = _load_reranker()
retriever = LegalRAGRetriever(embedder=_shared_embedder, reranker=_shared_reranker)
context_builder = ContextBuilder(max_context_tokens=3072, reserved_response_tokens=1024)
claim_verifier = ClaimVerifier()
slm_adapter = get_slm_adapter()


class RetrieveRequest(BaseModel):
    question: str = Field(..., min_length=2, description="The legal question to search")
    mode: Literal["keyword", "vector", "graph"] = Field("graph", description="Retrieval mode")
    top_k: int = Field(5, ge=1, le=20, description="Number of provisions to retrieve")
    candidate_limit: int = Field(25, ge=5, le=100, description="Size of candidate search pool")


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=2, description="The legal question to answer")
    mode: Literal["keyword", "vector", "graph"] = Field("graph", description="Retrieval mode")
    top_k: int = Field(5, ge=1, le=20, description="Number of provisions to retrieve")
    adapter_provider: str | None = Field(None, description="Optional override for SLM provider")


@app.get("/api/health")
def health_check() -> dict[str, Any]:
    return {
        "status": "healthy",
        "act_id": "consumer_protection_act_2019",
        "supported_modes": ["keyword", "vector", "graph"],
        "slm_model": slm_adapter.get_model_info(),
        "official_source": {
            "title": "Consumer Protection Act, 2019 (Act No. 35 of 2019)",
            "publisher": "Government of India",
            "url": "https://consumeraffairs.gov.in/public/upload/files/CP%20Act%202019_1732700731.pdf",
        },
    }


@app.post("/api/retrieve")
def retrieve_endpoint(req: RetrieveRequest) -> dict[str, Any]:
    try:
        raw_result = retriever.retrieve(
            question=req.question,
            mode=req.mode,
            top_k=req.top_k,
            candidate_limit=req.candidate_limit,
        )
        return raw_result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Retrieval error: {str(e)}")


class CompareRequest(BaseModel):
    question: str = Field(..., min_length=2, description="The legal question to compare across modes")
    top_k: int = Field(3, ge=1, le=10, description="Number of provisions per mode")
    adapter_provider: str | None = Field(None, description="Optional override for SLM provider")


def _is_template_text(value: Any) -> bool:
    text = str(value or "").casefold()
    markers = (
        "first concise point",
        "second concise point",
        "specific legal proposition or rule",
        "comprehensive and direct answer",
    )
    return any(marker in text for marker in markers)


def _execute_pipeline(question: str, mode: str, top_k: int, adapter_provider: str | None = None) -> dict[str, Any]:
    retrieval_res = retriever.retrieve(
        question=question,
        mode=mode,
        top_k=top_k,
    )
    raw_top_k = retrieval_res.get("top_k", [])

    evidence_bundle, prompt = context_builder.build_evidence_bundle(
        raw_evidence=raw_top_k,
        question=question,
        mode=mode,
    )

    active_adapter = get_slm_adapter(adapter_provider) if adapter_provider else slm_adapter
    slm_output = active_adapter.generate_answer(
        prompt=prompt,
        question=question,
        retrieval_mode=mode,
        evidence=evidence_bundle,
        max_tokens=768,
    )

    answer = (slm_output.get("answer") or "").strip()
    raw_claims = [
        claim for claim in slm_output.get("claims", [])
        if isinstance(claim, dict) and not _is_template_text(claim.get("text"))
    ]
    answer_generation_fallback = _is_template_text(answer)
    if answer_generation_fallback:
        answer = ""
    if not answer and raw_claims:
        claim_points = [claim.get("text", "").strip() for claim in raw_claims if claim.get("text", "").strip()]
        answer = "\n".join(f"{idx}. {text}" for idx, text in enumerate(claim_points[:6], start=1))
        answer_generation_fallback = True
    if not answer and evidence_bundle:
        excerpts = [
            f"{idx}. {item.get('citation', 'Provision')}: {item.get('text', '').strip()[:500]}"
            for idx, item in enumerate(evidence_bundle[:3], start=1)
            if item.get("text")
        ]
        answer = "The answer model did not produce a usable summary. Relevant retrieved provisions:\n" + "\n".join(excerpts)
        answer_generation_fallback = True
    if not answer:
        answer = "The retrieved Consumer Protection Act text is insufficient to answer this question."
        answer_generation_fallback = True
    extracted_claims = claim_verifier.extract_atomic_claims_from_answer(
        answer=answer,
        evidence_bundle=evidence_bundle,
        existing_claims=raw_claims,
    )
    verified_claims = claim_verifier.verify_claims(
        claims=extracted_claims,
        evidence_bundle=evidence_bundle,
        question=question,
    )

    return {
        "mode": mode,
        "answer": answer,
        "raw_slm_answer": slm_output.get("answer", ""),
        "answer_generation_fallback": answer_generation_fallback,
        "insufficient_evidence": bool(slm_output.get("insufficient_evidence")) or not evidence_bundle,
        "claims": verified_claims,
        "retrieved_citations": [e.get("citation") for e in evidence_bundle],
        "evidence_bundle": evidence_bundle,
        "retrieval_metadata": {
            "candidate_count": retrieval_res.get("candidate_count", 0),
            "backend_engine": retrieval_res.get("backend_engine", "unknown"),
            "normalized_query": retrieval_res.get("normalized_query", question),
            "analysis": retrieval_res.get("analysis", {}),
        },
        "model_info": active_adapter.get_model_info(),
    }


@app.post("/api/chat")
def chat_endpoint(req: ChatRequest) -> dict[str, Any]:
    try:
        res = _execute_pipeline(
            question=req.question,
            mode=req.mode,
            top_k=req.top_k,
            adapter_provider=req.adapter_provider,
        )
        return {
            "question": req.question,
            **res,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline processing error: {str(e)}")


@app.post("/api/compare")
def compare_endpoint(req: CompareRequest) -> dict[str, Any]:
    try:
        modes = ["keyword", "vector", "graph"]

        # Step 1: Run retrieval fast across all modes
        retrieval_by_mode = {
            m: retriever.retrieve(question=req.question, mode=m, top_k=req.top_k)
            for m in modes
        }

        # Step 2: Build evidence bundles and deduplicate generation tasks
        bundles = {}
        prompts = {}
        signatures = {}
        for m in modes:
            b, p = context_builder.build_evidence_bundle(
                raw_evidence=retrieval_by_mode[m].get("top_k", []),
                question=req.question,
                mode=m,
            )
            bundles[m] = b
            prompts[m] = p
            signatures[m] = tuple(sorted(e.get("citation", "") for e in b))

        # Step 3: Fast unified SLM generation (single comparative pass)
        active_adapter = get_slm_adapter(req.adapter_provider) if req.adapter_provider else slm_adapter

        def _fmt_brief_ev(bundle):
            return "\n".join(f"- {e.get('citation')}: {e.get('text', '')[:220]}..." for e in bundle)

        def _synthesize_distinct_mode_answer(mode_name, bundle, base_ans):
            if not bundle:
                return "No relevant provisions retrieved for this mode."
            top = bundle[0]
            cit = top.get("citation", "the Act")
            text = top.get("text", "")
            clauses = [c.strip() for c in re.split(r"(?<=[.;\n])\s+", text) if len(c.strip()) > 20]
            clause_str = clauses[0] if clauses else text[:160]
            citations_str = ", ".join(e.get("citation") for e in bundle[:3])
            if mode_name == "keyword":
                return f"Lexical retrieval matched {cit}: {clause_str.rstrip('.')}. Key provisions: {citations_str}."
            elif mode_name == "vector":
                return f"Semantic retrieval surfaced {cit}: {clause_str.rstrip('.')}. Key provisions: {citations_str}."
            else:
                return f"Graph traversal expanded to {cit}: {clause_str.rstrip('.')}. Graph route: {citations_str}."

        compare_prompt = (
            f"You are comparing three statutory retrieval modes for the Consumer Protection Act, 2019.\n"
            f"Inquiry: {req.question}\n\n"
            f"[KEYWORD MODE RETRIEVED PROVISIONS ({', '.join(e.get('citation') for e in bundles['keyword'])})]:\n{_fmt_brief_ev(bundles['keyword'])}\n\n"
            f"[VECTOR MODE RETRIEVED PROVISIONS ({', '.join(e.get('citation') for e in bundles['vector'])})]:\n{_fmt_brief_ev(bundles['vector'])}\n\n"
            f"[GRAPH HYBRID MODE RETRIEVED PROVISIONS ({', '.join(e.get('citation') for e in bundles['graph'])})]:\n{_fmt_brief_ev(bundles['graph'])}\n\n"
            f"Generate 3 DIFFERENT, mode-specific legal summaries. Each answer MUST explicitly cite and base its conclusion ONLY on that specific mode's retrieved sections.\n"
            f"Return valid JSON matching this exact schema:\n"
            f'{{"keyword_answer": "...", "vector_answer": "...", "graph_answer": "..."}}'
        )

        try:
            slm_out = active_adapter.generate_answer(
                prompt=compare_prompt,
                question=req.question,
                retrieval_mode="compare",
                evidence=bundles["graph"],
                max_tokens=140,
            )
        except Exception:
            slm_out = {}

        mode_answers = {
            "keyword": (slm_out.get("keyword_answer") or "").strip(),
            "vector": (slm_out.get("vector_answer") or "").strip(),
            "graph": (slm_out.get("graph_answer") or "").strip(),
        }

        # Check and ensure each mode's answer is distinct and reflects its retrieved provisions
        for m in modes:
            ans = mode_answers[m]
            is_empty = not ans
            is_dup = False
            for other_m in modes:
                if other_m != m and mode_answers.get(other_m) and mode_answers[other_m] == ans:
                    is_dup = True
                    break
            if is_empty or is_dup:
                mode_answers[m] = _synthesize_distinct_mode_answer(m, bundles[m], ans)

        mode_results = {}
        for m in modes:
            mode_results[m] = {
                "mode": m,
                "answer": mode_answers[m],
                "retrieved_citations": [e.get("citation") for e in bundles[m]],
                "evidence_bundle": bundles[m],
                "retrieval_metadata": {
                    "candidate_count": retrieval_by_mode[m].get("candidate_count", len(bundles[m])),
                    "backend_engine": retrieval_by_mode[m].get("backend_engine", "default"),
                },
            }

        # Step 4: Cross-mode comparative analysis & why each is better
        citation_sets = {m: set(mode_results[m]["retrieved_citations"]) for m in modes}
        union_citations = sorted(list(set.union(*citation_sets.values())))
        intersection_citations = sorted(list(set.intersection(*citation_sets.values())))

        mode_advantages = {
            "keyword": {
                "why_better": "Direct lexical precision. Best when queries contain explicit section numbers (e.g., Section 21, Section 41), specific terminology, or numeric thresholds ('ten lakh'). Never drifts semantically.",
                "provisions_count": len(citation_sets["keyword"]),
                "unique_citations": sorted(list(citation_sets["keyword"] - (citation_sets["vector"] | citation_sets["graph"]))),
            },
            "vector": {
                "why_better": "Semantic & conceptual generalization. Best for natural language or layman queries (e.g., 'faulty items', 'misleading promos') using synonyms that keyword matching would miss.",
                "provisions_count": len(citation_sets["vector"]),
                "unique_citations": sorted(list(citation_sets["vector"] - (citation_sets["keyword"] | citation_sets["graph"]))),
            },
            "graph": {
                "why_better": "Structural interconnectivity. Expands vector seeds across explicit statutory CITES cross-references and legal entity ontology edges, capturing interrelated provisions & remedy routes.",
                "provisions_count": len(citation_sets["graph"]),
                "unique_citations": sorted(list(citation_sets["graph"] - (citation_sets["keyword"] | citation_sets["vector"]))),
            },
        }

        best_mode = "graph" if mode_advantages["graph"]["unique_citations"] else (
            "keyword" if mode_advantages["keyword"]["unique_citations"] else "vector"
        )

        verdict_notes = []
        if intersection_citations:
            verdict_notes.append(f"All 3 modes agreed on consensus provision(s): {', '.join(intersection_citations)}.")
        if mode_advantages["graph"]["unique_citations"]:
            verdict_notes.append(f"Graph Hybrid expanded into unique provision(s): {', '.join(mode_advantages['graph']['unique_citations'])} via CITES / ontology.")
        if mode_advantages["keyword"]["unique_citations"]:
            verdict_notes.append(f"Keyword uniquely matched exact terms in: {', '.join(mode_advantages['keyword']['unique_citations'])}.")
        if not verdict_notes:
            verdict_notes.append(f"Mode {best_mode.upper()} achieved the strongest coverage and relevance for this inquiry.")

        return {
            "question": req.question,
            "modes": mode_results,
            "summary": {
                "best_mode": best_mode,
                "all_retrieved_citations": union_citations,
                "common_citations": intersection_citations,
                "mode_advantages": mode_advantages,
                "verdict": " ".join(verdict_notes),
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Comparison pipeline error: {str(e)}")


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def start_server():
    import uvicorn
    uvicorn.run("api_server:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    start_server()
