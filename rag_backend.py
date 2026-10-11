"""Retrieval backend for Consumer Protection Act RAG (stops before answer generation)."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_RERANKER_MODEL = "jinaai/jina-reranker-v1-turbo-en"
ACT_ID = "consumer_protection_act_2019"

ABSTENTION_RULES = (
    "Answer only from the supplied Consumer Protection Act evidence. "
    "If it does not support an answer, say that the retrieved Act text is insufficient. "
    "Do not invent facts or legal rules. Cite each legal claim with its provision citation and source URL."
)

KEYWORD_QUERY = """
CALL db.index.fulltext.queryNodes('act_text_lookup', $search_query) YIELD node, score
MATCH (act:Act {id: $act_id}) WHERE node.act_id = act.id
RETURN node.id AS id, labels(node)[0] AS node_type,
       node.citation AS citation,
       node.text AS text, node.chapter_title AS chapter_title,
       node.section_number AS section_number,
       node.subsection_number AS subsection_number,
       score AS retrieval_score, 'keyword' AS retrieval_source,
       act.title AS act_title, act.source_url AS source_url,
       act.source_title AS source_title, act.source_publisher AS source_publisher,
       toString(act.source_publication_date) AS source_publication_date
ORDER BY retrieval_score DESC LIMIT $limit
"""

VECTOR_QUERY = """
MATCH (node:SearchUnit)
SEARCH node IN (VECTOR INDEX act_vector_index FOR $embedding LIMIT $limit) SCORE AS score
MATCH (act:Act {id: $act_id}) WHERE node.act_id = act.id
OPTIONAL MATCH (parent:Subsection)-[:HAS_PASSAGE]->(node)
RETURN node.id AS id,
       CASE WHEN node:Passage THEN 'Passage'
            WHEN node:Subsection THEN 'Subsection' ELSE 'Section' END AS node_type,
       coalesce(node.citation, parent.citation) AS citation,
       node.text AS text, node.chapter_title AS chapter_title,
       node.section_number AS section_number,
       node.subsection_number AS subsection_number,
       node.passage_number AS passage_number, node.passage_count AS passage_count,
       score AS retrieval_score, 'vector' AS retrieval_source,
       act.title AS act_title, act.source_url AS source_url,
       act.source_title AS source_title, act.source_publisher AS source_publisher,
       toString(act.source_publication_date) AS source_publication_date
ORDER BY retrieval_score DESC
"""

EXPAND_ENTITIES_QUERY = """
MATCH (seed:SearchUnit) WHERE seed.id IN $seed_ids
OPTIONAL MATCH (parent:Subsection)-[:HAS_PASSAGE]->(seed)
WITH coalesce(parent, seed) AS origin
MATCH (origin)-[r1]-(entity:LegalEntity)-[r2]-(neighbor:Section|Subsection)
WHERE entity.act_id = $act_id AND entity.expansion_eligible = true
  AND neighbor.act_id = $act_id AND neighbor.id <> origin.id
  AND trim(coalesce(neighbor.text, '')) <> ''
MATCH (act:Act {id: $act_id})
RETURN origin.id AS seed_id, neighbor.id AS id,
       labels(neighbor)[0] AS node_type, neighbor.citation AS citation,
       neighbor.text AS text, neighbor.chapter_title AS chapter_title,
       neighbor.section_number AS section_number,
       neighbor.subsection_number AS subsection_number,
       entity.canonical_id AS bridge_entity,
       entity.name AS bridge_entity_name,
       [{type: type(r1), properties: properties(r1)},
        {type: type(r2), properties: properties(r2)}] AS expansion_relationships,
       act.title AS act_title, act.source_url AS source_url,
       act.source_title AS source_title, act.source_publisher AS source_publisher,
       toString(act.source_publication_date) AS source_publication_date
"""

EXPAND_CITES_QUERY = """
MATCH (seed:SearchUnit) WHERE seed.id IN $seed_ids
OPTIONAL MATCH (parent:Subsection)-[:HAS_PASSAGE]->(seed)
WITH coalesce(parent, seed) AS origin
MATCH (origin)-[r:CITES]-(neighbor:Section|Subsection)
WHERE neighbor.act_id = $act_id AND neighbor.id <> origin.id
  AND trim(coalesce(neighbor.text, '')) <> ''
MATCH (act:Act {id: $act_id})
RETURN origin.id AS seed_id, neighbor.id AS id,
       labels(neighbor)[0] AS node_type, neighbor.citation AS citation,
       neighbor.text AS text, neighbor.chapter_title AS chapter_title,
       neighbor.section_number AS section_number,
       neighbor.subsection_number AS subsection_number,
       null AS bridge_entity, null AS bridge_entity_name,
       [{type: type(r), properties: properties(r)}] AS expansion_relationships,
       act.title AS act_title, act.source_url AS source_url,
       act.source_title AS source_title, act.source_publisher AS source_publisher,
       toString(act.source_publication_date) AS source_publication_date
"""


def _load_embedder():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=EMBEDDING_MODEL, cache_dir=str(ROOT / ".model_cache"), threads=2)


def _graph_driver():
    from neo4j import GraphDatabase

    uri, username, password = (os.getenv("NEO4J_URI"), os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD"))
    if not all((uri, username, password)):
        raise RuntimeError("Set NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD in .env")
    return GraphDatabase.driver(uri, auth=(username, password))


def _fallback_analysis(question: str) -> dict[str, Any]:
    citations = re.findall(r"\bsections?\s+\d+[A-Z]?(?:\s*\(\s*\d+\s*\))?", question, re.I)
    words = re.findall(r"[A-Za-z][A-Za-z'-]{2,}|\d+", question)
    stop = {"what", "when", "where", "which", "who", "whom", "whose", "does", "did", "can", "could", "should", "would", "under", "about", "from", "with", "that", "this", "there", "their", "they", "have", "has", "into", "for", "the", "and", "how", "are", "was", "were"}
    keywords = list(dict.fromkeys([w for w in words if w.casefold() not in stop]))
    return {"normalized_query": " ".join(question.split()), "keywords": keywords, "citations": citations, "concepts": []}


def analyze_query(question: str) -> dict[str, Any]:
    """Apply deterministic, model-free query normalization and legal citation extraction."""
    fallback = _fallback_analysis(question)
    return {**fallback, "analysis_provider": "deterministic_rules"}


def _keyword_expression(analysis: dict[str, Any]) -> str:
    terms = list(analysis.get("keywords", [])) + list(analysis.get("citations", []))
    safe_terms: list[str] = []
    for term in terms:
        tokens = re.findall(r"[A-Za-z0-9]+", term)
        if tokens:
            safe_terms.append(" ".join(tokens))
    # Match any key term, then let the shared reranker refine relevance.
    return " OR ".join(f'"{term}"' if " " in term else term for term in dict.fromkeys(safe_terms))


def _embed_query(embedder: Any, query: str) -> list[float]:
    vector = next(embedder.embed([f"Represent this sentence for searching relevant passages: {query}"]))
    return [float(value) for value in vector]


def _hit_from_record(record: Any, source: str) -> dict[str, Any]:
    hit = record.data()
    hit["candidate_sources"] = [source]
    hit["expansion_relationships"] = []
    hit["retrieval_rank_score"] = float(hit.get("retrieval_score") or 0.0)
    return hit


def _merge_candidate(candidates: dict[str, dict[str, Any]], candidate: dict[str, Any]) -> None:
    key = candidate.get("id") or f"{candidate.get('citation')}:{candidate.get('node_type')}"
    if not key:
        return
    if key not in candidates:
        candidates[key] = candidate
        return
    existing = candidates[key]
    existing["candidate_sources"] = list(dict.fromkeys(existing.get("candidate_sources", []) + candidate.get("candidate_sources", [])))
    existing["expansion_relationships"] = existing.get("expansion_relationships", []) + [
        edge for edge in candidate.get("expansion_relationships", [])
        if edge not in existing.get("expansion_relationships", [])
    ]
    existing["retrieval_rank_score"] = max(existing.get("retrieval_rank_score", 0), candidate.get("retrieval_rank_score", 0))
    for key in ("relationship_review_status", "expansion_seed_id", "bridge_entity", "bridge_entity_name"):
        if candidate.get(key) is not None:
            existing[key] = candidate[key]


def _expand_graph(session: Any, seeds: list[dict[str, Any]], act_id: str,
                  max_candidates: int) -> list[dict[str, Any]]:
    if max_candidates < 1:
        return []
    seed_ids = list(dict.fromkeys(hit["id"] for hit in seeds if hit.get("id")))
    if not seed_ids:
        return []
    expanded: dict[str, dict[str, Any]] = {}
    for query in (EXPAND_ENTITIES_QUERY, EXPAND_CITES_QUERY):
        for record in session.run(query, seed_ids=seed_ids, act_id=act_id):
            item = record.data()
            seed = next((h for h in seeds if h.get("id") == item.get("seed_id")), None)
            item["candidate_sources"] = ["graph_expansion"]
            item["retrieval_source"] = "graph_expansion"
            item["retrieval_score"] = seed.get("retrieval_score", 0.0) if seed else 0.0
            item["retrieval_rank_score"] = item["retrieval_score"]
            item["expansion_relationships"] = item.get("expansion_relationships") or []
            item["expansion_seed_id"] = item.pop("seed_id", None)
            item["relationship_review_status"] = "unreviewed_candidate_edges"
            _merge_candidate(expanded, item)
    return sorted(
        expanded.values(), key=lambda item: item.get("retrieval_rank_score", 0), reverse=True
    )[:max_candidates]


def _load_reranker():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    model_name = os.getenv("RERANKER_MODEL", DEFAULT_RERANKER_MODEL)
    cache = ROOT / ".model_cache" / "rerankers"
    cache.mkdir(parents=True, exist_ok=True)
    return TextCrossEncoder(model_name=model_name, cache_dir=str(cache), threads=2)


def _rerank(reranker: Any, query: str, candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    if not candidates:
        return []
    documents = [f"{item.get('citation', '')} | {item.get('text', '')}" for item in candidates]
    scores = list(reranker.rerank(query, documents, batch_size=32))
    for item, score in zip(candidates, scores):
        item["reranker_score"] = float(score)
    return sorted(candidates, key=lambda item: item["reranker_score"], reverse=True)[:top_k]


class LegalRAGRetriever:
    """Callable retrieval service for keyword, vector, and graph-hybrid modes."""

    def __init__(self, *, embedder: Any = None, reranker: Any = None, analyzer=analyze_query):
        self.embedder = embedder
        self.reranker = reranker
        self.analyzer = analyzer

    def retrieve(self, question: str, mode: str, top_k: int = 5,
                 candidate_limit: int = 25) -> dict[str, Any]:
        mode = mode.casefold().strip()
        if mode not in {"keyword", "vector", "graph"}:
            raise ValueError("mode must be one of: keyword, vector, graph")
        if not question.strip():
            raise ValueError("question cannot be empty")
        if not 1 <= top_k <= 20 or not top_k <= candidate_limit <= 100:
            raise ValueError("require 1 <= top_k <= 20 and top_k <= candidate_limit <= 100")

        analysis = self.analyzer(question)
        normalized = analysis.get("normalized_query") or question
        candidates: dict[str, dict[str, Any]] = {}
        driver = _graph_driver()
        try:
            driver.verify_connectivity()
            with driver.session() as session:
                if mode == "keyword":
                    expression = _keyword_expression(analysis)
                    if expression:
                        for record in session.run(KEYWORD_QUERY, search_query=expression, limit=candidate_limit, act_id=ACT_ID):
                            _merge_candidate(candidates, _hit_from_record(record, "keyword"))
                else:
                    if self.embedder is None:
                        self.embedder = _load_embedder()
                    vector = _embed_query(self.embedder, normalized)
                    seed_limit = candidate_limit if mode == "vector" else max(1, min(candidate_limit // 2, 12))
                    seeds = [_hit_from_record(row, "vector") for row in session.run(
                        VECTOR_QUERY, embedding=vector, act_id=ACT_ID, limit=seed_limit
                    )]
                    for seed in seeds:
                        _merge_candidate(candidates, seed)
                    if mode == "graph":
                        expansion_budget = max(0, candidate_limit - len(seeds))
                        for item in _expand_graph(session, seeds, ACT_ID, expansion_budget):
                            _merge_candidate(candidates, item)
        finally:
            driver.close()

        items = list(candidates.values())
        if self.reranker is None:
            self.reranker = _load_reranker()
        ranked = _rerank(self.reranker, normalized, items, top_k)
        return {
            "question": question,
            "normalized_query": normalized,
            "analysis": analysis,
            "mode": mode,
            "candidate_count": len(items),
            "top_k": ranked,
            "answer_rules": ABSTENTION_RULES,
            "stopped_after": "reranked_top_k_before_generation",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--mode", choices=("keyword", "vector", "graph"), required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-limit", type=int, default=25)
    args = parser.parse_args()
    result = LegalRAGRetriever().retrieve(
        args.question, args.mode, top_k=args.top_k,
        candidate_limit=args.candidate_limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
