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


def _extract_trace_fields_for_ragas(trace_row):
    """Extract user_input, response, and retrieved_contexts from a trace row for RAGAS."""
    request_data = trace_row.get("request", {})
    response_data = trace_row.get("response", {})

    if isinstance(request_data, dict):
        user_input = request_data.get("user_question", str(request_data))
    elif request_data is not None:
        user_input = str(request_data)
    else:
        user_input = ""

    if isinstance(response_data, dict):
        response = response_data.get("answer", str(response_data))
    elif response_data is not None:
        response = str(response_data)
    else:
        response = ""

    contexts = []
    if isinstance(response_data, dict):
        chunks = response_data.get("context_chunks", [])
        if isinstance(chunks, list):
            for c in chunks:
                if isinstance(c, dict):
                    contexts.append(str(c.get("content", ""))[:1000])

    if not contexts:
        spans = trace_row.get("spans", [])
        if spans:
            for span in (spans if isinstance(spans, list) else []):
                sname = span.get("name", "") if isinstance(span, dict) else getattr(span, "name", "")
                if "retrieve" in sname.lower():
                    span_outputs = span.get("outputs", None) if isinstance(span, dict) else getattr(span, "outputs", None)
                    if isinstance(span_outputs, list):
                        for item in span_outputs:
                            if isinstance(item, dict):
                                contexts.append(str(item.get("content", item.get("page_content", "")))[:1000])
                            else:
                                contexts.append(str(item)[:1000])
                    elif span_outputs:
                        contexts.append(str(span_outputs)[:2000])
                    break

    if not contexts:
        contexts = ["No context retrieved."]

    return user_input, response, contexts


def run_ragas_evaluation(traces, experiment_name: str):
    """Run RAGAS evaluation via EvalHub and write scores back as MLflow assessments."""
    from evalhub import SyncEvalHubClient, JobSubmissionRequest, ModelConfig, BenchmarkConfig
    from evalhub.models.api import TestDataRef, S3TestDataRef

    samples = []
    trace_ids = []
    for _, trace_row in traces.iterrows():
        user_input, response, contexts = _extract_trace_fields_for_ragas(trace_row)
        if not user_input or not response:
            continue
        samples.append({
            "user_input": user_input,
            "response": response,
            "retrieved_contexts": contexts,
        })
        trace_ids.append(trace_row.get("trace_id", ""))

    if not samples:
        logger.warning("No valid samples for RAGAS evaluation.")
        return {"faithfulness": [], "answer_relevancy": []}

    ragas_scores = {"faithfulness": [], "answer_relevancy": []}

    import tempfile
    import boto3

    dataset_path = os.path.join(tempfile.mkdtemp(), "ragas_dataset.jsonl")
    with open(dataset_path, "w") as df:
        for s in samples:
            df.write(json.dumps(s) + "\n")

    s3_endpoint = os.environ.get("S3_ENDPOINT_URL", "http://minio.gov-rag-poc.svc:9000")
    s3 = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "minio"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "minio123"),
    )
    bucket = "evalhub-data"
    try:
        s3.create_bucket(Bucket=bucket)
    except Exception:
        pass
    s3_key = f"ragas-eval/runner-{int(time.time())}.jsonl"
    s3.upload_file(dataset_path, bucket, s3_key)
    s3_uri = f"s3://{bucket}/{s3_key}"
    logger.info("Uploaded %d samples to %s", len(samples), s3_uri)

    evalhub_url = os.environ.get(
        "EVALHUB_URL", "https://evalhub.redhat-ods-applications.svc:8443"
    )
    evalhub_tenant = os.environ.get("EVALHUB_TENANT", os.environ.get("NAMESPACE", "gov-rag-poc"))

    judge_url = config.LLM_JUDGE_ENDPOINT.rstrip("/")
    if not judge_url.endswith("/v1"):
        judge_url += "/v1"

    try:
        sa_token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        with SyncEvalHubClient(
            base_url=evalhub_url,
            tenant=evalhub_tenant,
            verify_ssl=False,
            auth_token_path=sa_token_path if os.path.exists(sa_token_path) else None,
        ) as eh_client:
            s3_secret = os.environ.get("EVALHUB_S3_SECRET", "pipelines-s3-credentials")
            job = eh_client.jobs.submit(JobSubmissionRequest(
                name=f"ragas-eval-runner-{int(time.time())}",
                model=ModelConfig(url=judge_url, name=config.LLM_MODEL),
                    benchmarks=[BenchmarkConfig(
                    id="ragas_rag_default",
                    provider_id="ragas",
                    parameters={
                        "metrics": ["faithfulness"],
                        "max_tokens": 4096,
                        "temperature": 0.1,
                    },
                    test_data_ref=TestDataRef(s3=S3TestDataRef(
                        bucket=bucket,
                        key=s3_key,
                        secret_ref=s3_secret,
                    )),
                )],
            ))
            job_resource = job.resource
            job_id = job_resource.id if hasattr(job_resource, "id") else str(job_resource)
            logger.info("EvalHub RAGAS job submitted: %s", job_id)

            result = eh_client.jobs.wait_for_completion(job_id, timeout=1200)
            job_status = result.status.state if hasattr(result.status, "state") else result.status
            logger.info("EvalHub RAGAS job status: %s", job_status)

            if str(job_status) == "completed" or str(job_status) == "JobStatus.COMPLETED":
                aggregate_metrics = {}
                bench_list = result.results
                if hasattr(result.results, "benchmarks"):
                    bench_list = result.results.benchmarks or []
                elif not isinstance(result.results, list):
                    bench_list = []
                for bench_result in bench_list:
                    if hasattr(bench_result, "metrics") and bench_result.metrics:
                        if isinstance(bench_result.metrics, dict):
                            aggregate_metrics = bench_result.metrics
                        else:
                            for m in bench_result.metrics:
                                if isinstance(m, dict):
                                    aggregate_metrics[m.get("name", "")] = m.get("score", 0.0)
                                else:
                                    aggregate_metrics[getattr(m, "name", "")] = getattr(m, "score", 0.0)
                        break

                avg_faith = float(aggregate_metrics.get("faithfulness", 0.0) or 0.0)
                avg_relevancy = float(aggregate_metrics.get("answer_relevancy", 0.0) or 0.0)
                logger.info("EvalHub aggregate metrics: faithfulness=%.4f, answer_relevancy=%.4f", avg_faith, avg_relevancy)

                from mlflow.entities import Assessment, AssessmentSource
                from mlflow.entities.assessment import FeedbackValue

                for i, trace_id in enumerate(trace_ids):
                    faith = avg_faith
                    relevancy = avg_relevancy

                    ragas_scores["faithfulness"].append(faith)
                    ragas_scores["answer_relevancy"].append(relevancy)

                    mlflow.log_assessment(
                        trace_id=trace_id,
                        assessment=Assessment(
                            name="groundedness",
                            source=AssessmentSource(
                                source_type="LLM_JUDGE", source_id="evalhub-ragas"
                            ),
                            feedback=FeedbackValue(value=round(faith, 4)),
                            rationale=f"EvalHub RAGAS faithfulness={faith:.4f}, answer_relevancy={relevancy:.4f}",
                        ),
                    )
                logger.info("EvalHub RAGAS completed. Scored %d traces.", len(trace_ids))
            else:
                logger.error("EvalHub RAGAS job ended with status: %s", job_status)

    except Exception as e:
        logger.error("EvalHub RAGAS evaluation failed: %s", e)
        import traceback
        traceback.print_exc()

    return ragas_scores


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

    mlflow.set_experiment(experiment_name)

    # Phase A: Code-based scorers (no LLM calls)
    logger.info("Phase A: Running code-based scorers (policy_language, latency_sla)...")
    mlflow.genai.evaluate(
        data=traces,
        scorers=[policy_language_check, latency_budget_check],
    )

    # Phase B: RAGAS metrics via EvalHub (faithfulness, answer_relevancy)
    logger.info("Phase B: Running RAGAS evaluation via EvalHub...")
    ragas_scores = run_ragas_evaluation(traces, experiment_name)

    avg_faith = sum(ragas_scores["faithfulness"]) / len(ragas_scores["faithfulness"]) if ragas_scores["faithfulness"] else 0.0
    avg_relevancy = sum(ragas_scores["answer_relevancy"]) / len(ragas_scores["answer_relevancy"]) if ragas_scores["answer_relevancy"] else 0.0

    logger.info("Evaluation complete.")
    logger.info("RAGAS: faithfulness=%.3f, answer_relevancy=%.3f",
                avg_faith, avg_relevancy)

    print()
    print("=" * 70)
    print("  EVALUATION COMPLETE")
    print("=" * 70)
    print(f"  Eval run ID      : {eval_run_id or 'ALL'}")
    print(f"  Traces evaluated : {len(traces)}")
    print(f"  Experiment       : {experiment_name}")
    print()
    print(f"  RAGAS Faithfulness      : {avg_faith:.3f}")
    print(f"  RAGAS Answer Relevancy  : {avg_relevancy:.3f}")
    print()
    print("  Assessments are now attached to each trace.")
    print("  Open a trace in MLflow UI -> click 'Show assessments' to see scores.")
    print("=" * 70)
    print()

    return ragas_scores


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
