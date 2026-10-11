"""Semantic vector search over Section, Subsection, and long-text Passage nodes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
MODEL_NAME = "BAAI/bge-small-en-v1.5"
EVALUATION_FILE = ROOT / "parsed_output" / "vector_search_evaluation.json"

VECTOR_QUERY = """
MATCH (node:SearchUnit)
SEARCH node IN (
  VECTOR INDEX act_vector_index
  FOR $embedding
  LIMIT $limit
) SCORE AS score
MATCH (act:Act {id: node.act_id})
OPTIONAL MATCH (parent:Subsection)-[:HAS_PASSAGE]->(node)
RETURN CASE
         WHEN node:Passage THEN 'Passage'
         WHEN node:Subsection THEN 'Subsection'
         ELSE 'Section'
       END AS node_type,
       coalesce(node.citation, parent.citation) AS citation,
       node.text AS text,
       node.passage_number AS passage_number,
       node.passage_count AS passage_count,
       score,
       act.title AS act_title,
       act.source_url AS source_url,
       act.source_publisher AS source_publisher,
       act.source_publication_date AS source_publication_date
ORDER BY score DESC
"""

EXAMPLES = [
    {
        "query": "Who can file a complaint when numerous consumers share the same interest?",
        "expected_citations": ["Section 2(5)"],
    },
    {
        "query": "What can the District Commission do if the opposite party does not respond to a complaint?",
        "expected_citations": ["Section 38(3)"],
    },
    {
        "query": "How does the District Commission test goods when a defect needs laboratory analysis?",
        "expected_citations": ["Section 38(2)"],
    },
    {
        "query": "What penalty applies when adulterated goods cause the death of a consumer?",
        "expected_citations": ["Section 90(1)"],
    },
    {
        "query": "Can the Central Authority order a misleading advertisement to be stopped or changed?",
        "expected_citations": ["Section 21(1)"],
    },
    {
        "query": "Can the Central Government make rules to carry out the Act?",
        "expected_citations": ["Section 101(1)"],
    },
    {
        "query": "What matters may Central Government rules cover about commission members and their appointments?",
        "expected_citations": ["Section 101(2)"],
    },
    {
        "query": "Which unfair or deceptive practices, such as false claims about goods, are prohibited?",
        "expected_citations": ["Section 2(47)"],
    },
]


def load_embedder():
    from fastembed import TextEmbedding

    return TextEmbedding(
        model_name=MODEL_NAME,
        cache_dir=str(ROOT / ".model_cache"),
        threads=2,
    )


def graph_driver():
    from neo4j import GraphDatabase

    load_dotenv(ROOT / ".env")
    uri, username, password = (
        os.getenv("NEO4J_URI"), os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")
    )
    if not all((uri, username, password)):
        raise RuntimeError("Set NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD in .env")
    return GraphDatabase.driver(uri, auth=(username, password))


def make_query_vector(embedder: Any, query: str) -> list[float]:
    raw_vector = next(embedder.embed([
        f"Represent this sentence for searching relevant passages: {query}"
    ]))
    return [float(value) for value in raw_vector]


def search_vector(session: Any, vector: list[float], limit: int) -> list[dict[str, Any]]:
    records = session.run(
        VECTOR_QUERY,
        limit=limit,
        embedding=vector,
    )
    return [record.data() for record in records]


def run_examples(limit: int) -> list[dict[str, Any]]:
    embedder = load_embedder()
    query_vectors = [make_query_vector(embedder, example["query"]) for example in EXAMPLES]
    driver = graph_driver()
    try:
        driver.verify_connectivity()
        results = []
        with driver.session() as session:
            for example, vector in zip(EXAMPLES, query_vectors):
                hits = search_vector(session, vector, limit)
                results.append({
                    **example,
                    "top_k": hits,
                    "expected_in_top_k": any(
                        hit["citation"] in example["expected_citations"] for hit in hits
                    ),
                })
        EVALUATION_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return results
    finally:
        driver.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", help="Natural-language query")
    parser.add_argument("--limit", type=int, default=5, help="Maximum matching nodes (default: 5)")
    parser.add_argument("--examples", action="store_true", help="Run the built-in retrieval examples")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100:
        parser.error("--limit must be between 1 and 100")
    if args.examples == bool(args.query):
        parser.error("provide a query or use --examples")

    if args.examples:
        results = run_examples(args.limit)
        print(json.dumps([
            {
                "query": item["query"],
                "expected_citations": item["expected_citations"],
                "expected_in_top_k": item["expected_in_top_k"],
                "hits": [
                    {key: hit[key] for key in ("citation", "node_type", "score", "passage_number", "passage_count")}
                    for hit in item["top_k"]
                ],
            }
            for item in results
        ], ensure_ascii=False, indent=2))
    else:
        embedder = load_embedder()
        vector = make_query_vector(embedder, args.query)
        driver = graph_driver()
        try:
            driver.verify_connectivity()
            with driver.session() as session:
                print(json.dumps(search_vector(session, vector, args.limit), ensure_ascii=False, indent=2, default=str))
        finally:
            driver.close()


if __name__ == "__main__":
    main()
