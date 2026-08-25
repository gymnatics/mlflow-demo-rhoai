#!/usr/bin/env python3
"""
RAGAS Benchmark Evaluation via EvalHub against test dataset with ground truth.

Runs each question through the RAG pipeline, then submits the dataset to
EvalHub's RAGAS adapter (ragas_rag_full benchmark) for evaluation with all
available RAGAS metrics using the expected_answer as reference.

Usage:
    python ragas_eval.py                          # Default prompt v1
    python ragas_eval.py -p 2                     # Prompt v2
    python ragas_eval.py -d custom_dataset.json   # Custom dataset
"""

import sys
import os
import json
import argparse
import time
import logging
import tempfile

_this_dir = os.path.dirname(os.path.abspath(__file__))
RAG_APP_DIR = (
    _this_dir
    if os.path.exists(os.path.join(_this_dir, "rag_pipeline.py"))
    else os.path.join(_this_dir, "..", "rag-app")
)
sys.path.insert(0, RAG_APP_DIR)

os.environ.setdefault("OPENAI_API_KEY", os.environ.get("LLM_API_KEY", "unused"))
os.environ.setdefault("OPENAI_TIMEOUT", "120")

import mlflow
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


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


def run_benchmark(
    prompt_version: int = 1,
    test_data: list[dict] | None = None,
    dataset_path: str | None = None,
):
    from rag_pipeline import RAGPipeline
    from evalhub import SyncEvalHubClient, JobSubmissionRequest, ModelConfig, BenchmarkConfig
    from evalhub.models.api import TestDataRef, S3TestDataRef
    import boto3

    if test_data is None:
        test_data = load_test_dataset(dataset_path)

    logger.info("=== RAGAS Benchmark Evaluation (via EvalHub) ===")
    logger.info("  Prompt version : %d", prompt_version)
    logger.info("  Test questions : %d", len(test_data))
    logger.info("  Judge endpoint : %s", config.LLM_JUDGE_ENDPOINT)

    mlflow.set_tracking_uri(config.MLFLOW_TRACKING_URI)
    if config.MLFLOW_WORKSPACE:
        mlflow.set_workspace(config.MLFLOW_WORKSPACE)
    mlflow.set_experiment(config.MLFLOW_EXPERIMENT_NAME)

    pipeline = RAGPipeline(prompt_version=prompt_version)
    logger.info("Building vector index...")
    pipeline.build_index()

    samples = []
    for i, item in enumerate(test_data):
        question = item["question"]
        expected = item.get("expected_answer", "")
        logger.info("[%d/%d] %s", i + 1, len(test_data), question[:80])

        try:
            result = pipeline.query(question)
        except Exception as e:
            logger.error("Query failed for '%s': %s", question[:40], e)
            continue

        if isinstance(result, dict):
            response = result.get("answer", str(result))
            chunks = result.get("context_chunks", [])
            contexts = []
            if isinstance(chunks, list):
                for c in chunks:
                    if isinstance(c, dict):
                        contexts.append(str(c.get("content", ""))[:1000])
                    else:
                        contexts.append(str(c)[:1000])
        else:
            response = str(result)
            contexts = []

        if not contexts:
            contexts = ["No context retrieved."]

        samples.append({
            "user_input": question,
            "response": response,
            "retrieved_contexts": contexts,
            "reference": expected,
        })

    if not samples:
        logger.error("No valid samples generated. Aborting.")
        return

    logger.info("All %d queries complete. Submitting to EvalHub RAGAS...", len(samples))

    dataset_file = os.path.join(tempfile.mkdtemp(), "ragas_benchmark.jsonl")
    with open(dataset_file, "w") as df:
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
    s3_key = f"ragas-benchmark/v{prompt_version}-{int(time.time())}.jsonl"
    s3.upload_file(dataset_file, bucket, s3_key)
    s3_uri = f"s3://{bucket}/{s3_key}"
    logger.info("Uploaded %d samples to %s", len(samples), s3_uri)

    judge_url = config.LLM_JUDGE_ENDPOINT.rstrip("/")
    if not judge_url.endswith("/v1"):
        judge_url += "/v1"

    evalhub_url = os.environ.get(
        "EVALHUB_URL", "https://evalhub.redhat-ods-applications.svc:8443"
    )
    evalhub_tenant = os.environ.get("EVALHUB_TENANT", os.environ.get("NAMESPACE", "gov-rag-poc"))

    sa_token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    with SyncEvalHubClient(
        base_url=evalhub_url,
        tenant=evalhub_tenant,
        verify_ssl=False,
        auth_token_path=sa_token_path if os.path.exists(sa_token_path) else None,
    ) as eh_client:
        s3_secret = os.environ.get("EVALHUB_S3_SECRET", "pipelines-s3-credentials")
        job = eh_client.jobs.submit(JobSubmissionRequest(
            name=f"ragas-benchmark-v{prompt_version}-{int(time.time())}",
            model=ModelConfig(url=judge_url, name=config.LLM_MODEL),
            benchmarks=[BenchmarkConfig(
                id="ragas_rag_full",
                provider_id="ragas",
                parameters={
                    "embedding_model": "all-MiniLM-L6-v2",
                    "max_tokens": 1024,
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
        logger.info("EvalHub RAGAS benchmark job submitted: %s", job_id)

        result = eh_client.jobs.wait_for_completion(job_id, timeout=1800)

    job_status = result.status.state if hasattr(result.status, "state") else result.status
    logger.info("EvalHub RAGAS benchmark job status: %s", job_status)
    if str(job_status) not in ("completed", "JobStatus.COMPLETED"):
        logger.error("EvalHub job ended with status: %s", job_status)
        return

    aggregate = {}
    per_sample = []
    bench_list = result.results
    if hasattr(result.results, "benchmarks"):
        bench_list = result.results.benchmarks or []
    elif not isinstance(result.results, list):
        bench_list = []
    for bench_result in bench_list:
        if hasattr(bench_result, "metrics") and bench_result.metrics:
            for metric_result in bench_result.metrics:
                if isinstance(metric_result, dict):
                    aggregate[metric_result["name"]] = metric_result.get("score", 0.0)
                else:
                    aggregate[getattr(metric_result, "name", "")] = getattr(metric_result, "score", 0.0)
        if hasattr(bench_result, "per_sample_results") and bench_result.per_sample_results:
            per_sample = bench_result.per_sample_results
        elif hasattr(bench_result, "samples") and bench_result.samples:
            per_sample = bench_result.samples

    avg_faithfulness = aggregate.get("faithfulness", 0.0)
    avg_answer_relevancy = aggregate.get("answer_relevancy", 0.0)
    avg_context_precision = aggregate.get("context_precision", 0.0)
    avg_context_recall = aggregate.get("context_recall", 0.0)
    avg_factual_correctness = aggregate.get("factual_correctness", 0.0)

    benchmark_run_id = f"ragas-benchmark-v{prompt_version}-{time.strftime('%Y%m%d-%H%M%S')}"

    with mlflow.start_run(run_name=benchmark_run_id):
        mlflow.set_tag("eval_type", "ragas_benchmark")
        mlflow.set_tag("eval_source", "evalhub")
        mlflow.set_tag("evalhub_job_id", job_id)
        mlflow.set_tag("prompt_version", str(prompt_version))
        mlflow.set_tag("model_name", config.LLM_MODEL)
        mlflow.set_tag("num_questions", str(len(samples)))
        mlflow.set_tag("has_ground_truth", "true")

        mlflow.log_metric("avg_faithfulness", round(avg_faithfulness, 4))
        mlflow.log_metric("avg_answer_relevancy", round(avg_answer_relevancy, 4))
        mlflow.log_metric("avg_context_precision", round(avg_context_precision, 4))
        mlflow.log_metric("avg_context_recall", round(avg_context_recall, 4))
        mlflow.log_metric("avg_factual_correctness", round(avg_factual_correctness, 4))
        mlflow.log_metric("avg_groundedness", round(avg_faithfulness, 4))
        mlflow.log_metric("hallucination_rate", round(1.0 - avg_faithfulness, 4))

        def _get_score(row, key, default=0):
            if isinstance(row, dict):
                return float(row.get(key, default) or default)
            return float(getattr(row, key, default) or default)

        per_question = []
        for i, sample in enumerate(samples):
            row = per_sample[i] if i < len(per_sample) else {}
            per_question.append({
                "question": sample["user_input"],
                "expected_answer": sample.get("reference", ""),
                "actual_answer": sample["response"],
                "faithfulness": _get_score(row, "faithfulness"),
                "answer_relevancy": _get_score(row, "answer_relevancy"),
                "context_precision": _get_score(row, "context_precision"),
                "context_recall": _get_score(row, "context_recall"),
                "factual_correctness": _get_score(row, "factual_correctness"),
            })

        mlflow.log_text(json.dumps({
            "benchmark_run_id": benchmark_run_id,
            "evalhub_job_id": job_id,
            "prompt_version": prompt_version,
            "model": config.LLM_MODEL,
            "questions_evaluated": len(samples),
            "aggregate_metrics": {
                "avg_faithfulness": avg_faithfulness,
                "avg_answer_relevancy": avg_answer_relevancy,
                "avg_context_precision": avg_context_precision,
                "avg_context_recall": avg_context_recall,
                "avg_factual_correctness": avg_factual_correctness,
            },
            "per_question_results": per_question,
        }, indent=2), "ragas_benchmark_results.json")

    print()
    print("=" * 70)
    print("  RAGAS BENCHMARK COMPLETE (via EvalHub)")
    print("=" * 70)
    print(f"  EvalHub Job ID        : {job_id}")
    print(f"  Prompt version        : v{prompt_version}")
    print(f"  Questions evaluated   : {len(samples)}")
    print(f"  Model                 : {config.LLM_MODEL}")
    print()
    print(f"  Faithfulness          : {avg_faithfulness:.3f}")
    print(f"  Answer Relevancy      : {avg_answer_relevancy:.3f}")
    print(f"  Context Precision     : {avg_context_precision:.3f}")
    print(f"  Context Recall        : {avg_context_recall:.3f}")
    print(f"  Factual Correctness   : {avg_factual_correctness:.3f}")
    print()
    print(f"  Results logged to MLflow run: {benchmark_run_id}")
    print("=" * 70)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="RAGAS Benchmark via EvalHub: full test-dataset evaluation with ground truth",
    )
    parser.add_argument(
        "--prompt-version", "-p", type=int, default=1,
        help="Prompt version to evaluate (default: 1)",
    )
    parser.add_argument(
        "--dataset", "-d", type=str, default=None,
        help="Path to test dataset JSON (default: eval/test_dataset.json)",
    )
    args = parser.parse_args()

    run_benchmark(
        prompt_version=args.prompt_version,
        dataset_path=args.dataset,
    )


if __name__ == "__main__":
    main()
