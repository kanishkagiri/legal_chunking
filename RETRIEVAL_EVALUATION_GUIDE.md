# Retrieval evaluation: how to measure a question

## What the evaluator measures

`evaluate_retrieval.py` runs the query through the existing keyword, vector, or graph retrieval mode, sends the candidates through the shared local reranker, and scores the reranked citations against citations you mark as relevant (the **gold citations**).

It measures retrieval quality only. It does not generate an SLM answer or measure answer accuracy, hallucinations, or citation faithfulness.

## Evaluate any new question

Open PowerShell in the project directory. Give the question and every provision citation that would count as a relevant result:

```powershell
.venv\Scripts\python.exe evaluate_retrieval.py --question "What procedure applies when testing goods for a defect?" --gold "Section 38(2)" --gold "Section 38(5)"
```

By default, the tool compares all three modes. It prints the gold citations, top‑k results, and metrics for each mode. Save a reusable JSON result with `--output`:

```powershell
.venv\Scripts\python.exe evaluate_retrieval.py --question "What procedure applies when testing goods for a defect?" --gold "Section 38(2)" --gold "Section 38(5)" --output parsed_output\my_question_metrics.json
```

To run only one mode, add `--mode keyword`, `--mode vector`, or `--mode graph`. To change the reranked context size, add `--top-k 3`; the candidate pool defaults to 25 and can be changed with `--candidate-limit 40`.

The tool requires Neo4j credentials in `.env`, the existing Neo4j indexes, the downloaded `BAAI/bge-small-en-v1.5` embedding model, and the FastEmbed cross-encoder reranker. The query analyzer is deterministic and requires no model API key.

## Run the original nine-question comparison

With no arguments, the script runs the nine labeled examples and rewrites:

- `retrieval_comparison.md` — readable summary and rankings.
- `parsed_output/retrieval_comparison.json` — full result objects, including the retrieved text and source metadata.

```powershell
.venv\Scripts\python.exe evaluate_retrieval.py
```

To make a new question part of that repeatable benchmark, add it to `QUESTIONS` in `evaluate_retrieval.py` with a unique `id`, query, all gold citations, and a short reason. Then rerun the command above. A one-off `--question` run does not modify the nine-question benchmark.

## Metrics and how to read them

The evaluator compares citations, not node IDs. Multiple passage results that point to the same citation count once. Citation matching ignores letter case and whitespace, but otherwise expects the citation to match (for example, `Section 38 (2)` matches `Section 38(2)`).

For a cutoff of `K`:

- **Precision@K** = relevant citations in the top K ÷ K. The denominator stays K, even if fewer than K results are returned.
- **Recall@K** = relevant gold citations found in the top K ÷ all supplied gold citations.
- **MRR@K** = 1 ÷ the rank of the first gold citation; zero if none appear.
- **nDCG@K** = discounted cumulative gain of the relevant citations ÷ the ideal discounted gain. It rewards finding more gold citations and ranking them higher.
- **Hit@K** = 1 if at least one gold citation appears in the top K, otherwise 0.

### Small example

Suppose the gold citations are `Section 38(2)` and `Section 38(5)`, K is 5, and the returned citation list is:

1. Section 38(1)
2. Section 38(2)
3. Section 38(5)
4. Section 39(1)
5. Section 42

Then Precision@5 = 2/5 = **0.40**, Recall@5 = 2/2 = **1.00**, MRR@5 = 1/2 = **0.50**, and Hit@5 = **1.00**. For nDCG@5, DCG = 1/log₂(3) + 1/log₂(4) ≈ 1.131; ideal DCG = 1 + 1/log₂(3) ≈ 1.631; nDCG@5 ≈ **0.69**.

## Labeling guidance

Metrics are only as reliable as the gold citations. Include every citation needed to answer the retrieval task, including multiple provisions when the question asks for a procedure plus an exception or cross-reference. If you are unsure which citations are relevant, review the Act text first and mark the question as uncertain instead of treating one guessed citation as definitive. Keep this same gold set when comparing modes.

The three retrieval modes use the same deterministic question processing and reranker. This helps isolate the effect of retrieval mode. The evaluation's manually selected nine questions are a small development sample, not a statistically representative legal benchmark.
