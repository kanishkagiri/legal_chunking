"""Extract a controlled, evidence-backed ontology graph from the parsed Act text.

The first pass is deterministic: it uses the bounded vocabulary in legal_ontology.md,
exact/alias matching, explicit statutory-reference parsing, and provision-level legal
cues. It does not ask a language model to invent entities or relationships.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "parsed_output" / "act_sections.json"
OUT_FILE = ROOT / "parsed_output" / "legal_ontology_edges.json"
REPORT_FILE = ROOT / "parsed_output" / "legal_ontology_report.json"
ACT_ID = "consumer_protection_act_2019"
EXPANSION_MAX_PROVISIONS = 30

# Deliberately bounded: these are Act concepts that can connect provisions in
# meaningful legal domains. Generic nouns are retained for normalization but are
# not used as graph-expansion bridges.
ENTITIES: list[dict[str, Any]] = [
    {"id":"central_authority","name":"Central Consumer Protection Authority","type":"PUBLIC_BODY","aliases":["Central Consumer Protection Authority","Central Authority","CCPA"]},
    {"id":"district_collector","name":"District Collector","type":"PUBLIC_BODY","aliases":["District Collector"]},
    {"id":"district_commission","name":"District Commission","type":"PUBLIC_BODY","aliases":["District Consumer Disputes Redressal Commission","District Commission"]},
    {"id":"state_commission","name":"State Commission","type":"PUBLIC_BODY","aliases":["State Consumer Disputes Redressal Commission","State Commission"]},
    {"id":"national_commission","name":"National Commission","type":"PUBLIC_BODY","aliases":["National Consumer Disputes Redressal Commission","National Commission"]},
    {"id":"central_council","name":"Central Consumer Protection Council","type":"PUBLIC_BODY","aliases":["Central Consumer Protection Council","Central Council"]},
    {"id":"state_council","name":"State Consumer Protection Council","type":"PUBLIC_BODY","aliases":["State Consumer Protection Council","State Council"]},
    {"id":"district_council","name":"District Consumer Protection Council","type":"PUBLIC_BODY","aliases":["District Consumer Protection Council","District Council"]},
    {"id":"central_government","name":"Central Government","type":"PUBLIC_BODY","aliases":["Central Government"]},
    {"id":"state_government","name":"State Government","type":"PUBLIC_BODY","aliases":["State Government"]},
    {"id":"regulator","name":"Regulator","type":"PUBLIC_BODY","aliases":["Regulator"]},
    {"id":"appropriate_laboratory","name":"Appropriate laboratory","type":"PUBLIC_BODY","aliases":["appropriate laboratory"]},
    {"id":"supreme_court","name":"Supreme Court","type":"PUBLIC_BODY","aliases":["Supreme Court"]},
    {"id":"consumer","name":"Consumer","type":"PERSON_ROLE","aliases":["consumer","consumers"],"generic":True},
    {"id":"complainant","name":"Complainant","type":"PERSON_ROLE","aliases":["complainant","complainants"]},
    {"id":"consumer_association","name":"Consumer association","type":"PERSON_ROLE","aliases":["consumer association","consumer associations","consumer organisation","consumer organization"]},
    {"id":"opposite_party","name":"Opposite party","type":"PERSON_ROLE","aliases":["opposite party","opposite parties"]},
    {"id":"trader","name":"Trader","type":"PERSON_ROLE","aliases":["trader","traders"]},
    {"id":"manufacturer","name":"Manufacturer","type":"PERSON_ROLE","aliases":["manufacturer","manufacturers"]},
    {"id":"product_manufacturer","name":"Product manufacturer","type":"PERSON_ROLE","aliases":["product manufacturer","product manufacturers"]},
    {"id":"product_seller","name":"Product seller","type":"PERSON_ROLE","aliases":["product seller","product sellers"]},
    {"id":"service_provider","name":"Service provider","type":"PERSON_ROLE","aliases":["service provider","service providers"]},
    {"id":"product_service_provider","name":"Product service provider","type":"PERSON_ROLE","aliases":["product service provider","product service providers"]},
    {"id":"endorser","name":"Endorser","type":"PERSON_ROLE","aliases":["endorser","endorsers"]},
    {"id":"advertiser","name":"Advertiser","type":"PERSON_ROLE","aliases":["advertiser","advertisers"]},
    {"id":"publisher","name":"Publisher","type":"PERSON_ROLE","aliases":["publisher","publishers"]},
    {"id":"electronic_service_provider","name":"Electronic service provider","type":"PERSON_ROLE","aliases":["electronic service provider","electronic service providers"]},
    {"id":"mediator","name":"Mediator","type":"PERSON_ROLE","aliases":["mediator","mediators"]},
    {"id":"consumer_rights","name":"Consumer rights","type":"CONSUMER_ISSUE","aliases":["consumer rights","right of consumers","rights of consumers"]},
    {"id":"complaint","name":"Consumer complaint","type":"LEGAL_PROCESS","aliases":["complaint","complaints"]},
    {"id":"consumer_dispute","name":"Consumer dispute","type":"LEGAL_PROCESS","aliases":["consumer dispute","consumer disputes"]},
    {"id":"defect","name":"Defect","type":"CONSUMER_ISSUE","aliases":["defect","defects","defective"]},
    {"id":"deficiency","name":"Service deficiency","type":"CONSUMER_ISSUE","aliases":["deficiency","deficiencies","deficient"]},
    {"id":"unfair_contract","name":"Unfair contract","type":"CONSUMER_ISSUE","aliases":["unfair contract","unfair contracts"]},
    {"id":"unfair_trade_practice","name":"Unfair trade practice","type":"CONSUMER_ISSUE","aliases":["unfair trade practice","unfair trade practices"]},
    {"id":"restrictive_trade_practice","name":"Restrictive trade practice","type":"CONSUMER_ISSUE","aliases":["restrictive trade practice","restrictive trade practices"]},
    {"id":"misleading_advertisement","name":"False or misleading advertisement","type":"CONSUMER_ISSUE","aliases":["false or misleading advertisement","false or misleading advertisements","misleading advertisement","misleading advertisements"]},
    {"id":"hazardous_goods","name":"Hazardous or unsafe goods","type":"CONSUMER_ISSUE","aliases":["hazardous goods","unsafe goods","dangerous goods"]},
    {"id":"hazardous_service","name":"Hazardous service","type":"CONSUMER_ISSUE","aliases":["hazardous service","hazardous services","unsafe service","unsafe services"]},
    {"id":"spurious_goods","name":"Spurious goods","type":"CONSUMER_ISSUE","aliases":["spurious goods"]},
    {"id":"adulterated_product","name":"Product containing an adulterant","type":"CONSUMER_ISSUE","aliases":["adulterant","adulterated product","products containing an adulterant"]},
    {"id":"product_liability","name":"Product liability","type":"CONSUMER_ISSUE","aliases":["product liability","product liability action","product liability actions"]},
    {"id":"harm_injury","name":"Harm or injury","type":"CONSUMER_ISSUE","aliases":["harm","injury","injuries"]},
    {"id":"mediation","name":"Consumer mediation","type":"LEGAL_PROCESS","aliases":["mediation","consumer mediation"]},
    {"id":"investigation","name":"Inquiry or investigation","type":"LEGAL_PROCESS","aliases":["investigation","investigations","inquiry","inquiries"]},
    {"id":"appeal","name":"Appeal","type":"LEGAL_PROCESS","aliases":["appeal","appeals"]},
    {"id":"review","name":"Review of an order","type":"LEGAL_PROCESS","aliases":["review"]},
    {"id":"refund","name":"Refund","type":"RELIEF_OR_SANCTION","aliases":["refund","refunds","reimbursement"]},
    {"id":"replacement","name":"Replacement","type":"RELIEF_OR_SANCTION","aliases":["replace the goods","replacement","replace such goods"]},
    {"id":"compensation","name":"Compensation","type":"RELIEF_OR_SANCTION","aliases":["compensation","compensate"]},
    {"id":"recall_withdrawal","name":"Recall or withdrawal of goods/services","type":"RELIEF_OR_SANCTION","aliases":["recalling of goods","withdrawal of services","withdraw the hazardous goods","recall"]},
    {"id":"corrective_advertisement","name":"Corrective advertisement","type":"RELIEF_OR_SANCTION","aliases":["corrective advertisement"]},
    {"id":"penalty","name":"Penalty","type":"RELIEF_OR_SANCTION","aliases":["penalty","penalties"]},
    {"id":"imprisonment","name":"Imprisonment","type":"RELIEF_OR_SANCTION","aliases":["imprisonment"]},
]

GENERIC_ENTITY_IDS = {"consumer"}
RELATION_TYPES = {
    "DEFINES", "ESTABLISHES", "APPLIES_TO", "IMPOSES_DUTY_ON", "PROHIBITS",
    "GRANTS_POWER_TO", "ASSIGNS_JURISDICTION_TO", "GOVERNS_PROCEDURE_FOR",
    "MAKES_LIABLE", "PROVIDES_RELIEF", "PRESCRIBES_PENALTY_FOR",
    "EXEMPTS_OR_LIMITS", "APPEALS_TO",
}


def clean_statutory_text(text: str) -> str:
    text = text.replace("\ufffd", " ")
    # The chapter extraction has PDF publication matter appended after these markers.
    for marker in ("MINISTRY OF LAW AND JUSTICE", "DR. G. NARAYANA RAJU", "UPLOADED BY THE MANAGER"):
        if marker in text:
            text = text.split(marker, 1)[0]
    return re.sub(r"[ \t]+", " ", text).strip()


def alias_pattern(alias: str) -> re.Pattern[str]:
    words = re.split(r"\s+", alias.strip())
    body = r"[\s\-/]+".join(re.escape(word) for word in words)
    return re.compile(rf"(?<![A-Za-z]){body}(?![A-Za-z])", re.IGNORECASE)


ALIAS_PATTERNS = [
    (entity, alias, alias_pattern(alias))
    for entity in ENTITIES
    for alias in entity["aliases"]
]


def entity_mentions(text: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for entity, alias, pattern in ALIAS_PATTERNS:
        for match in pattern.finditer(text):
            matches.append({"entity": entity, "alias": alias, "start": match.start(), "end": match.end()})
    # Prefer the longest alias at overlapping spans, e.g. Product manufacturer over Manufacturer.
    matches.sort(key=lambda item: (item["start"], -(item["end"] - item["start"])))
    selected: list[dict[str, Any]] = []
    for match in matches:
        if any(match["start"] < old["end"] and match["end"] > old["start"] for old in selected):
            continue
        selected.append(match)
    return selected


def local_context(text: str, start: int, end: int, radius: int = 220) -> str:
    # Stay inside a clause where possible; a fixed-radius window can accidentally
    # borrow a "shall" or "penalty" cue from a neighboring legal clause.
    left_candidates = [text.rfind(mark, 0, start) for mark in (";", ".", "\n")]
    left = max(left_candidates) + 1
    right_candidates = [position for mark in (";", ".", "\n") if (position := text.find(mark, end)) >= 0]
    right = min(right_candidates) if right_candidates else len(text)
    if right - left > radius * 2:
        left = max(left, start - radius)
        right = min(right, end + radius)
    return text[left:right].strip()


def relations_for(section_number: int, entity: dict[str, Any], context: str, definition_subject: bool) -> list[str]:
    low = context.lower()
    etype = entity["type"]
    eid = entity["id"]
    result: list[str] = []

    if section_number == 2 and definition_subject:
        # Only link DEFINES when this matched term is the subject immediately
        # followed by "means"/"includes", not when mentioned in another definition.
        result.append("DEFINES")
    if section_number != 2 and re.search(r"\b(establish|establishes|established|constitute|constituted)\b", low) and etype == "PUBLIC_BODY":
        result.append("ESTABLISHES")
    if re.search(r"\b(jurisdiction|jurisdictional)\b", low) and etype == "PUBLIC_BODY":
        result.append("ASSIGNS_JURISDICTION_TO")
    if re.search(r"\bappeal\w*\b.{0,100}\bto\s+(?:the\s+)?", low, re.S) and etype == "PUBLIC_BODY":
        result.append("APPEALS_TO")
    if re.search(r"\bliable\b", low) and etype == "PERSON_ROLE":
        result.append("MAKES_LIABLE")
    if section_number != 2 and re.search(r"\b(punish|punishable|imprisonment|fine|offence|offense)\w*\b|\bimpose\w*.{0,50}\bpenalt\w*\b", low):
        if etype in {"RELIEF_OR_SANCTION", "CONSUMER_ISSUE", "LEGAL_PROCESS"}:
            result.append("PRESCRIBES_PENALTY_FOR")
    if re.search(r"\b(refund|replace|replacement|compensation|recall|withdraw|corrective advertisement|cease|discontinue)\w*\b", low) and etype == "RELIEF_OR_SANCTION":
        result.append("PROVIDES_RELIEF")
    if re.search(r"\bmay\b.{0,100}\b(power|direct|order|issue|refer|designate|transfer|appoint|establish)\w*\b|\b(?:shall|has|have)\s+power\b", low, re.S) and etype == "PUBLIC_BODY":
        result.append("GRANTS_POWER_TO")
    if re.search(r"\b(prohibit|prohibited|shall not|no person|prevent)\w*\b", low) and etype in {"CONSUMER_ISSUE", "MARKET_SUBJECT"}:
        result.append("PROHIBITS")
    if re.search(r"\b(not liable|shall not be liable|does not apply|shall not apply|does not include|except|exemption|defence|defense)\b", low):
        if etype in {"PERSON_ROLE", "CONSUMER_ISSUE", "LEGAL_PROCESS", "MARKET_SUBJECT"}:
            result.append("EXEMPTS_OR_LIMITS")
    if re.search(r"\b(shall|must|required to|duty to|responsible for|maintain|submit|disclose)\b", low) and etype in {"PERSON_ROLE", "PUBLIC_BODY"}:
        result.append("IMPOSES_DUTY_ON")
    if re.search(r"\b(proceeding|procedure|file|filing|admit|hearing|hear|refer|transfer|settle|settlement|investigat|inquir|review|enforc|serve|test|analysis)\w*\b", low) and eid in {"complaint", "consumer_dispute", "mediation", "investigation", "appeal", "review"}:
        result.append("GOVERNS_PROCEDURE_FOR")

    # A typed, provision-to-topic link is useful where the provision expressly applies
    # to or is about the matched non-generic statutory concept. Generic 'consumer'
    # mentions are deliberately excluded from expansion.
    if not result and eid not in GENERIC_ENTITY_IDS and re.search(r"\b(applies? to|applicable to|in relation to|with respect to|relating to|for the purposes? of)\b", low):
        result.append("APPLIES_TO")
    return list(dict.fromkeys(result))


def iter_provisions(data: dict[str, Any]):
    for section in data["sections"]:
        section_text = clean_statutory_text(section["text"])
        if section_text:
            yield {
                "id": section["id"], "label": "Section", "citation": section["citation"],
                "section_number": section["section_number"], "text": section_text,
                "chapter_number": section["chapter_number"], "chapter_title": section["chapter_title"],
            }
        for subsection in section["subsections"]:
            text = clean_statutory_text(subsection["text"])
            if text:
                yield {
                    "id": subsection["id"], "label": "Subsection", "citation": subsection["citation"],
                    "section_number": subsection["section_number"], "subsection_number": subsection["subsection_number"],
                    "text": text, "chapter_number": subsection["chapter_number"], "chapter_title": subsection["chapter_title"],
                }


def extract_citations(provision: dict[str, Any]) -> list[dict[str, Any]]:
    text = provision["text"]
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    # Match explicit sub-section references first so section-level references do not
    # swallow the more precise target.
    patterns = [
        re.compile(r"\bsub[- ]sections?\s*\((\d+)\)\s*(?:of\s+)?sections?\s+(\d+)\b", re.I),
        re.compile(r"\bsub[- ]section\s*\((\d+)\)\s+of\s+section\s+(\d+)\b", re.I),
        re.compile(r"\bclause\s*\((\d+)\)\s+of\s+section\s+(\d+)\b", re.I),
    ]
    covered: list[tuple[int, int]] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            sub_no, sec_no = int(match.group(1)), int(match.group(2))
            target_id = f"{ACT_ID}:section:{sec_no}:subsection:{sub_no}"
            key = (target_id, match.group(0))
            edges[key] = {"target_id": target_id, "reference_text": match.group(0), "evidence_text": match.group(0), "extraction_method": "explicit_reference_regex", "review_status": "accepted"}
            covered.append(match.span())

    # Also recognize nested statutory cross-references, e.g. clause (v) of clause (5)
    # of section 2, as a link to the numbered subsection node (2(5)).
    nested = re.compile(r"\b(?:sub-clause|subclause)\s*\([ivxlcdm]+\)\s+of\s+clause\s*\((\d+)\)\s+of\s+section\s+(\d+)\b", re.I)
    for match in nested.finditer(text):
        sub_no, sec_no = int(match.group(1)), int(match.group(2))
        target_id = f"{ACT_ID}:section:{sec_no}:subsection:{sub_no}"
        edges[(target_id, match.group(0))] = {"target_id": target_id, "reference_text": match.group(0), "evidence_text": match.group(0), "extraction_method": "explicit_reference_regex", "review_status": "accepted"}
        covered.append(match.span())

    section_ref = re.compile(r"\bsections?\s+(\d+)(?:\s*(?:and|,|to|–|-)\s*(\d+))?\b", re.I)
    for match in section_ref.finditer(text):
        if any(match.start() < end and match.end() > start for start, end in covered):
            continue
        first = int(match.group(1))
        second = int(match.group(2)) if match.group(2) else first
        if second - first > 20:
            continue
        for sec_no in range(first, second + 1):
            target_id = f"{ACT_ID}:section:{sec_no}"
            edges[(target_id, match.group(0))] = {"target_id": target_id, "reference_text": match.group(0), "evidence_text": match.group(0), "extraction_method": "explicit_reference_regex", "review_status": "accepted"}
    return list(edges.values())


def build_graph_data(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    provisions = list(iter_provisions(data))
    provision_ids = {p["id"] for p in provisions}
    entity_by_id = {entity["id"]: entity for entity in ENTITIES}
    raw_edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    mention_counts: Counter[str] = Counter()

    for provision in provisions:
        for mention in entity_mentions(provision["text"]):
            entity = mention["entity"]
            mention_counts[entity["id"]] += 1
            context = local_context(provision["text"], mention["start"], mention["end"])
            tail = provision["text"][mention["end"]:mention["end"] + 45]
            definition_subject = provision["section_number"] == 2 and bool(re.match(r"\W*(?:means|includes|shall mean)\b", tail, re.I))
            for rel_type in relations_for(provision["section_number"], entity, context, definition_subject):
                excerpt_start = max(0, mention["start"] - 110)
                excerpt_end = min(len(provision["text"]), mention["end"] + 150)
                evidence = provision["text"][excerpt_start:excerpt_end].strip()
                key = (provision["id"], entity["id"], rel_type)
                raw_edges.setdefault(key, {
                    "source_id": provision["id"], "source_label": provision["label"],
                    "source_citation": provision["citation"], "entity_id": entity["id"],
                    "relationship_type": rel_type, "evidence_text": evidence,
                    "extraction_method": "controlled_alias_and_legal_cue_rules_v1",
                    "review_status": "unreviewed",
                    "evidence_key": f"{provision['id']}|{entity['id']}|{rel_type}",
                })

    # Keep only actual multi-provision bridges; one-off mentions are not useful for
    # expansion and are reported rather than imported as dangling ontology nodes.
    links_by_entity: dict[str, set[str]] = defaultdict(set)
    for edge in raw_edges.values():
        links_by_entity[edge["entity_id"]].add(edge["source_id"])
    persisted_ids = {eid for eid, sources in links_by_entity.items() if len(sources) >= 2}
    entities = []
    for eid in sorted(persisted_ids):
        entity = entity_by_id[eid]
        degree = len(links_by_entity[eid])
        generic = entity.get("generic", False)
        entities.append({
            "id": f"{ACT_ID}:entity:{eid}", "canonical_id": eid,
            "name": entity["name"], "entity_type": entity["type"],
            "aliases": entity["aliases"], "provision_degree": degree,
            "expansion_eligible": not generic and degree <= EXPANSION_MAX_PROVISIONS,
        })
    entity_edges = [
        edge for edge in raw_edges.values()
        if edge["entity_id"] in persisted_ids
    ]

    all_citations: list[dict[str, Any]] = []
    for provision in provisions:
        for edge in extract_citations(provision):
            if edge["target_id"] not in provision_ids:
                continue
            if edge["target_id"] == provision["id"]:
                continue
            all_citations.append({
                "source_id": provision["id"], "source_citation": provision["citation"],
                "target_id": edge["target_id"], "reference_text": edge["reference_text"],
                "evidence_text": edge["evidence_text"], "extraction_method": edge["extraction_method"],
                "review_status": edge["review_status"],
            })

    degrees = [len(links_by_entity[eid]) for eid in persisted_ids]
    expandable = sum(1 for entity in entities if entity["expansion_eligible"])
    report = {
        "act_id": ACT_ID,
        "method": "controlled ontology alias matching plus deterministic legal-cue/reference rules; no LLM-generated links",
        "source_provisions_scanned": len(provisions),
        "candidate_entity_count": len(mention_counts),
        "candidate_entity_link_count": len(links_by_entity),
        "entities_excluded_single_provision": sorted(eid for eid, srcs in links_by_entity.items() if len(srcs) < 2),
        "persisted_entity_count": len(entities),
        "persisted_entities_linked_to_multiple_provisions": sum(1 for d in degrees if d > 1),
        "persisted_multi_provision_entity_ratio": (sum(1 for d in degrees if d > 1) / len(entities)) if entities else 0.0,
        "expansion_eligible_entity_count": expandable,
        "expansion_eligible_entity_ratio": (expandable / len(entities)) if entities else 0.0,
        "expansion_max_provisions": EXPANSION_MAX_PROVISIONS,
        "ontology_relationship_count": len(entity_edges),
        "explicit_cites_relationship_count": len(all_citations),
        "relationship_type_counts": dict(Counter(edge["relationship_type"] for edge in entity_edges)),
        "entity_degrees": {eid: sorted(srcs) for eid, srcs in sorted(links_by_entity.items()) if eid in persisted_ids},
        "entities": entities,
    }
    return entities, entity_edges + all_citations, report


def import_graph(entities: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, int]:
    from neo4j import GraphDatabase

    load_dotenv(ROOT / ".env")
    uri, username, password = os.getenv("NEO4J_URI"), os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")
    if not all((uri, username, password)):
        raise RuntimeError("Set NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD in .env")
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            session.run("CREATE CONSTRAINT legal_entity_canonical_id IF NOT EXISTS FOR (n:LegalEntity) REQUIRE n.canonical_id IS UNIQUE").consume()
            session.execute_write(_write_entities_and_edges, entities, edges)
        with driver.session() as session:
            entity_count = session.run(
                "MATCH (e:LegalEntity {act_id: $act_id}) RETURN count(e) AS n", act_id=ACT_ID
            ).single()["n"]
            linked = session.run(
                "MATCH (e:LegalEntity {act_id: $act_id})-[]-(p) "
                "WHERE p:Section OR p:Subsection "
                "WITH e, count(DISTINCT p) AS provision_count "
                "RETURN count(e) AS total, count(CASE WHEN provision_count > 1 THEN 1 END) AS multiple, "
                "count(CASE WHEN e.expansion_eligible AND provision_count > 1 THEN 1 END) AS expandable",
                act_id=ACT_ID,
            ).single()
            cites_count = session.run(
                "MATCH (:Section|Subsection)-[r:CITES]->(:Section|Subsection) "
                "WHERE r.act_id = $act_id RETURN count(r) AS n", act_id=ACT_ID
            ).single()["n"]
            return {"entity_nodes": entity_count, "linked_entities": linked["multiple"],
                    "expansion_eligible_entities": linked["expandable"], "cites_relationships": cites_count}
    finally:
        driver.close()


def _write_entities_and_edges(tx: Any, entities: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    tx.run(
        "UNWIND $rows AS row MERGE (e:LegalEntity {canonical_id: row.canonical_id}) "
        "SET e += row, e.act_id = $act_id",
        rows=entities, act_id=ACT_ID,
    ).consume()
    for rel_type in sorted(RELATION_TYPES):
        rows = [edge for edge in edges if edge.get("relationship_type") == rel_type]
        if not rows:
            continue
        tx.run(
            f"UNWIND $rows AS row MATCH (p {{id: row.source_id}}) "
            "MATCH (e:LegalEntity {canonical_id: row.entity_id}) "
            f"MERGE (p)-[r:{rel_type} {{evidence_key: row.evidence_key}}]->(e) "
            "SET r.evidence_text = row.evidence_text, r.extraction_method = row.extraction_method, "
            "r.review_status = row.review_status, r.act_id = $act_id",
            rows=rows, act_id=ACT_ID,
        ).consume()
    cite_rows = []
    for edge in edges:
        if "target_id" in edge:
            cite_rows.append({
                **edge,
                "evidence_key": f"{edge['source_id']}|{edge['target_id']}|{edge['reference_text']}",
            })
    if cite_rows:
        tx.run(
            "UNWIND $rows AS row MATCH (src {id: row.source_id}) MATCH (dst {id: row.target_id}) "
            "MERGE (src)-[r:CITES {evidence_key: row.evidence_key}]->(dst) "
            "SET r.reference_text = row.reference_text, r.evidence_text = row.evidence_text, "
            "r.extraction_method = row.extraction_method, r.review_status = row.review_status, r.act_id = $act_id",
            rows=cite_rows, act_id=ACT_ID,
        ).consume()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import", dest="do_import", action="store_true", help="Write ontology nodes and relationships to Neo4j")
    args = parser.parse_args()
    if not DATA_FILE.exists():
        raise SystemExit(f"Missing {DATA_FILE}; run neo4j_pipeline.py first")
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    entities, edges, report = build_graph_data(data)
    ontology_edges = [edge for edge in edges if "relationship_type" in edge]
    cite_edges = [edge for edge in edges if "target_id" in edge]
    OUT_FILE.write_text(json.dumps({"act_id": ACT_ID, "entities": entities, "ontology_relationships": ontology_edges, "cites_relationships": cite_edges}, ensure_ascii=False, indent=2), encoding="utf-8")
    # Keep the graph-sized report separate from detailed edge evidence.
    report_for_file = {key: value for key, value in report.items() if key not in {"entities", "entity_degrees"}}
    report_for_file["expansion_eligible_entities"] = [
        {"canonical_id": e["canonical_id"], "name": e["name"], "entity_type": e["entity_type"], "provision_degree": e["provision_degree"]}
        for e in entities if e["expansion_eligible"]
    ]
    report_for_file["multi_provision_entities"] = [
        {"canonical_id": e["canonical_id"], "name": e["name"], "provision_degree": e["provision_degree"]}
        for e in entities
    ]
    REPORT_FILE.write_text(json.dumps(report_for_file, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_keys = (
        "source_provisions_scanned", "candidate_entity_count", "candidate_entity_link_count",
        "entities_excluded_single_provision", "persisted_entity_count",
        "persisted_entities_linked_to_multiple_provisions", "persisted_multi_provision_entity_ratio",
        "expansion_eligible_entity_count", "expansion_eligible_entity_ratio",
        "ontology_relationship_count", "explicit_cites_relationship_count", "relationship_type_counts",
    )
    print(json.dumps({key: report_for_file[key] for key in summary_keys}, ensure_ascii=False, indent=2))
    if report["persisted_entity_count"] == 0:
        raise SystemExit("No multi-provision ontology entities were found; Neo4j was not changed.")
    if args.do_import:
        result = import_graph(entities, edges)
        report_for_file["neo4j_verification"] = result
        REPORT_FILE.write_text(json.dumps(report_for_file, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Neo4j verification:", json.dumps(result, ensure_ascii=False))
        if result["linked_entities"] != result["entity_nodes"]:
            raise SystemExit("Import verification failed: a stored entity is not linked to multiple provisions.")
    else:
        print("Dry run only. Review the evidence in parsed_output/legal_ontology_edges.json; use --import to write to Neo4j.")


if __name__ == "__main__":
    main()
