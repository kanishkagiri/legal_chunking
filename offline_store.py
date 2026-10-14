"""Offline search and graph store for Consumer Protection Act, 2019.
Used as an in-memory fallback when Neo4j is offline or paused.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent
ACT_SECTIONS_FILE = ROOT / "parsed_output" / "act_sections.json"
ONTOLOGY_EDGES_FILE = ROOT / "parsed_output" / "legal_ontology_edges.json"
VECTORS_CACHE_FILE = ROOT / "parsed_output" / "cached_provision_vectors.npz"

OFFICIAL_SOURCE = {
    "act_title": "Consumer Protection Act, 2019",
    "source_url": "https://consumeraffairs.gov.in/public/upload/files/CP%20Act%202019_1732700731.pdf",
    "source_title": "The Consumer Protection Act, 2019 (Act No. 35 of 2019)",
    "source_publisher": "Government of India, Ministry of Consumer Affairs, Food and Public Distribution",
    "source_publication_date": "2019-08-09",
}


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z0-9]+", text) if len(t) > 1]


class OfflineLegalStore:
    """Provides keyword, vector, and graph expansion over parsed Act data without requiring live Neo4j."""

    def __init__(self, embedder: Any = None):
        self.embedder = embedder
        self.units: list[dict[str, Any]] = []
        self.unit_by_id: dict[str, dict[str, Any]] = {}
        self.entities_by_canonical: dict[str, dict[str, Any]] = {}
        self.unit_to_entities: dict[str, list[dict[str, Any]]] = {}
        self.entity_to_units: dict[str, list[str]] = {}
        self.unit_to_cites: dict[str, list[dict[str, Any]]] = {}
        self.cite_to_units: dict[str, list[str]] = {}
        self.unit_vectors: np.ndarray | None = None
        self._load_data()

    def _load_data(self) -> None:
        if not ACT_SECTIONS_FILE.exists():
            return

        with open(ACT_SECTIONS_FILE, "r", encoding="utf-8") as f:
            act_data = json.load(f)

        for sec in act_data.get("sections", []):
            sec_num = sec.get("section_number")
            chap_title = sec.get("chapter_title", "")
            has_sub = sec.get("has_subsections", False)
            sec_text = (sec.get("text") or "").strip()

            if not has_sub and sec_text:
                unit = {
                    "id": sec["id"],
                    "node_type": "Section",
                    "citation": sec.get("citation", f"Section {sec_num}"),
                    "text": sec_text,
                    "chapter_title": chap_title,
                    "section_number": sec_num,
                    "subsection_number": None,
                    **OFFICIAL_SOURCE,
                }
                self.units.append(unit)
                self.unit_by_id[unit["id"]] = unit

            for sub in sec.get("subsections", []):
                sub_text = (sub.get("text") or "").strip()
                if sub_text:
                    unit = {
                        "id": sub["id"],
                        "node_type": "Subsection",
                        "citation": sub.get("citation", f"Section {sec_num}({sub.get('subsection_number')})"),
                        "text": sub_text,
                        "chapter_title": chap_title,
                        "section_number": sec_num,
                        "subsection_number": sub.get("subsection_number"),
                        **OFFICIAL_SOURCE,
                    }
                    self.units.append(unit)
                    self.unit_by_id[unit["id"]] = unit

        # Load ontology edges
        if ONTOLOGY_EDGES_FILE.exists():
            with open(ONTOLOGY_EDGES_FILE, "r", encoding="utf-8") as f:
                ont_data = json.load(f)

            for ent in ont_data.get("entities", []):
                cid = ent.get("canonical_id")
                if cid:
                    self.entities_by_canonical[cid] = ent

            for rel in ont_data.get("ontology_relationships", []):
                src_id = rel.get("source_id")
                ent_id = rel.get("entity_id")
                if src_id and ent_id:
                    self.unit_to_entities.setdefault(src_id, []).append(rel)
                    self.entity_to_units.setdefault(ent_id, []).append(src_id)

            for cite in ont_data.get("cites_relationships", []):
                src_id = cite.get("source_id")
                tgt_id = cite.get("target_id")
                if src_id and tgt_id:
                    self.unit_to_cites.setdefault(src_id, []).append(cite)
                    self.cite_to_units.setdefault(tgt_id, []).append(src_id)

    def search_keyword(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        results = []
        for unit in self.units:
            text = f"{unit['citation']} {unit['chapter_title']} {unit['text']}"
            unit_tokens = _tokenize(text)
            unit_token_set = set(unit_tokens)

            # Match score
            score = 0.0
            citation_lower = unit["citation"].lower()
            query_lower = query.lower()

            # Exact citation boost
            if citation_lower in query_lower or query_lower in citation_lower:
                score += 15.0

            for qt in query_tokens:
                if qt in unit_token_set:
                    # Token frequency score
                    count = unit_tokens.count(qt)
                    score += 1.0 + math.log(1.0 + count)

            if score > 0:
                hit = dict(unit)
                hit["retrieval_score"] = float(score)
                hit["retrieval_rank_score"] = float(score)
                hit["retrieval_source"] = "keyword"
                hit["candidate_sources"] = ["keyword"]
                hit["expansion_relationships"] = []
                results.append(hit)

        results.sort(key=lambda x: x["retrieval_score"], reverse=True)
        return results[:limit]

    def _ensure_vectors(self) -> None:
        if self.unit_vectors is not None:
            return

        if VECTORS_CACHE_FILE.exists():
            try:
                data = np.load(VECTORS_CACHE_FILE)
                if len(data["vectors"]) == len(self.units):
                    self.unit_vectors = data["vectors"]
                    return
            except Exception:
                pass

        if self.embedder is None:
            from fastembed import TextEmbedding
            self.embedder = TextEmbedding(
                model_name="BAAI/bge-small-en-v1.5",
                cache_dir=str(ROOT / ".model_cache"),
                threads=2,
            )

        texts = [
            f"Represent this sentence for searching relevant passages: {u['citation']} | {u['text']}"
            for u in self.units
        ]
        vectors = list(self.embedder.embed(texts))
        norm_vectors = []
        for v in vectors:
            arr = np.array(v, dtype=np.float32)
            norm = np.linalg.norm(arr)
            norm_vectors.append(arr / norm if norm > 0 else arr)

        self.unit_vectors = np.stack(norm_vectors)
        try:
            np.savez_compressed(VECTORS_CACHE_FILE, vectors=self.unit_vectors)
        except Exception:
            pass

    def search_vector(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        self._ensure_vectors()
        if self.embedder is None:
            from fastembed import TextEmbedding
            self.embedder = TextEmbedding(
                model_name="BAAI/bge-small-en-v1.5",
                cache_dir=str(ROOT / ".model_cache"),
                threads=2,
            )

        q_vec = next(self.embedder.embed([f"Represent this sentence for searching relevant passages: {query}"]))
        q_arr = np.array(q_vec, dtype=np.float32)
        norm = np.linalg.norm(q_arr)
        if norm > 0:
            q_arr = q_arr / norm

        scores = np.dot(self.unit_vectors, q_arr)
        top_indices = np.argsort(scores)[::-1][:limit]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            unit = dict(self.units[idx])
            unit["retrieval_score"] = score
            unit["retrieval_rank_score"] = score
            unit["retrieval_source"] = "vector"
            unit["candidate_sources"] = ["vector"]
            unit["expansion_relationships"] = []
            results.append(unit)
        return results

    def expand_graph(self, seeds: list[dict[str, Any]], limit: int = 15) -> list[dict[str, Any]]:
        expanded: dict[str, dict[str, Any]] = {}
        seed_ids = {s["id"] for s in seeds if s.get("id")}

        for seed in seeds:
            s_id = seed.get("id")
            if not s_id:
                continue

            # 1. Expand via ontology entities
            ont_rels = self.unit_to_entities.get(s_id, [])
            for rel in ont_rels:
                ent_id = rel.get("entity_id")
                entity_info = self.entities_by_canonical.get(ent_id, {})
                if not entity_info.get("expansion_eligible", True):
                    continue

                connected_units = self.entity_to_units.get(ent_id, [])
                for neighbor_id in connected_units:
                    if neighbor_id in seed_ids or neighbor_id not in self.unit_by_id:
                        continue

                    neighbor = dict(self.unit_by_id[neighbor_id])
                    neighbor["candidate_sources"] = ["graph_expansion"]
                    neighbor["retrieval_source"] = "graph_expansion"
                    neighbor["retrieval_score"] = seed.get("retrieval_score", 0.0) * 0.85
                    neighbor["retrieval_rank_score"] = neighbor["retrieval_score"]
                    neighbor["bridge_entity"] = ent_id
                    neighbor["bridge_entity_name"] = entity_info.get("name", ent_id)
                    neighbor["expansion_relationships"] = [
                        {"type": rel.get("relationship_type"), "properties": {"evidence_key": rel.get("evidence_key")}}
                    ]
                    neighbor["expansion_seed_id"] = s_id
                    neighbor["relationship_review_status"] = "unreviewed_candidate_edges"

                    if neighbor_id not in expanded:
                        expanded[neighbor_id] = neighbor

            # 2. Expand via statutory CITES
            cite_rels = self.unit_to_cites.get(s_id, [])
            for cite in cite_rels:
                tgt_id = cite.get("target_id")
                if tgt_id and tgt_id in self.unit_by_id and tgt_id not in seed_ids:
                    target_unit = dict(self.unit_by_id[tgt_id])
                    target_unit["candidate_sources"] = ["graph_expansion"]
                    target_unit["retrieval_source"] = "graph_expansion"
                    target_unit["retrieval_score"] = seed.get("retrieval_score", 0.0) * 0.90
                    target_unit["retrieval_rank_score"] = target_unit["retrieval_score"]
                    target_unit["bridge_entity"] = None
                    target_unit["bridge_entity_name"] = None
                    target_unit["expansion_relationships"] = [
                        {"type": "CITES", "properties": {"reference_text": cite.get("reference_text")}}
                    ]
                    target_unit["expansion_seed_id"] = s_id
                    target_unit["relationship_review_status"] = "accepted"

                    if tgt_id not in expanded:
                        expanded[tgt_id] = target_unit

        res = list(expanded.values())
        res.sort(key=lambda x: x.get("retrieval_rank_score", 0), reverse=True)
        return res[:limit]
