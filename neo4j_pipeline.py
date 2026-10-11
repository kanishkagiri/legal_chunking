"""Parse Consumer Protection Act chapter text into Neo4j Section/Subsection nodes."""

from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase


ROOT = Path(__file__).resolve().parent
ACT_ID = "consumer_protection_act_2019"
ACT_TITLE = "Consumer Protection Act, 2019"
ACT_NUMBER = "35 of 2019"
SOURCE_URL = "https://consumeraffairs.gov.in/public/upload/files/CP%20Act%202019_1732700731.pdf"
SOURCE_TITLE = "The Consumer Protection Act, 2019 (No. 35 of 2019)"
SOURCE_PUBLISHER = "Ministry of Law and Justice, Legislative Department, Government of India"
SOURCE_HOST = "Department of Consumer Affairs, Government of India"
SOURCE_PUBLICATION_DATE = "2019-08-09"
FULLTEXT_INDEX = "act_text_lookup"
SECTION_START = re.compile(r"(?m)^(\d{1,3})\.\s+")
# Match only a marker at the start of a provision line (after the section prefix
# has been removed). This intentionally leaves (a), (i), etc. in their parent text.
SUBSECTION_START = re.compile(
    r"(?m)(?:^|\n)[ \t]*\((\d+)\)(?=[ \t]+(?:[A-Z]|[\"“]))"
)
CHAPTER_HEADER = re.compile(r"(?m)^CHAPTER\s+([IVX]+)\s*\n([^\n]+)")
ROMAN_VALUES = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}


def clean_text(value: str) -> str:
    """Remove unreadable replacement/control characters without dropping legal text."""
    value = unicodedata.normalize("NFC", value)
    value = value.replace("\ufffd", "")
    return "".join(
        char for char in value
        if char in "\n\r\t" or unicodedata.category(char) not in {"Cc", "Cs"}
    )


def chapter_files() -> list[Path]:
    files = sorted(
        ROOT.glob("chunk_chapter_*.txt"),
        key=lambda p: int(re.search(r"(\d+)$", p.stem).group(1)),
    )
    expected = list(range(1, 9))
    actual = [int(re.search(r"(\d+)$", p.stem).group(1)) for p in files]
    if actual != expected:
        raise ValueError(f"Expected chapter files 1–8; found {actual}")
    return files


def parse_chapter(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = path.read_text(encoding="utf-8")
    header = CHAPTER_HEADER.search(raw)
    if not header:
        raise ValueError(f"No chapter heading found in {path.name}")
    roman, chapter_title = header.group(1), clean_text(header.group(2).strip())
    if roman not in ROMAN_VALUES:
        raise ValueError(f"Unsupported chapter numeral {roman} in {path.name}")
    chapter_number = ROMAN_VALUES[roman]
    chapter = {
        "id": f"{ACT_ID}:chapter:{chapter_number}",
        "act_id": ACT_ID,
        "chapter_number": chapter_number,
        "chapter_roman": roman,
        "chapter_title": chapter_title,
        "source_file": path.name,
    }

    starts = list(SECTION_START.finditer(raw))
    if not starts:
        raise ValueError(f"No numbered sections found in {path.name}")
    sections: list[dict[str, Any]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(raw)
        section_number = int(start.group(1))
        # Exclude the section's `N. ` label from its text property.
        body = raw[start.end():end].strip()
        markers = list(SUBSECTION_START.finditer(body))
        section_text: str
        subsections: list[dict[str, Any]] = []
        if markers:
            section_text = clean_text(body[:markers[0].start()].strip())
            for sub_index, marker in enumerate(markers):
                sub_end = markers[sub_index + 1].start() if sub_index + 1 < len(markers) else len(body)
                subsection_number = int(marker.group(1))
                # Retain the marker and all nested (a), (i), etc. text verbatim
                # except for unreadable replacement/control characters.
                raw_subtext = body[marker.start():sub_end].strip()
                subtext = clean_text(raw_subtext)
                subsections.append({
                    "id": f"{ACT_ID}:section:{section_number}:subsection:{subsection_number}",
                    "act_id": ACT_ID,
                    "chapter_number": chapter_number,
                    "chapter_roman": roman,
                    "chapter_title": chapter_title,
                    "section_number": section_number,
                    "subsection_number": subsection_number,
                    "subsection_marker": f"({subsection_number})",
                    "citation": f"Section {section_number}({subsection_number})",
                    "ordinal": sub_index + 1,
                    "text": subtext,
                    "source_file": path.name,
                })
        else:
            section_text = clean_text(body)

        sections.append({
            "id": f"{ACT_ID}:section:{section_number}",
            "act_id": ACT_ID,
            "act_title": ACT_TITLE,
            "act_number": ACT_NUMBER,
            "chapter_id": chapter["id"],
            "chapter_number": chapter_number,
            "chapter_roman": roman,
            "chapter_title": chapter_title,
            "section_number": section_number,
            "citation": f"Section {section_number}",
            "has_subsections": bool(subsections),
            "subsection_count": len(subsections),
            "text": section_text,
            "source_file": path.name,
            "source_order": index + 1,
            "subsections": subsections,
        })
    return chapter, sections


def parse_all() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chapters: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    for path in chapter_files():
        chapter, chapter_sections = parse_chapter(path)
        chapters.append(chapter)
        sections.extend(chapter_sections)
    return chapters, sections


def validate(chapters: list[dict[str, Any]], sections: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    numbers = [section["section_number"] for section in sections]
    if len(sections) != 107:
        errors.append(f"Expected 107 sections, found {len(sections)}")
    if numbers != list(range(1, 108)):
        errors.append(f"Section sequence is not exactly 1–107: {numbers}")
    if len(chapters) != 8:
        errors.append(f"Expected 8 chapters, found {len(chapters)}")

    subsection_total = 0
    sections_with_subsections = 0
    empty_text: list[str] = []
    for section in sections:
        subs = section["subsections"]
        subsection_total += len(subs)
        sections_with_subsections += bool(subs)
        if not section["text"] and not subs:
            empty_text.append(section["citation"])
        markers = [sub["subsection_number"] for sub in subs]
        if len(markers) != len(set(markers)):
            errors.append(f"Duplicate numbered subsection in {section['citation']}: {markers}")
        for sub in subs:
            if not sub["text"] or not sub["text"].startswith(sub["subsection_marker"]):
                errors.append(f"Missing text/marker in {sub['citation']}")
    if empty_text:
        errors.append(f"Empty text for sections without subsections: {empty_text}")

    return {
        "valid": not errors,
        "errors": errors,
        "chapter_count": len(chapters),
        "section_count": len(sections),
        "sections_with_subsections": sections_with_subsections,
        "subsection_count": subsection_total,
        "section_numbers": numbers,
    }


def write_parse_artifacts(chapters: list[dict[str, Any]], sections: list[dict[str, Any]], report: dict[str, Any]) -> None:
    output_dir = ROOT / "parsed_output"
    output_dir.mkdir(exist_ok=True)
    (output_dir / "act_sections.json").write_text(
        json.dumps({"act_id": ACT_ID, "chapters": chapters, "sections": sections}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "validation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def import_into_neo4j(chapters: list[dict[str, Any]], sections: list[dict[str, Any]]) -> None:
    load_dotenv(ROOT / ".env")
    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    if not all((uri, username, password)):
        raise RuntimeError("Set NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD in .env")

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            session.run("CREATE CONSTRAINT act_id IF NOT EXISTS FOR (n:Act) REQUIRE n.id IS UNIQUE")
            session.run("CREATE CONSTRAINT chapter_id IF NOT EXISTS FOR (n:Chapter) REQUIRE n.id IS UNIQUE")
            session.run("CREATE CONSTRAINT section_id IF NOT EXISTS FOR (n:Section) REQUIRE n.id IS UNIQUE")
            session.run("CREATE CONSTRAINT subsection_id IF NOT EXISTS FOR (n:Subsection) REQUIRE n.id IS UNIQUE")
            session.run(
                "MERGE (a:Act {id: $id}) "
                "SET a.title = $title, a.act_number = $number, "
                "a.source_url = $source_url, a.source_title = $source_title, "
                "a.source_publisher = $source_publisher, a.source_host = $source_host, "
                "a.source_publication_date = date($source_publication_date), "
                "a.source_type = $source_type, a.source_pdf_pages = $source_pdf_pages",
                id=ACT_ID, title=ACT_TITLE, number=ACT_NUMBER,
                source_url=SOURCE_URL, source_title=SOURCE_TITLE,
                source_publisher=SOURCE_PUBLISHER, source_host=SOURCE_HOST,
                source_publication_date=SOURCE_PUBLICATION_DATE,
                source_type="Official Government PDF", source_pdf_pages=40,
            )
            session.run(
                "CREATE FULLTEXT INDEX act_text_lookup IF NOT EXISTS "
                "FOR (n:Section|Subsection) ON EACH [n.text, n.citation]"
            ).consume()
            session.run("CALL db.awaitIndex($index_name, 60)", index_name=FULLTEXT_INDEX).consume()
            session.execute_write(_write_chapters, chapters)
            session.execute_write(_write_sections, sections)
            counts = session.run(
                "MATCH (a:Act {id: $id}) OPTIONAL MATCH (a)-[:HAS_CHAPTER]->(c:Chapter) "
                "OPTIONAL MATCH (c)-[:HAS_SECTION]->(s:Section) "
                "OPTIONAL MATCH (s)-[:HAS_SUBSECTION]->(ss:Subsection) "
                "RETURN count(DISTINCT c) AS chapters, count(DISTINCT s) AS sections, "
                "count(DISTINCT ss) AS subsections",
                id=ACT_ID,
            ).single()
            print(
                "Neo4j import complete: "
                f"{counts['chapters']} chapters, {counts['sections']} sections, "
                f"{counts['subsections']} subsections in the graph."
            )
    finally:
        driver.close()


def _write_chapters(tx: Any, chapters: list[dict[str, Any]]) -> None:
    tx.run(
        "UNWIND $rows AS row "
        "MERGE (c:Chapter {id: row.id}) "
        "SET c.act_id = row.act_id, c.chapter_number = row.chapter_number, "
        "c.chapter_roman = row.chapter_roman, c.title = row.chapter_title, c.source_file = row.source_file "
        "WITH c, row MATCH (a:Act {id: row.act_id}) MERGE (a)-[:HAS_CHAPTER]->(c)",
        rows=chapters,
    )


def _write_sections(tx: Any, sections: list[dict[str, Any]]) -> None:
    rows = []
    for section in sections:
        subs = section["subsections"]
        section_props = {key: value for key, value in section.items() if key != "subsections"}
        rows.append({
            "section": section_props,
            "subsections": subs,
        })
    tx.run(
        "UNWIND $rows AS row "
        "WITH row, row.section AS p "
        "MATCH (c:Chapter {id: p.chapter_id}) "
        "MERGE (s:Section {id: p.id}) "
        "SET s += p "
        "MERGE (c)-[:HAS_SECTION]->(s) "
        "WITH s, row UNWIND row.subsections AS sub "
        "MERGE (ss:Subsection {id: sub.id}) "
        "SET ss += sub "
        "MERGE (s)-[:HAS_SUBSECTION]->(ss)",
        rows=rows,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import", dest="do_import", action="store_true", help="Import validated data into Neo4j")
    args = parser.parse_args()

    chapters, sections = parse_all()
    report = validate(chapters, sections)
    write_parse_artifacts(chapters, sections, report)
    print(json.dumps({key: value for key, value in report.items() if key != "section_numbers"}, indent=2))
    if not report["valid"]:
        raise SystemExit("Validation failed; Neo4j was not changed. See parsed_output/validation_report.json")
    print("Validated section sequence: 1–107; subsection markers are retained in their text.")
    if args.do_import:
        import_into_neo4j(chapters, sections)
    else:
        print("Dry run only. Re-run with --import to write the validated data to Neo4j.")


if __name__ == "__main__":
    main()
