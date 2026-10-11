# Consumer Protection Act, 2019: retrieval ontology

## Scope and evidence reviewed

This proposal is based on the parsed text of all 107 sections and their 225 numbered subsections across all eight chapters. It is designed to connect provisions that help answer legal questions, not to represent every noun in the Act. Existing `Section` and `Subsection` nodes remain the authoritative text nodes; ontology links add retrieval paths and do not replace the statutory wording.

The parsed chapter files contain some page headers, OCR replacement characters, and publication matter alongside statutory text. Only text belonging to the Act should be used for entity and relationship extraction. In particular, do not create legal concepts from the PDF masthead, page furniture, or text after the Act's closing repeal provision.

## Node model

Keep the current `Act`, `Chapter`, `Section`, and `Subsection` nodes. Add canonical ontology nodes with the label `LegalEntity` and a controlled `entity_type` property. This avoids proliferating Neo4j labels while still preserving meaningful distinctions.

| `entity_type` | Act concepts to canonicalize |
|---|---|
| `PERSON_ROLE` | consumer, complainant, opposite party, consumer association, trader, manufacturer, product manufacturer, product seller, product service provider, service provider, endorser, advertiser, publisher, electronic service provider, mediator, expert |
| `PUBLIC_BODY` | Central Consumer Protection Authority (CCPA/Central Authority), Investigation Wing, District Collector, Central/State/District Consumer Protection Council, District/State/National Commission, Central/State Government, Regulator, appropriate laboratory, Comptroller and Auditor-General, competent court, Supreme Court |
| `MARKET_SUBJECT` | goods, product, service, advertisement, contract, price, consumer information |
| `CONSUMER_ISSUE` | consumer right, defect, deficiency, unfair contract, unfair trade practice, restrictive trade practice, false/misleading advertisement, hazardous/unsafe goods or service, adulterated product, spurious goods, product liability, harm/injury |
| `LEGAL_PROCESS` | complaint, consumer dispute, inquiry, investigation, analysis/test, mediation, settlement, appeal, review, enforcement, compounding |
| `RELIEF_OR_SANCTION` | repair/removal of defect, replacement, refund, compensation, recall/withdrawal, discontinuation/cease-and-desist, corrective advertisement, penalty, imprisonment, licence suspension/cancellation |
| `LEGAL_INSTRUMENT` | Consumer Protection Act, 2019; Consumer Protection Act, 1986; rules, regulations, and other named statutes where the Act expressly refers to them |

Create one canonical node per concept, not one node per mention. Store `canonical_id`, `name`, `entity_type`, and `aliases`; aliases should include statutory variants (for example, `CCPA`, `Central Authority`, and `Central Consumer Protection Authority`) without conflating legally distinct roles. For section-specific public bodies, distinguish District, State, and National Commissions. Keep the role `product seller` distinct from `product manufacturer`, even where one person may occupy both roles.

## Relationship vocabulary

Ontology relationships start at the most specific provision that supports them: a `Subsection` when the rule is in a subsection, otherwise the `Section`. They point from that provision to a canonical `LegalEntity`.

| Relationship | Meaning and typical endpoints |
|---|---|
| `DEFINES` | Provision defines a term → `CONSUMER_ISSUE`, `PERSON_ROLE`, or another concept. Especially useful for Section 2. |
| `ESTABLISHES` | Provision establishes a public body or statutory process → `PUBLIC_BODY` / `LEGAL_PROCESS`. |
| `APPLIES_TO` | Provision expressly applies to a person, market subject, issue, or circumstance. Use only where the scope is stated. |
| `IMPOSES_DUTY_ON` | Provision requires an actor to do or disclose something → `PERSON_ROLE` / `PUBLIC_BODY`. |
| `PROHIBITS` | Provision prohibits conduct or a practice → `CONSUMER_ISSUE` / `MARKET_SUBJECT`. |
| `GRANTS_POWER_TO` | Provision authorizes a body or role to act → `PUBLIC_BODY` / `PERSON_ROLE`. |
| `ASSIGNS_JURISDICTION_TO` | Provision assigns a class of complaint, appeal, or dispute to a Commission/court → `PUBLIC_BODY`; retain value limits and conditions as edge properties/evidence. |
| `GOVERNS_PROCEDURE_FOR` | Provision sets a procedure for a complaint, investigation, test, mediation, appeal, review, or enforcement process → `LEGAL_PROCESS`. |
| `MAKES_LIABLE` | Provision makes a defined actor liable in stated circumstances → `PERSON_ROLE`; preserve the conditions in evidence and properties. |
| `PROVIDES_RELIEF` | Provision authorizes or requires relief/sanction → `RELIEF_OR_SANCTION`. |
| `PRESCRIBES_PENALTY_FOR` | Provision sets a criminal or monetary penalty for an offence/non-compliance → `CONSUMER_ISSUE` or `LEGAL_PROCESS` representing the offence. |
| `EXEMPTS_OR_LIMITS` | Provision creates an exception, defence, exclusion, or limit on liability/procedure → the affected role, issue, or process. Capture the exact condition; do not infer a broad exemption. |
| `APPEALS_TO` | Provision states the appeal forum → `PUBLIC_BODY` (for example, District Commission order → State Commission). |
| `CITES` | Provision explicitly refers to another provision → `Section` or `Subsection`. This is a provision-to-provision edge, not an ontology edge. |

Do not add a vague `RELATED_TO` edge. Do not infer a substantive relationship just because two provisions mention a common word. When the text supports several distinct legal effects, create separate typed edges, each with its own evidence.

## Relationship provenance and normalization

Every extracted ontology relationship should carry:

- `evidence_text`: exact supporting excerpt from the source provision.
- `extraction_method`: `rule` or model identifier.
- `confidence`: extraction confidence for review prioritization, not legal certainty.
- `review_status`: `unreviewed`, `accepted`, or `rejected`.
- Optional `conditions`, `exceptions`, `amount`, `time_limit`, and `jurisdiction_level` when expressly stated and useful for retrieval.

Use deterministic parsing for explicit section citations and resolve the target against the Act's section/subsection IDs. For model-extracted links, require a verbatim evidence span and verify that it occurs in the source node before writing the edge. Preserve negation and provisos: for example, a liability exception must not become a positive liability link.

## Granularity and retrieval rules

- If a section has numbered subsections, attach an ontology link to the particular subsection that states the rule. Attach a link to the Section node only when its section-level text itself expresses a distinct rule or scope.
- If a section has no subsections, attach links to its Section node. It remains a first-class provision and can be a vector, keyword, or graph-retrieval result.
- If a Passage is the vector seed, follow its `HAS_PASSAGE` parent link to the Subsection before ontology expansion. Do not attach duplicated ontology edges to every passage.
- For graph expansion, follow selected semantic relationship types and `CITES`; do not traverse Chapter/Section hierarchy as an unrestricted two-hop neighbor search. Group resulting evidence by parent Section but retain the matching Subsection text and citation.
- Avoid creating retrieval hubs from universal terms such as `person`, `consumer`, `goods`, or `service` unless the provision's legal role is material. Apply degree limits or down-weight very common concepts during expansion.

## Grounded examples from the Act

- Section 2(10) `DEFINES` `defect`; Section 2(11) `DEFINES` `deficiency`; Section 2(28) `DEFINES` `misleading advertisement`.
- Section 18(2) `GRANTS_POWER_TO` CCPA for inquiry, filing complaints, intervention, and other listed functions. Represent materially different powers with their corresponding process/concept nodes and exact evidence, rather than a single unspecific edge.
- Section 21(1) `GRANTS_POWER_TO` CCPA and `PROVIDES_RELIEF` discontinuation or modification of a misleading advertisement.
- Section 35(1) `GOVERNS_PROCEDURE_FOR` complaint filing and identifies permitted complainants; Section 38 governs complaint adjudication and testing procedure.
- Section 39(1) `PROVIDES_RELIEF` including refund, replacement, compensation, recall, and corrective advertisement, with each remedy supported by its specific clause text.
- Sections 84–86 `MAKES_LIABLE` the relevant product manufacturer, product service provider, or product seller subject to their respective conditions; Section 87 `EXEMPTS_OR_LIMITS` product-liability claims in its specified circumstances.
- Sections 41, 51, 67, and 73 use `APPEALS_TO` for their stated appellate route; explicit statutory references in the same text also get `CITES` edges.

## Recommended extraction sequence

1. Create and review this controlled vocabulary and canonical alias list.
2. Add `CITES` edges with a deterministic reference parser, retaining source and target provision IDs.
3. Extract ontology links from each Section/Subsection independently, requesting typed edges plus exact evidence spans in structured JSON.
4. Validate spans, entity aliases, relationship direction, negation, and conditions; keep uncertain edges unreviewed rather than silently importing them as fact.
5. Review a sample from every chapter and every relationship type, then import accepted edges.
6. Evaluate graph expansion on representative legal questions; tune relationship filters and high-degree concept limits before enabling it for answers.
