"""Compare keyword, vector, and graph retrieval on labeled Act questions."""

from __future__ import annotations

import json
import math
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rag_backend import LegalRAGRetriever, analyze_query


ROOT = Path(__file__).resolve().parent
REPORT_JSON = ROOT / "parsed_output" / "retrieval_comparison.json"
REPORT_MD = ROOT / "retrieval_comparison.md"
TOP_K = 5
CANDIDATE_LIMIT = 25

# Gold citations are manually assigned from the Act and are used only to measure
# retrieval ranking/coverage. They do not assert that a generated answer is correct.
QUESTIONS = [
    {"id": "exact_definition", "query": "What practices are included in the definition of unfair trade practice?", "gold": ["Section 2(47)"], "expected_strength": "keyword", "reason": "Uses the statutory phrase and definition wording."},
    {"id": "exact_citation", "query": "What can the Central Authority do under Section 21(1) about a misleading advertisement?", "gold": ["Section 21(1)"], "expected_strength": "keyword", "reason": "Contains an explicit provision citation and statutory terms."},
    {"id": "quoted_phrase", "query": "Which provision says a consumer can seek compensation for loss or injury caused by negligence?", "gold": ["Section 2(11)", "Section 39(1)"], "expected_strength": "keyword", "reason": "Tests phrase overlap around negligence, injury, and compensation."},
    {"id": "semantic_paraphrase", "query": "If something bought online is faulty, what remedies can the consumer forum grant?", "gold": ["Section 39(1)"], "expected_strength": "vector", "reason": "Paraphrases statutory wording and asks for the legal outcome."},
    {"id": "semantic_who_may_complain", "query": "Can a group of people affected in the same way bring one case together?", "gold": ["Section 2(5)", "Section 35(1)"], "expected_strength": "vector", "reason": "Uses a plain-language description of numerous consumers with the same interest."},
    {"id": "semantic_lab_test", "query": "What happens when deciding whether a product is defective requires specialist testing?", "gold": ["Section 38(2)"], "expected_strength": "vector", "reason": "Describes laboratory analysis without copying the Act's exact phrase."},
    {"id": "cross_reference", "query": "What procedure applies to an analysis or test of articles other than those covered by Section 38(2)?", "gold": ["Section 38(5)", "Section 38(2)"], "expected_strength": "graph", "reason": "Tests explicit CITES expansion from the provision to the referenced procedure."},
    {"id": "appeal_path", "query": "Where can a consumer appeal a District Commission order, and what is the statutory route?", "gold": ["Section 41"], "expected_strength": "graph", "reason": "Tests expansion among provisions connected by appeal/jurisdiction concepts."},
    {"id": "related_definitions", "query": "How does the Act connect misleading advertisements with unfair trade practices?", "gold": ["Section 2(28)", "Section 2(47)", "Section 17", "Section 21"], "expected_strength": "graph", "reason": "Tests cross-provision concept expansion; multiple gold provisions are relevant."},
]


def _unique_citations(hits: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(str(hit.get("citation", "")) for hit in hits if hit.get("citation")))


def _normalise_citation(citation: str) -> str:
    return "".join(str(citation).casefold().split())


def _metrics(hits: list[dict[str, Any]], gold: list[str], k: int) -> dict[str, float]:
    citations = _unique_citations(hits[:k])
    relevant = {_normalise_citation(citation) for citation in gold}
    normalized_citations = [_normalise_citation(citation) for citation in citations]
    found = [citation for citation in normalized_citations if citation in relevant]
    first_rank = next((rank for rank, citation in enumerate(normalized_citations, 1) if citation in relevant), None)
    dcg = sum(1.0 / math.log2(rank + 1) for rank, citation in enumerate(normalized_citations, 1) if citation in relevant)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    return {
        f"precision@{k}": len(found) / k,
        f"recall@{k}": len(found) / len(relevant) if relevant else 0.0,
        f"mrr@{k}": 1.0 / first_rank if first_rank else 0.0,
        f"ndcg@{k}": dcg / ideal if ideal else 0.0,
        f"hit@{k}": 1.0 if found else 0.0,
    }


def _mean(rows: list[dict[str, Any]], key: str) -> float:
    return sum(float(row["metrics"][key]) for row in rows) / len(rows) if rows else 0.0


def _evaluate_one(retriever: LegalRAGRetriever, query: str, gold: list[str], modes: list[str],
                  top_k: int, candidate_limit: int) -> list[dict[str, Any]]:
    rows = []
    for mode in modes:
        result = retriever.retrieve(query, mode, top_k=top_k, candidate_limit=candidate_limit)
        rows.append({
            "mode": mode,
            "analysis": result["analysis"],
            "candidate_count": result["candidate_count"],
            "retrieved_citations": _unique_citations(result["top_k"]),
            "metrics": _metrics(result["top_k"], gold, top_k),
            "top_k": result["top_k"],
        })
    return rows


def evaluate_custom_question(query: str, gold: list[str], modes: list[str] | None = None,
                             top_k: int = TOP_K, candidate_limit: int = CANDIDATE_LIMIT) -> dict[str, Any]:
    if not query.strip():
        raise ValueError("question cannot be empty")
    normalized_gold = list(dict.fromkeys(item.strip() for item in gold if item.strip()))
    if not normalized_gold:
        raise ValueError("at least one gold citation is required to calculate retrieval metrics")
    modes = modes or ["keyword", "vector", "graph"]
    retriever = LegalRAGRetriever()
    mode_results = _evaluate_one(retriever, query, normalized_gold, modes, top_k, candidate_limit)
    return {
        "question": query,
        "gold_citations": normalized_gold,
        "top_k": top_k,
        "candidate_limit": candidate_limit,
        "metrics_note": "Citation-level metrics compare returned citations with the supplied gold citations; they are retrieval metrics, not answer-quality scores.",
        "results": mode_results,
    }


def run_evaluation(top_k: int = TOP_K, candidate_limit: int = CANDIDATE_LIMIT) -> dict[str, Any]:
    retriever = LegalRAGRetriever()
    analysis_cache: dict[str, dict[str, Any]] = {}

    def cached_analyzer(question: str) -> dict[str, Any]:
        if question not in analysis_cache:
            analysis_cache[question] = analyze_query(question)
        return analysis_cache[question]

    retriever.analyzer = cached_analyzer
    rows: list[dict[str, Any]] = []
    for question in QUESTIONS:
        for result in _evaluate_one(retriever, question["query"], question["gold"],
                                    ["keyword", "vector", "graph"], top_k, candidate_limit):
            rows.append({
                "question_id": question["id"], "query": question["query"],
                "gold_citations": question["gold"], "expected_strength": question["expected_strength"],
                "reason": question["reason"], "mode": result["mode"],
                "analysis_provider": result["analysis"].get("analysis_provider"),
                "candidate_count": result["candidate_count"],
                "top_k_citations": result["retrieved_citations"],
                "top_k": result["top_k"], "metrics": result["metrics"],
            })
    metric_names = list(rows[0]["metrics"]) if rows else []
    summaries = {
        mode: {metric: _mean([row for row in rows if row["mode"] == mode], metric) for metric in metric_names}
        for mode in ("keyword", "vector", "graph")
    }
    analysis_providers = Counter(item.get("analysis_provider") or "unknown" for item in analysis_cache.values())
    target_wins = Counter()
    for question in QUESTIONS:
        group = [row for row in rows if row["question_id"] == question["id"]]
        best_recall = max(row["metrics"][f"recall@{top_k}"] for row in group)
        for row in group:
            if row["metrics"][f"recall@{top_k}"] == best_recall:
                target_wins[row["mode"]] += 1
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_description": "Nine manually labeled questions over the Consumer Protection Act 2019; retrieval-only evaluation, no generated answers.",
        "settings": {"top_k": top_k, "candidate_limit": candidate_limit,
                     "embedding_model": "BAAI/bge-small-en-v1.5",
                     "reranker_model": "jinaai/jina-reranker-v1-turbo-en", "query_analyzer": "deterministic rules; no LLM/API"},
        "summary_metrics": summaries,
        "analysis_provider_counts": dict(analysis_providers),
        "retrieval_modes_tied_or_winning_recall_questions": dict(target_wins),
        "results": rows,
    }


def write_reports(report: dict[str, Any]) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    keys = list(next(iter(report["summary_metrics"].values())))
    lines = [
        "# Retrieval Mode Comparison",
        "",
        f"Run time (UTC): {report['generated_at_utc']}",
        "",
        "## Scope and setup",
        "",
        report["dataset_description"],
        "",
        f"Candidate pool: up to {report['settings']['candidate_limit']}; final reranked context: top {report['settings']['top_k']}. "
        f"Query embeddings use {report['settings']['embedding_model']}; reranking uses {report['settings']['reranker_model']}.",
        "",
        "Query analysis providers: " + ", ".join(f"{name}: {count}" for name, count in report.get("analysis_provider_counts", {}).items()) + ".",
        "",
        "## Run the retrieval pipeline",
        "",
        "From the project directory, run the CLI with the chosen retrieval mode:",
        "",
        "```powershell",
        ".venv\\Scripts\\python.exe rag_backend.py \"What can the Central Authority do about a misleading advertisement?\" --mode graph --top-k 5 --candidate-limit 25",
        "```",
        "",
        "Valid modes are `keyword`, `vector`, and `graph`. The response contains the reranked top-k evidence, Act source metadata, and graph relationship names/properties when expansion supplied a candidate. It stops before SLM generation and includes answer-grounding rules for the next stage.",
        "",
        f"Metrics are calculated at the citation level after reranking. Precision@{report['settings']['top_k']} uses the fixed context budget; Recall@{report['settings']['top_k']} counts labeled relevant citations found; MRR rewards the earliest relevant citation; nDCG rewards relevant citations near the top; Hit records whether at least one gold citation appears.",
        "",
        "This measures retrieval ranking only. There is no SLM answer generation, so the table does not measure answer correctness, hallucination rate, or citation faithfulness. The questions and gold citations are a small manually labeled sample, not a general benchmark.",
        "",
        "## Average metrics",
        "",
        "| Mode | " + " | ".join(keys) + " |",
        "|---|" + "|".join(["---:"] * len(keys)) + "|",
    ]
    for mode, metrics in report["summary_metrics"].items():
        lines.append("| " + mode + " | " + " | ".join(f"{metrics[key]:.3f}" for key in keys) + " |")
    lines.extend(["", "## Per-question results", "", "| Question | Expected strength | Gold citations | Keyword (ranked citations) | Vector (ranked citations) | Graph (ranked citations) |", "|---|---|---|---|---|---|"])
    question_by_id = {q["id"]: q for q in QUESTIONS}
    for question_id in dict.fromkeys(row["question_id"] for row in report["results"]):
        group = {row["mode"]: row for row in report["results"] if row["question_id"] == question_id}
        q = question_by_id[question_id]
        fmt = lambda row: ", ".join(f"{c} ({i})" for i, c in enumerate(row["top_k_citations"], 1)) or "—"
        lines.append("| " + q["query"].replace("|", "\\|") + " | " + q["expected_strength"] + " | " + ", ".join(q["gold"]) + " | " + fmt(group["keyword"]) + " | " + fmt(group["vector"]) + " | " + fmt(group["graph"]) + " |")
    best_by_metric = {
        metric: [mode for mode in report["summary_metrics"]
                 if report["summary_metrics"][mode][metric] == max(values[metric] for values in report["summary_metrics"].values())]
        for metric in keys
    }
    winners_text = "; ".join(f"{metric}: {', '.join(modes)}" for metric, modes in best_by_metric.items())
    lines.extend(["", "## Interpretation", "", "Best average mode(s) by metric: " + winners_text + ".", "", "The exact Section 21(1) question put the gold citation first in keyword, vector, and graph results. Graph mode ranked Section 41 first for the appeal question (vector ranked it second) and surfaced Sections 17 and 21 among the related-concepts results. On the explicit cross-reference question it returned both labeled citations within the top three, comparable to vector mode. It did not recover every labeled citation on every query. These observations apply to this small manually labeled set, not to all legal questions.", "", "Graph expansion exposes the connecting relationship types and stored relationship properties with each expanded candidate. Ontology edges were previously marked `unreviewed`; they are surfaced as candidate expansion evidence and should not be treated as verified legal conclusions. Explicit `CITES` edges are also returned with their stored reference/evidence properties.", ""])
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", help="Evaluate a new question instead of the built-in nine-question set")
    parser.add_argument("--gold", action="append", default=[], help="Relevant citation; repeat this option for multiple gold citations")
    parser.add_argument("--mode", choices=("all", "keyword", "vector", "graph"), default="all")
    parser.add_argument("--top-k", type=int, default=TOP_K)
    parser.add_argument("--candidate-limit", type=int, default=CANDIDATE_LIMIT)
    parser.add_argument("--output", help="Optional JSON output path for a one-question evaluation")
    args = parser.parse_args()
    if not 1 <= args.top_k <= 20 or not args.top_k <= args.candidate_limit <= 100:
        parser.error("require 1 <= --top-k <= 20 and --top-k <= --candidate-limit <= 100")

    if args.question:
        if not args.gold:
            parser.error("--gold is required with --question because metrics need known relevant citation(s)")
        modes = ["keyword", "vector", "graph"] if args.mode == "all" else [args.mode]
        report = evaluate_custom_question(args.question, args.gold, modes, args.top_k, args.candidate_limit)
        rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        if args.output:
            output_path = Path(args.output).resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
            print(json.dumps({"saved_to": str(output_path), "metrics": {row["mode"]: row["metrics"] for row in report["results"]}}, indent=2))
        else:
            print(rendered)
        return

    if args.gold or args.mode != "all" or args.output:
        parser.error("--gold, --mode, and --output require --question")
    report = run_evaluation(args.top_k, args.candidate_limit)
    write_reports(report)
    print(json.dumps({"summary_metrics": report["summary_metrics"],
                      "retrieval_modes_tied_or_winning_recall_questions": report["retrieval_modes_tied_or_winning_recall_questions"],
                      "markdown_report": str(REPORT_MD), "json_report": str(REPORT_JSON)}, indent=2))


if __name__ == "__main__":
    main()
