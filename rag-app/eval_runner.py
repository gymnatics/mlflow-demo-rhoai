#!/usr/bin/env python3
"""
Evaluation runner using MLflow-native scorers on traces.

Two-phase approach (matching MLFlow-Agent-Observability-Demo pattern):
  Phase 1: Generate traces by running RAG pipeline, tagged with an eval_run_id
  Phase 2: Search traces by that tag and evaluate only those traces

Assessments attach directly to traces -- visible in MLflow UI via "Show assessments".

Usage:
  python eval_runner.py -p 1               # Generate + evaluate prompt v1
  python eval_runner.py -p 1 -p 2          # Generate both + evaluate each set
  python eval_runner.py --evaluate-only --eval-run-id <id>  # Re-evaluate a previous run
"""

import sys
import os
import json
import argparse
import time
import logging
import uuid
from textwrap import dedent

_this_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(_this_dir, "rag_pipeline.py")):
    RAG_APP_DIR = _this_dir
else:
    RAG_APP_DIR = os.path.join(_this_dir, "..", "rag-app")
sys.path.insert(0, RAG_APP_DIR)

os.environ.setdefault("OPENAI_API_KEY", os.environ.get("LLM_API_KEY", "unused"))
os.environ.setdefault("OPENAI_TIMEOUT", "120")

import mlflow
from mlflow.genai import make_judge
from mlflow.genai.scorers import scorer
from mlflow.entities import Feedback

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

EVAL_EXPERIMENT = config.MLFLOW_EXPERIMENT_NAME


def _judge_base_url() -> str:
    base = config.LLM_JUDGE_ENDPOINT.rstrip("/")
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base


def _judge_model() -> str:
    return f"openai:/{config.LLM_MODEL}"


# ---------------------------------------------------------------------------
# LLM-based judges (make_judge)
# ---------------------------------------------------------------------------

def build_relevance_judge():
    return make_judge(
        name="relevance",
        model=_judge_model(),
        base_url=_judge_base_url(),
        instructions=(
            "Evaluate whether the agent's response is relevant to the user's query "
            "about the organization's policy.\n\n"
            "Query: {{ inputs }}\n"
            "Response: {{ outputs }}\n\n"
            "Answer 'yes' if the response addresses the query, 'no' if it does not."
        ),
    )


@scorer
def groundedness_check(inputs, outputs):
    """Check if the response is grounded in retrieved context (uses raw HTTP to avoid autolog loops)."""
    import requests as _req
    answer = outputs.get("answer", str(outputs)) if isinstance(outputs, dict) else str(outputs)
    context = ""
    if isinstance(outputs, dict):
        chunks = outputs.get("context_chunks", [])
        if isinstance(chunks, list):
            context = "\n".join(
                c.get("content", "")[:500] for c in chunks if isinstance(c, dict)
            )
    if not context:
        return Feedback(name="groundedness", value="grounded", rationale="No context to check against.")

    base = config.LLM_JUDGE_ENDPOINT
    url = base + "/chat/completions" if base.endswith("/v1") else base
    try:
        resp = _req.post(url, json={
            "model": config.LLM_MODEL,
            "messages": [{"role": "user", "content": (
                "Is this answer grounded in the context? Answer only 'yes' or 'no'.\n\n"
                f"Context: {context[:2000]}\n\nAnswer: {answer[:1000]}"
            )}],
            "temperature": 0.0, "max_tokens": 10,
        }, timeout=90, verify=False)
        text = resp.json()["choices"][0]["message"]["content"].strip().lower()
    except Exception as e:
        return Feedback(name="groundedness", value="error", rationale=str(e)[:200])

    grounded = text.startswith("yes")
    return Feedback(name="groundedness", value="grounded" if grounded else "not_grounded", rationale=text)


def build_faithfulness_judge():
    return make_judge(
        name="faithfulness",
        model=_judge_model(),
        base_url=_judge_base_url(),
        instructions=(
            "You are a faithfulness evaluator for a banking policy Q&A system. "
            "Evaluate whether the response sticks to answering from provided policy "
            "documents without adding speculation or outside knowledge.\n\n"
            "Response: {{ outputs }}\n\n"
            "Answer 'yes' if the response is faithful and does not fabricate, "
            "'no' if it adds unsupported information."
        ),
    )


# ---------------------------------------------------------------------------
# Code-based scorers (no LLM needed)
# ---------------------------------------------------------------------------

@scorer
def policy_language_check(inputs, outputs, trace):
    """Check that the response references policy-specific language."""
    response_text = outputs if isinstance(outputs, str) else str(outputs)
    default_terms = "policy,section,lvr,kyc,aml,cdd,compliance,regulatory,retention,restricted,confidential"
    policy_terms = os.environ.get("POLICY_TERMS", default_terms).split(",")
    found = [t for t in policy_terms if t in response_text.lower()]
    return Feedback(
        name="policy_language",
        value="yes" if found else "no",
        rationale=(
            f"Response contains policy terms: {', '.join(found)}."
            if found
            else "Response lacks policy-specific language."
        ),
    )


@scorer
def latency_budget_check(inputs, outputs, trace):
    """Check whether trace stayed within 10-second SLA."""
    if trace and trace.info and trace.info.execution_time_ms is not None:
        within = trace.info.execution_time_ms < 10_000
        return Feedback(
            name="latency_sla",
            value="pass" if within else "fail",
            rationale=(
                f"Execution took {trace.info.execution_time_ms}ms "
                f"({'within' if within else 'exceeds'} 10s SLA)."
            ),
        )
    return Feedback(name="latency_sla", value="unknown", rationale="No execution time data.")


# ---------------------------------------------------------------------------
# Phase 1: Generate traces (tagged with eval_run_id)
# ---------------------------------------------------------------------------

def load_test_dataset(path: str | None = None) -> list[dict]:
    if path is None:
        candidates = [
            os.path.join(_this_dir, "test_dataset.json"),
            os.path.join(_this_dir, "..", "eval", "test_dataset.json"),
        ]
        for c in candidates:
            if os.path.exists(c):
                path = c
                break
        else:
            path = candidates[0]
    with open(path) as f:
        return json.load(f)


@mlflow.trace(name="eval_query")
def _run_tagged_query(pipeline, question: str, eval_run_id: str, prompt_version: str):
    """Wrapper that tags each trace with eval_run_id for later filtering."""
    mlflow.update_current_trace(
        metadata={
            "eval_run_id": eval_run_id,
            "eval_prompt_version": prompt_version,
        },
    )
    return pipeline.query(question)


def generate_traces(
    prompt_version: int,
    test_data: list[dict],
    eval_run_id: str,
):
    """Run RAG pipeline on test questions, tagging each trace with eval_run_id."""
    from rag_pipeline import RAGPipeline

    logger.info("--- Phase 1: Generating Traces ---")
    logger.info("  Prompt version : %d", prompt_version)
    logger.info("  Eval run ID    : %s", eval_run_id)
    logger.info("  Test questions : %d", len(test_data))

    mlflow.set_experiment(EVAL_EXPERIMENT)

    pipeline = RAGPipeline(prompt_version=prompt_version)
    logger.info("Building vector index...")
    pipeline.build_index()

    for i, item in enumerate(test_data):
        q = item["question"]
        logger.info("[%d/%d] %s", i + 1, len(test_data), q[:80])
        _run_tagged_query(pipeline, q, eval_run_id, str(prompt_version))

    logger.info("All %d queries complete. Flushing traces...", len(test_data))
    time.sleep(3)


# ---------------------------------------------------------------------------
# Phase 2: Evaluate traces (filtered by eval_run_id)
# ---------------------------------------------------------------------------

def evaluate_traces(
    experiment_name: str,
    eval_run_id: str | None = None,
    max_traces: int = 100,
    extra_filter: str | None = None,
):
    """Search traces (optionally filtered by eval_run_id) and run scorers."""
    logger.info("--- Phase 2: Evaluating Traces ---")

    exp = mlflow.get_experiment_by_name(experiment_name)
    if exp is None:
        logger.error("Experiment '%s' not found!", experiment_name)
        return None

    cutoff_ms = int((time.time() - 24 * 3600) * 1000)
    filters = [
        "tags.`mlflow.traceName` RLIKE '(rag_query|eval_query)'",
        f"timestamp_ms > {cutoff_ms}",
    ]
    if eval_run_id:
        filters.append(f"metadata.`eval_run_id` = '{eval_run_id}'")
        logger.info("Filtering by eval_run_id='%s'", eval_run_id)
    if extra_filter:
        filters.append(extra_filter)
        logger.info("Extra filter: %s", extra_filter)

    filter_str = " AND ".join(filters)
    logger.info("Trace filter: %s", filter_str)

    traces = mlflow.search_traces(
        experiment_ids=[exp.experiment_id],
        filter_string=filter_str,
        max_results=max_traces,
    )

    if traces.empty:
        logger.warning("No traces found matching the filter.")
        return None

    logger.info("Found %d traces. Running scorers ...", len(traces))
    logger.info("Judge model: %s -> %s", _judge_model(), _judge_base_url())

    mlflow.set_experiment(experiment_name)

    results = mlflow.genai.evaluate(
        data=traces,
        scorers=[
            build_relevance_judge(),
            groundedness_check,
            policy_language_check,
            latency_budget_check,
        ],
    )

    logger.info("Evaluation complete.")
    if hasattr(results, "metrics") and results.metrics:
        logger.info("Metrics: %s", results.metrics)

    print()
    print("=" * 70)
    print("  EVALUATION COMPLETE")
    print("=" * 70)
    print(f"  Eval run ID      : {eval_run_id or 'ALL'}")
    print(f"  Traces evaluated : {len(traces)}")
    print(f"  Experiment       : {experiment_name}")
    print()
    print("  Assessments are now attached to each trace.")
    print("  Open a trace in MLflow UI -> click 'Show assessments' to see scores.")
    print("=" * 70)
    print()

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="RAG Evaluation Runner -- MLflow-native scorers on traces",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            Examples:
              %(prog)s -p 1                              # Generate + evaluate v1
              %(prog)s -p 2                              # Generate + evaluate v2
              %(prog)s -p 1 -p 2                         # Generate both, evaluate each
              %(prog)s --evaluate-only                    # Evaluate ALL existing traces
              %(prog)s --evaluate-only --eval-run-id ID   # Re-evaluate a specific run
        """),
    )
    parser.add_argument(
        "--prompt-version", "-p",
        type=int,
        action="append",
        dest="prompt_versions",
        help="Prompt version(s) to generate traces for",
    )
    parser.add_argument(
        "--evaluate-only",
        action="store_true",
        help="Skip trace generation, evaluate existing traces",
    )
    parser.add_argument(
        "--unassessed-only",
        action="store_true",
        help="Only evaluate traces that have no assessments yet",
    )
    parser.add_argument(
        "--eval-run-id",
        type=str,
        default=None,
        help="Evaluate only traces with this eval_run_id (use with --evaluate-only)",
    )
    parser.add_argument(
        "--dataset", "-d",
        type=str,
        default=None,
        help="Path to test dataset JSON (default: eval/test_dataset.json)",
    )
    parser.add_argument(
        "--max-traces",
        type=int,
        default=100,
        help="Max traces to evaluate (default: 100)",
    )
    args = parser.parse_args()

    mlflow.set_tracking_uri(config.MLFLOW_TRACKING_URI)
    if config.MLFLOW_WORKSPACE:
        mlflow.set_workspace(config.MLFLOW_WORKSPACE)

    if args.evaluate_only:
        extra_filter = "assessments IS NULL" if args.unassessed_only else None
        evaluate_traces(
            EVAL_EXPERIMENT,
            eval_run_id=args.eval_run_id,
            max_traces=args.max_traces,
            extra_filter=extra_filter,
        )
    else:
        if not args.prompt_versions:
            parser.error("Specify --prompt-version or use --evaluate-only")

        test_data = load_test_dataset(args.dataset)

        for pv in args.prompt_versions:
            eval_run_id = f"eval-v{pv}-{time.strftime('%Y%m%d-%H%M%S')}"
            generate_traces(prompt_version=pv, test_data=test_data, eval_run_id=eval_run_id)
            evaluate_traces(EVAL_EXPERIMENT, eval_run_id=eval_run_id, max_traces=args.max_traces)


if __name__ == "__main__":
    main()
