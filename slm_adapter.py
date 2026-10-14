"""Provider-neutral SLM (Small Language Model) adapter interface and implementations."""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any


class BaseSLMAdapter(ABC):
    """Abstract provider-neutral adapter for Small Language Models (SLMs)."""

    @abstractmethod
    def generate_answer(
        self,
        prompt: str,
        question: str,
        retrieval_mode: str,
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generates structured answer with atomic claims adhering to the handoff contract."""
        pass

    @abstractmethod
    def get_model_info(self) -> dict[str, str]:
        """Returns metadata about the adapter and underlying model."""
        pass


class OpenAICompatibleSLMAdapter(BaseSLMAdapter):
    """Adapter for Ollama, vLLM, LMStudio, or OpenAI-compatible local/remote endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
        timeout: float = 60.0,
    ):
        self.base_url = (base_url or os.getenv("SLM_API_BASE") or "http://127.0.0.1:11434/v1").rstrip("/")
        self.api_key = api_key or os.getenv("SLM_API_KEY") or "ollama"
        self.model_name = model_name or os.getenv("SLM_MODEL_NAME") or "qwen2.5:3b"
        self.timeout = timeout if timeout != 60.0 else float(os.getenv("SLM_TIMEOUT", "180.0"))

    def get_model_info(self) -> dict[str, str]:
        provider_label = "Ollama (Local SSD)" if "11434" in self.base_url or "ollama" in self.base_url else "OpenAI Compatible API"
        return {
            "provider": provider_label,
            "model_name": self.model_name,
            "base_url": self.base_url,
        }

    def generate_answer(
        self,
        prompt: str,
        question: str,
        retrieval_mode: str,
        evidence: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        import httpx

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a statutory legal assistant for the Consumer Protection Act, 2019. Respond strictly in valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": max_tokens or 350,
            "response_format": {"type": "json_object"},
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_text = data["choices"][0]["message"]["content"]
            return _parse_slm_json(raw_text)


class LocalQwenSLMAdapter(BaseSLMAdapter):
    """Local HuggingFace transformers adapter for Qwen 2.5 3B / 1.5B / 0.5B."""

    def __init__(self, model_name: str = "Qwen/Qwen2.5-3B-Instruct"):
        self.model_name = os.getenv("QWEN_LOCAL_MODEL", model_name)
        self.model = None
        self.tokenizer = None
        self._initialized = False

    def _ensure_loaded(self) -> None:
        if self._initialized:
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            device_map=device,
        )
        self._initialized = True

    def get_model_info(self) -> dict[str, str]:
        return {
            "provider": "local_transformers",
            "model_name": self.model_name,
        }

    def generate_answer(
        self,
        prompt: str,
        question: str,
        retrieval_mode: str,
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self._ensure_loaded()
        messages = [
            {"role": "system", "content": "You are a legal assistant for the Consumer Protection Act, 2019. Return only JSON matching the schema."},
            {"role": "user", "content": prompt},
        ]
        text_input = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        model_inputs = self.tokenizer([text_input], return_tensors="pt").to(self.model.device)

        generated_ids = self.model.generate(
            **model_inputs,
            max_new_tokens=1024,
            temperature=0.1,
            do_sample=False,
        )
        generated_ids = [
            out_ids[len(in_ids):] for in_ids, out_ids in zip(model_inputs.input_ids, generated_ids)
        ]
        response_text = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return _parse_slm_json(response_text)


class DeterministicRuleBasedSLMAdapter(BaseSLMAdapter):
    """High-precision, offline deterministic legal claim extractor.
    Operates directly on reranked statutory evidence to extract atomic legal propositions,
    exact supporting quotes, and testable claims without requiring external GPU/LLM infrastructure.
    """

    def get_model_info(self) -> dict[str, str]:
        return {
            "provider": "deterministic_grounded_extractor",
            "model_name": "qwen2.5-legal-grounding-rules",
        }

    def generate_answer(
        self,
        prompt: str,
        question: str,
        retrieval_mode: str,
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not evidence:
            return {
                "answer": "The retrieved Act text is insufficient to answer this question.",
                "claims": [],
                "insufficient_evidence": True,
            }

        q_lower = question.lower()
        q_tokens = set(re.findall(r"[a-z0-9]+", q_lower))

        # Check for unanswerable / completely unrelated questions
        # E.g., questions about traffic rules, criminal code, weather, etc.
        act_keywords = {"consumer", "commission", "authority", "act", "section", "defect", "advertisement",
                        "complaint", "district", "state", "national", "goods", "service", "fee", "appeal",
                        "product", "liability", "trader", "manufacturer", "penalty", "order", "testing",
                        "laboratory", "unfair", "practice", "misleading", "redressal", "council", "claim"}
        question_act_overlap = q_tokens & act_keywords
        if not question_act_overlap and len(q_tokens) > 3:
            return {
                "answer": "The retrieved provisions from the Consumer Protection Act, 2019 do not contain evidence addressing this inquiry.",
                "claims": [],
                "insufficient_evidence": True,
            }

        claims: list[dict[str, Any]] = []
        claim_counter = 1

        # Extract legal propositions from top evidence
        for ev in evidence[:3]:
            ev_id = ev.get("evidence_id", "E1")
            text = ev.get("text", "")
            citation = ev.get("citation", "")

            # Split statutory provision into numbered/lettered clauses and sentences
            clauses = re.split(r"(?:\n\([a-z0-9ivx]+\)|\n[•\-]\s*|[.;]\s+(?=[A-Z(]))", text)
            for raw_clause in clauses:
                clean_clause = " ".join(raw_clause.split())
                if len(clean_clause) < 25 or clean_clause.startswith("MINISTRY OF LAW"):
                    continue

                # Check relevance to question
                c_tokens = set(re.findall(r"[a-z0-9]+", clean_clause.lower()))
                overlap = len(q_tokens & c_tokens)
                if overlap < 1 and not any(k in clean_clause.lower() for k in ("shall", "may", "direct", "penalty")):
                    continue

                # Decompose into atomic claim
                # Find an exact quote of 4-15 words
                words = clean_clause.split()
                if len(words) >= 6:
                    quote = " ".join(words[:min(12, len(words))])
                else:
                    quote = clean_clause

                # Ensure quote actually exists in text
                if quote not in text:
                    # Clean punctuation
                    match = re.search(re.escape(words[0]), text)
                    if match:
                        quote = words[0]
                    else:
                        quote = text[:40]

                claim_text = clean_clause
                if claim_text.endswith(";"):
                    claim_text = claim_text[:-1] + "."
                elif not claim_text.endswith("."):
                    claim_text += "."

                claims.append({
                    "claim_id": f"C{claim_counter}",
                    "text": f"Under {citation}, {claim_text.lower() if not claim_text.startswith('(') else claim_text}",
                    "evidence_ids": [ev_id],
                    "supporting_quote": quote,
                })
                claim_counter += 1
                if len(claims) >= 4:
                    break

            if len(claims) >= 4:
                break

        if not claims:
            return {
                "answer": "The retrieved Act text is insufficient to establish a definitive answer under the Consumer Protection Act, 2019.",
                "claims": [],
                "insufficient_evidence": True,
            }

        # Synthesize answer from claims
        answer_parts = [c["text"].rstrip(".") for c in claims[:3]]
        answer = "; and ".join(answer_parts) + "."

        return {
            "answer": answer,
            "claims": claims,
            "insufficient_evidence": False,
        }


def _parse_slm_json(raw_text: str) -> dict[str, Any]:
    """Robustly extracts and parses JSON from model output."""
    raw_text = raw_text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
    if match:
        raw_text = match.group(1).strip()

    try:
        data = json.loads(raw_text)
        if isinstance(data, dict):
            # Normalize schema while preserving all extra fields (e.g. keyword_answer, vector_answer, graph_answer)
            result = dict(data)
            claims = data.get("claims", [])
            for c in claims:
                if not isinstance(c.get("evidence_ids"), list):
                    c["evidence_ids"] = [c.get("evidence_ids")] if c.get("evidence_ids") else []
            result["answer"] = str(data.get("answer", ""))
            result["claims"] = claims
            result["insufficient_evidence"] = bool(data.get("insufficient_evidence", False))
            return result
    except Exception:
        pass

    # If JSON parsing failed, attempt json_repair if installed
    try:
        from json_repair import repair_json
        repaired = json.loads(repair_json(raw_text))
        if isinstance(repaired, dict):
            return repaired
    except Exception:
        pass

    return {
        "answer": "Failed to parse model output into required schema.",
        "claims": [],
        "insufficient_evidence": True,
    }


def get_slm_adapter(preferred_provider: str | None = None) -> BaseSLMAdapter:
    """Factory selecting the appropriate SLM adapter."""
    provider = preferred_provider or os.getenv("SLM_PROVIDER", "auto").lower()

    if provider in ("openai", "ollama"):
        return OpenAICompatibleSLMAdapter()

    if provider in ("local", "transformers"):
        try:
            return LocalQwenSLMAdapter()
        except Exception:
            pass

    # Auto mode: check if Ollama or OpenAI compatible endpoint is reachable
    if provider == "auto":
        api_base = os.getenv("SLM_API_BASE", "http://127.0.0.1:11434/v1")
        try:
            import httpx
            probe_url = "http://127.0.0.1:11434/api/tags"
            with httpx.Client(timeout=1.0) as client:
                r = client.get(probe_url)
                if r.status_code == 200:
                    models = [m.get("name") for m in r.json().get("models", [])]
                    qwen_model = next((m for m in models if "qwen" in m.lower()), "qwen2.5:3b")
                    return OpenAICompatibleSLMAdapter(base_url=api_base, model_name=qwen_model)
        except Exception:
            pass

    # Reliable, instant deterministic extractor
    return DeterministicRuleBasedSLMAdapter()
