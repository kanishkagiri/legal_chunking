"""Create local E5 embeddings and store searchable legal nodes in Neo4j."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "parsed_output" / "act_sections.json"
MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
MAX_PASSAGE_WORDS = 220
PASSAGE_INDEX = "act_vector_index"


def word_count(text: str) -> int:
    return len(text.split())


def split_long_text(text: str, max_words: int = MAX_PASSAGE_WORDS) -> list[str]:
    """Pack nested list items/sentences into small passages without altering source nodes."""
    # Keep inner legal markers inside passages; they remain part of the same Subsection node.
    # These boundaries are only used for derived retrieval passages.
    marker = re.compile(r"(?m)(?=^[ \t]*\((?:[a-z]|[ivxlcdm]+)\)[ \t]+)")
    units = [part.strip() for part in marker.split(text) if part.strip()]
    if len(units) <= 1:
        units = [part.strip() for part in re.split(r"(?<=[.;!?])\s+", text) if part.strip()]

    # Break a single long clause into sentence/word-sized parts if needed.
    bounded: list[str] = []
    for unit in units:
        if word_count(unit) <= max_words:
            bounded.append(unit)
            continue
        sentences = [part.strip() for part in re.split(r"(?<=[.;!?])\s+", unit) if part.strip()]
        if len(sentences) <= 1:
            words = unit.split()
            bounded.extend(" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words))
        else:
            sentence_group: list[str] = []
            sentence_words = 0
            for sentence in sentences:
                count = word_count(sentence)
                if sentence_group and sentence_words + count > max_words:
                    bounded.append(" ".join(sentence_group))
                    sentence_group, sentence_words = [], 0
                if count > max_words:
                    if sentence_group:
                        bounded.append(" ".join(sentence_group))
                        sentence_group, sentence_words = [], 0
                    words = sentence.split()
                    bounded.extend(" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words))
                else:
                    sentence_group.append(sentence)
                    sentence_words += count
            if sentence_group:
                bounded.append(" ".join(sentence_group))

    # Greedily recombine small logical units while staying under the word budget.
    passages: list[str] = []
    current: list[str] = []
    current_words = 0
    for unit in bounded:
        count = word_count(unit)
        if current and current_words + count > max_words:
            passages.append("\n".join(current))
            current, current_words = [], 0
        current.append(unit)
        current_words += count
    if current:
        passages.append("\n".join(current))
    return passages


def load_embedder():
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise RuntimeError("Install dependencies with: python -m pip install -r requirements-embeddings.txt") from exc
    cache_dir = ROOT / ".model_cache"
    cache_dir.mkdir(exist_ok=True)
    return TextEmbedding(model_name=MODEL_NAME, cache_dir=str(cache_dir), threads=2)


def load_tokenizer():
    from tokenizers import Tokenizer

    cache_root = ROOT / ".model_cache" / "models--Qdrant--bge-small-en-v1.5-onnx-Q" / "snapshots"
    tokenizers = list(cache_root.glob("*/tokenizer.json"))
    if not tokenizers:
        raise RuntimeError("Could not find the downloaded BGE tokenizer to verify input lengths")
    return Tokenizer.from_file(str(tokenizers[0]))


def with_context(citation: str, chapter_title: str, text: str) -> str:
    return f"Consumer Protection Act, 2019 | {chapter_title} | {citation}\n{text}"


def make_embedding_inputs(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    section_rows: list[dict[str, Any]] = []
    subsection_rows: list[dict[str, Any]] = []
    passage_rows: list[dict[str, Any]] = []
    for section in data["sections"]:
        text = section["text"].strip()
        if text:
            section_rows.append({
                "id": section["id"],
                "act_id": section["act_id"],
                "section_number": section["section_number"],
                "citation": section["citation"],
                "text": text,
                "embedding_text": with_context(section["citation"], section["chapter_title"], text),
                "embedding_word_count": word_count(text),
            })
        for subsection in section["subsections"]:
            subtext = subsection["text"].strip()
            common = {
                "id": subsection["id"],
                "act_id": subsection["act_id"],
                "chapter_number": subsection["chapter_number"],
                "chapter_roman": subsection["chapter_roman"],
                "chapter_title": subsection["chapter_title"],
                "section_number": subsection["section_number"],
                "subsection_number": subsection["subsection_number"],
                "subsection_marker": subsection["subsection_marker"],
                "citation": subsection["citation"],
                "source_file": subsection["source_file"],
                "text": subtext,
                "embedding_word_count": word_count(subtext),
            }
            if word_count(subtext) <= MAX_PASSAGE_WORDS:
                subsection_rows.append({
                    **common,
                    "embedding_text": with_context(subsection["citation"], subsection["chapter_title"], subtext),
                    "embedding_strategy": "whole_subsection",
                    "passages": [],
                })
            else:
                passage_texts = split_long_text(subtext)
                passage_ids = [f"{subsection['id']}:passage:{i + 1}" for i in range(len(passage_texts))]
                subsection_rows.append({
                    **common,
                    "embedding_text": None,
                    "embedding_strategy": "linked_passages",
                    "passages": passage_ids,
                })
                for i, passage_text in enumerate(passage_texts):
                    passage_rows.append({
                        "id": passage_ids[i],
                        "act_id": subsection["act_id"],
                        "parent_subsection_id": subsection["id"],
                        "chapter_number": subsection["chapter_number"],
                        "chapter_roman": subsection["chapter_roman"],
                        "chapter_title": subsection["chapter_title"],
                        "section_number": subsection["section_number"],
                        "subsection_number": subsection["subsection_number"],
                        "citation": subsection["citation"],
                        "passage_number": i + 1,
                        "passage_count": len(passage_texts),
                        "previous_passage_id": passage_ids[i - 1] if i else None,
                        "source_file": subsection["source_file"],
                        "text": passage_text,
                        "embedding_text": with_context(subsection["citation"], subsection["chapter_title"], passage_text),
                        "embedding_word_count": word_count(passage_text),
                        "embedding_strategy": "linked_passage",
                    })
    return section_rows, subsection_rows, passage_rows


def embed_rows(embedder: Any, tokenizer: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    for row in rows:
        token_count = len(tokenizer.encode(row["embedding_text"]).ids)
        if token_count > 512:
            raise ValueError(
                f"Embedding input for {row['id']} is {token_count} tokens; "
                "split the text further before importing."
            )
        row["embedding_token_count"] = token_count
    vectors = embedder.embed([row["embedding_text"] for row in rows], batch_size=32)
    for row, vector in zip(rows, vectors):
        row["embedding"] = [float(value) for value in vector]
        if len(row["embedding"]) != DIMENSIONS:
            raise ValueError(f"Expected {DIMENSIONS} dimensions for {row['id']}, got {len(row['embedding'])}")
        row["embedding_dimensions"] = DIMENSIONS
        row["embedding_model"] = MODEL_NAME
    return rows


def update_graph(section_rows: list[dict[str, Any]], subsection_rows: list[dict[str, Any]], passage_rows: list[dict[str, Any]]) -> None:
    from neo4j import GraphDatabase

    load_dotenv(ROOT / ".env")
    uri, username, password = (
        os.getenv("NEO4J_URI"), os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")
    )
    if not all((uri, username, password)):
        raise RuntimeError("Set NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD in .env")

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            session.execute_write(_save_embeddings, section_rows, subsection_rows, passage_rows)
            session.run(
                "CREATE VECTOR INDEX act_vector_index IF NOT EXISTS "
                "FOR (n:SearchUnit) ON (n.embedding) "
                "OPTIONS {indexConfig: {`vector.dimensions`: 384, "
                "`vector.similarity_function`: 'cosine'}}",
            ).consume()
            session.run("CALL db.awaitIndex($index_name, 60)", index_name=PASSAGE_INDEX).consume()
        # Index population can leave a connection idle long enough for Aura to close it.
        with driver.session() as session:
            state = session.run(
                "SHOW VECTOR INDEXES YIELD name, state, populationPercent "
                "WHERE name = $index_name RETURN name, state, populationPercent",
                index_name=PASSAGE_INDEX,
            ).single()
            if not state or state["state"] != "ONLINE":
                raise RuntimeError(f"Vector index is not online: {state}")
            result = session.run(
                "MATCH (n:SearchUnit) "
                "RETURN count(n) AS embedded_nodes, "
                "count(CASE WHEN n:Passage THEN 1 END) AS passage_nodes, "
                "count(CASE WHEN n:Section THEN 1 END) AS sections, "
                "count(CASE WHEN n:Subsection THEN 1 END) AS subsections"
            ).single()
            print(
                f"Stored {result['embedded_nodes']} searchable embeddings "
                f"({result['sections']} sections, {result['subsections']} subsections, "
                f"{result['passage_nodes']} passages); vector index {state['state']} "
                f"at {state['populationPercent']}%."
            )
    finally:
        driver.close()


def _save_embeddings(tx: Any, section_rows: list[dict[str, Any]], subsection_rows: list[dict[str, Any]], passage_rows: list[dict[str, Any]]) -> None:
    # Set whole-node vectors or mark empty section text as unsearchable.
    tx.run(
        "MATCH (s:Section) WHERE s.act_id = $act_id "
        "WITH s, $rows AS rows "
        "UNWIND rows AS row WITH s, row WHERE s.id = row.id "
        "SET s.embedding = row.embedding, s.embedding_model = $model, "
        "s.embedding_dimensions = $dimensions, "
        "s.embedding_status = CASE WHEN row.embedding IS NULL THEN 'no_section_only_text' ELSE 'embedded' END, "
        "s.embedding_word_count = row.embedding_word_count, "
        "s.embedding_token_count = row.embedding_token_count "
        "FOREACH (_ IN CASE WHEN row.embedding IS NULL THEN [] ELSE [1] END | SET s:SearchUnit) "
        "FOREACH (_ IN CASE WHEN row.embedding IS NULL THEN [1] ELSE [] END | REMOVE s:SearchUnit)",
        act_id="consumer_protection_act_2019", rows=section_rows,
        model=MODEL_NAME, dimensions=DIMENSIONS,
    ).consume()
    tx.run(
        "UNWIND $rows AS row MATCH (s:Subsection {id: row.id}) "
        "OPTIONAL MATCH (s)-[r:HAS_PASSAGE]->(old:Passage) "
        "WITH s, row, collect(r) AS old_rels, collect(old) AS old_nodes "
        "FOREACH (r IN old_rels | DELETE r) "
        "FOREACH (p IN old_nodes | DETACH DELETE p) "
        "SET s.embedding = row.embedding, s.embedding_model = $model, "
        "s.embedding_dimensions = $dimensions, s.embedding_status = row.embedding_strategy, "
        "s.embedding_word_count = row.embedding_word_count, "
        "s.embedding_token_count = row.embedding_token_count "
        "FOREACH (_ IN CASE WHEN row.embedding IS NULL THEN [] ELSE [1] END | SET s:SearchUnit) "
        "FOREACH (_ IN CASE WHEN row.embedding IS NULL THEN [1] ELSE [] END | REMOVE s:SearchUnit)",
        rows=subsection_rows, model=MODEL_NAME, dimensions=DIMENSIONS,
    ).consume()

    if passage_rows:
        tx.run(
            "UNWIND $rows AS row MATCH (s:Subsection {id: row.parent_subsection_id}) "
            "MERGE (p:Passage {id: row.id}) SET p += row SET p:SearchUnit "
            "MERGE (s)-[:HAS_PASSAGE]->(p)",
            rows=passage_rows,
        ).consume()
        tx.run(
            "UNWIND $rows AS row WITH row WHERE row.previous_passage_id IS NOT NULL "
            "MATCH (prev:Passage {id: row.previous_passage_id}) "
            "MATCH (current:Passage {id: row.id}) "
            "MERGE (prev)-[:NEXT_PASSAGE]->(current)",
            rows=passage_rows,
        ).consume()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import", dest="do_import", action="store_true", help="Store vectors and vector index in Neo4j")
    args = parser.parse_args()
    if not DATA_FILE.exists():
        raise SystemExit(f"Missing parsed input: {DATA_FILE}. Run neo4j_pipeline.py first.")
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    section_rows, subsection_rows, passage_rows = make_embedding_inputs(data)
    largest_whole_node_words = max(
        [row["embedding_word_count"] for row in section_rows]
        + [row["embedding_word_count"] for row in subsection_rows if row["embedding_text"]]
        + [0]
    )
    largest_passage_words = max([row["embedding_word_count"] for row in passage_rows] + [0])
    report = {
        "model": MODEL_NAME,
        "dimensions": DIMENSIONS,
        "input_limit_tokens": 512,
        "safe_passage_limit_words": MAX_PASSAGE_WORDS,
        "section_embeddings": len(section_rows),
        "whole_subsection_embeddings": sum(row["embedding_strategy"] == "whole_subsection" for row in subsection_rows),
        "long_subsections_as_passages": sum(row["embedding_strategy"] == "linked_passages" for row in subsection_rows),
        "passage_count": len(passage_rows),
        "largest_whole_node_words": largest_whole_node_words,
        "largest_passage_words": largest_passage_words,
    }
    embedder = load_embedder()
    tokenizer = load_tokenizer()
    section_rows = embed_rows(embedder, tokenizer, section_rows)
    short_subsection_rows = embed_rows(
        embedder, tokenizer, [row for row in subsection_rows if row["embedding_text"]]
    )
    embedded_subsections_by_id = {row["id"]: row for row in short_subsection_rows}
    all_subsection_rows = []
    for row in subsection_rows:
        embedded_row = embedded_subsections_by_id.get(row["id"])
        if embedded_row:
            all_subsection_rows.append(embedded_row)
        else:
            all_subsection_rows.append({
                **row,
                "embedding": None,
                "embedding_model": MODEL_NAME,
                "embedding_dimensions": DIMENSIONS,
            })
    passage_rows = embed_rows(embedder, tokenizer, passage_rows)
    report["largest_embedding_tokens"] = max(
        [row["embedding_token_count"] for row in section_rows + short_subsection_rows + passage_rows]
        + [0]
    )
    report["inputs_over_model_limit"] = 0
    print(json.dumps(report, indent=2))
    # Restore empty-vector rows for every Section so the import removes stale vectors if needed.
    embedded_by_id = {row["id"]: row for row in section_rows}
    all_sections = []
    for section in data["sections"]:
        row = embedded_by_id.get(section["id"])
        if row:
            all_sections.append(row)
        else:
            all_sections.append({"id": section["id"], "embedding": None, "embedding_word_count": 0})
    if args.do_import:
        update_graph(all_sections, all_subsection_rows, passage_rows)
    else:
        print("Dry run only. Re-run with --import to store embeddings in Neo4j.")


if __name__ == "__main__":
    main()
