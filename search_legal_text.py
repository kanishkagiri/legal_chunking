"""Keyword-search section and subsection text in the Consumer Protection Act graph."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase


ROOT = Path(__file__).resolve().parent
INDEX_NAME = "act_text_lookup"

SEARCH_QUERY = """
CALL db.index.fulltext.queryNodes($index_name, $search_text) YIELD node, score
MATCH (act:Act {id: node.act_id})
RETURN labels(node)[0] AS node_type,
       node.citation AS citation,
       node.text AS text,
       node.chapter_title AS chapter_title,
       node.section_number AS section_number,
       node.subsection_number AS subsection_number,
       score,
       act.title AS act_title,
       act.source_url AS source_url,
       act.source_title AS source_title,
       act.source_publisher AS source_publisher,
       act.source_host AS source_host,
       act.source_publication_date AS source_publication_date
ORDER BY score DESC
LIMIT $limit
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Keyword or Lucene full-text query")
    parser.add_argument("--limit", type=int, default=5, help="Maximum matching nodes (default: 5)")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100:
        parser.error("--limit must be between 1 and 100")

    load_dotenv(ROOT / ".env")
    uri, username, password = (
        os.getenv("NEO4J_URI"), os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")
    )
    if not all((uri, username, password)):
        raise SystemExit("Set NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD in .env")

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            records = session.run(
                SEARCH_QUERY,
                index_name=INDEX_NAME,
                search_text=args.query,
                limit=args.limit,
            )
            print(json.dumps([record.data() for record in records], ensure_ascii=False, indent=2, default=str))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
