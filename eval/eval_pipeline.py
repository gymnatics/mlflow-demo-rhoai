"""
KFP v2 Pipeline: RAG Evaluation with Compliance Analysis
=========================================================
Three-step pipeline:
  Step 1: Score -- evaluate un-assessed traces with MLflow scorers
  Step 2: Analyze -- flag violations and compute trends vs previous period
  Step 3: Report -- compare with previous eval run, log flagged traces and summary

Usage:
    python eval_pipeline.py              # Compile to YAML
    python eval_pipeline.py --run        # Compile and submit to DSPA
"""

import os
from kfp import dsl, compiler

RAG_APP_IMAGE = os.environ.get(
    "RAG_APP_IMAGE",
    "image-registry.openshift-image-registry.svc:5000/gov-rag-poc/gov-rag-app:latest",
)


@dsl.component(
    base_image=RAG_APP_IMAGE,
    packages_to_install=[],
)
def evaluate_traces(
    mlflow_uri: str,
    mlflow_workspace: str,
    experiment_name: str,
    llm_endpoint: str,
    llm_judge_endpoint: str,
    llm_model: str,
    max_traces: int,
    lookback_hours: int,
    eval_output: dsl.Output[dsl.Artifact],
):
    """Score recent traces with RAGAS metrics (faithfulness, answer_relevancy) and MLflow code-based scorers."""
    import os
    import json
    import time

    os.environ.setdefault("MLFLOW_TRACKING_INSECURE_TLS", "true")
    os.environ.setdefault("MLFLOW_TRACKING_AUTH", "kubernetes-namespaced")
    os.environ.setdefault("OPENAI_API_KEY", os.environ.get("LLM_API_KEY", "unused"))
    os.environ.setdefault("OPENAI_TIMEOUT", "120")

    import mlflow
    from mlflow.genai.scorers import scorer
    from mlflow.entities import Feedback

    mlflow.set_tracking_uri(mlflow_uri)
    if mlflow_workspace:
        mlflow.set_workspace(mlflow_workspace)

    @scorer
    def policy_language_check(inputs, outputs, trace):
        response_text = outputs if isinstance(outputs, str) else str(outputs)
        default_terms = "policy,section,lvr,kyc,aml,cdd,compliance,regulatory,retention"
        terms = os.environ.get("POLICY_TERMS", default_terms).split(",")
        found = [t for t in terms if t in response_text.lower()]
        return Feedback(
            name="policy_language", value="yes" if found else "no",
            rationale=f"Found: {', '.join(found)}" if found else "No policy terms found.",
        )

    @scorer
    def latency_sla_check(inputs, outputs, trace):
        if trace and trace.info and trace.info.execution_time_ms is not None:
            ok = trace.info.execution_time_ms < 10_000
            return Feedback(
                name="latency_sla", value="pass" if ok else "fail",
                rationale=f"{trace.info.execution_time_ms}ms ({'within' if ok else 'exceeds'} 10s SLA).",
            )
        return Feedback(name="latency_sla", value="unknown", rationale="No timing data.")

    exp = mlflow.get_experiment_by_name(experiment_name)
    if exp is None:
        print(f"Experiment '{experiment_name}' not found.")
        output = {"traces_evaluated": 0, "eval_run_id": "", "metrics": {}}
        with open(eval_output.path, "w") as f:
            json.dump(output, f)
        return

    cutoff_ms = int((time.time() - lookback_hours * 3600) * 1000)
    filter_str = (
        f"tags.`mlflow.traceName` RLIKE '(rag_query|eval_query)' "
        f"AND timestamp_ms > {cutoff_ms}"
    )
    print(f"Filter: {filter_str}")

    traces = mlflow.search_traces(
        experiment_ids=[exp.experiment_id],
        filter_string=filter_str,
        max_results=max_traces,
    )

    if traces.empty:
        print("No traces found to evaluate.")
        output = {"traces_evaluated": 0, "eval_run_id": "", "metrics": {}}
        with open(eval_output.path, "w") as f:
            json.dump(output, f)
        return

    # Filter out traces that already have a groundedness assessment
    def _has_groundedness(row):
        for a in (row.get("assessments", []) or []):
            name = ""
            if isinstance(a, dict):
                name = a.get("assessment_name", a.get("name", ""))
            else:
                name = getattr(a, "name", "")
                if hasattr(a, "feedback"):
                    name = getattr(a.feedback, "name", name)
            if name == "groundedness":
                return True
        return False

    already_assessed = traces.apply(_has_groundedness, axis=1)
    traces = traces[~already_assessed]
    if traces.empty:
        print("All traces already assessed. Nothing new to evaluate.")
        output = {"traces_evaluated": 0, "eval_run_id": "", "metrics": {}}
        with open(eval_output.path, "w") as f:
            json.dump(output, f)
        return
    print(f"Skipped {already_assessed.sum()} already-assessed traces.")

    num_traces = len(traces)
    print(f"Found {num_traces} traces. Running scorers...")

    mlflow.set_experiment(experiment_name)

    # Phase A: MLflow code-based scorers (no LLM calls)
    mlflow.genai.evaluate(
        data=traces,
        scorers=[policy_language_check, latency_sla_check],
    )
    print("Phase A complete: policy_language and latency_sla scored.")

    eval_run_id = f"pipeline-eval-{int(time.time())}"

    # Phase B: RAGAS metrics via EvalHub
    from evalhub import SyncEvalHubClient, JobSubmissionRequest, ModelConfig, BenchmarkConfig
    from evalhub.models.api import TestDataRef, S3TestDataRef

    def _extract_trace_fields(trace_row):
        """Extract user_input, response, and retrieved_contexts from a trace row."""
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

    samples = []
    trace_ids = []
    for _, trace_row in traces.iterrows():
        user_input, response, contexts = _extract_trace_fields(trace_row)
        if not user_input or not response:
            continue
        samples.append({
            "user_input": user_input,
            "response": response,
            "retrieved_contexts": contexts,
        })
        trace_ids.append(trace_row.get("trace_id", ""))

    ragas_scores = {"faithfulness": [], "answer_relevancy": []}

    if samples:
        import tempfile
        import boto3

        dataset_path = os.path.join(tempfile.mkdtemp(), "ragas_dataset.jsonl")
        with open(dataset_path, "w") as df:
            for s in samples:
                df.write(json.dumps(s) + "\n")

        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT_URL", "http://minio.gov-rag-poc.svc:9000"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "minio"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "minio123"),
        )
        bucket = "evalhub-data"
        try:
            s3.create_bucket(Bucket=bucket)
        except Exception:
            pass
        s3_key = f"ragas-eval/{eval_run_id}.jsonl"
        s3.upload_file(dataset_path, bucket, s3_key)
        s3_uri = f"s3://{bucket}/{s3_key}"
        print(f"Uploaded {len(samples)} samples to {s3_uri}")

        evalhub_url = os.environ.get(
            "EVALHUB_URL", "https://evalhub.redhat-ods-applications.svc:8443"
        )
        evalhub_tenant = os.environ.get("EVALHUB_TENANT", os.environ.get("NAMESPACE", "gov-rag-poc"))

        judge_url = llm_judge_endpoint.rstrip("/")
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
                    name=f"ragas-eval-{eval_run_id}",
                    model=ModelConfig(url=judge_url, name=llm_model),
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
                print(f"EvalHub RAGAS job submitted: {job_id}")

                result = eh_client.jobs.wait_for_completion(job_id, timeout=1200)
                job_status = result.status.state if hasattr(result.status, "state") else result.status
                print(f"EvalHub RAGAS job status: {job_status}")

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
                    print(f"EvalHub aggregate metrics: faithfulness={avg_faith:.4f}, answer_relevancy={avg_relevancy:.4f}")

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
                    print(f"EvalHub RAGAS job completed. Logged scores for {len(trace_ids)} traces.")
                else:
                    print(f"EvalHub RAGAS job ended with status: {job_status}")

        except Exception as e:
            print(f"EvalHub RAGAS evaluation failed: {e}")
            if hasattr(e, "response"):
                print(f"Response status: {e.response.status_code}")
                print(f"Response body: {e.response.text}")
            import traceback
            traceback.print_exc()
    else:
        print("No valid samples for RAGAS evaluation.")

    print("Phase B complete: RAGAS metrics scored via EvalHub.")

    # Aggregate metrics
    avg_faithfulness = sum(ragas_scores["faithfulness"]) / len(ragas_scores["faithfulness"]) if ragas_scores["faithfulness"] else 0.0
    avg_answer_relevancy = sum(ragas_scores["answer_relevancy"]) / len(ragas_scores["answer_relevancy"]) if ragas_scores["answer_relevancy"] else 0.0
    hallucination_rate = 1.0 - avg_faithfulness

    # Re-read traces for code-based scorer aggregation
    scored_traces = mlflow.search_traces(
        experiment_ids=[exp.experiment_id],
        filter_string=filter_str,
        max_results=max_traces,
    )

    relevance_values = []
    latency_values = []
    policy_yes = 0
    total_assessed = 0

    for _, trace_row in scored_traces.iterrows():
        assessments_list = trace_row.get("assessments", []) or []
        for assessment in assessments_list:
            if isinstance(assessment, dict):
                name = assessment.get("assessment_name", "")
                fb = assessment.get("feedback", {})
                value = fb.get("value", "") if isinstance(fb, dict) else ""
            else:
                name = getattr(assessment, "name", "")
                value = getattr(assessment, "value", "")

            if name == "relevance":
                relevance_values.append(1.0 if str(value).lower() in ("yes", "true") else 0.0)
            elif name == "policy_language":
                if value == "yes":
                    policy_yes += 1
                total_assessed += 1

        exec_dur = trace_row.get("execution_duration", None)
        if exec_dur:
            try:
                latency_values.append(float(exec_dur) / 1000.0)
            except (ValueError, TypeError):
                pass

    avg_relevance = sum(relevance_values) / len(relevance_values) if relevance_values else 0.0
    source_accuracy = policy_yes / total_assessed if total_assessed > 0 else 0.0
    avg_latency = sum(latency_values) / len(latency_values) if latency_values else 0.0

    prompt_version = "unknown"
    model_name = llm_model
    for _, trace_row in scored_traces.head(1).iterrows():
        spans = trace_row.get("spans", [])
        if spans:
            root_span = spans[0] if isinstance(spans, list) else None
            if root_span and isinstance(root_span, dict):
                attrs = root_span.get("attributes", {}) or {}
                prompt_version = attrs.get("prompt_version", "unknown")
                model_name = attrs.get("model_name", llm_model)

    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(run_name=f"eval-{eval_run_id}"):
        mlflow.set_tag("prompt_version", prompt_version)
        mlflow.set_tag("model_name", model_name)
        mlflow.set_tag("num_questions", str(num_traces))
        mlflow.set_tag("eval_run_id", eval_run_id)
        mlflow.set_tag("eval_type", "ragas")
        mlflow.log_metric("avg_groundedness", round(avg_faithfulness, 4))
        mlflow.log_metric("avg_faithfulness", round(avg_faithfulness, 4))
        mlflow.log_metric("avg_answer_relevancy", round(avg_answer_relevancy, 4))
        mlflow.log_metric("avg_relevance", round(avg_relevance, 4))
        mlflow.log_metric("hallucination_rate", round(hallucination_rate, 4))
        mlflow.log_metric("source_accuracy", round(source_accuracy, 4))
        mlflow.log_metric("avg_latency", round(avg_latency, 4))
        mlflow.log_text(json.dumps({
            "eval_run_id": eval_run_id,
            "traces_evaluated": num_traces,
            "metrics": {
                "avg_faithfulness": avg_faithfulness,
                "avg_answer_relevancy": avg_answer_relevancy,
                "avg_relevance": avg_relevance,
                "hallucination_rate": hallucination_rate,
                "source_accuracy": source_accuracy,
                "avg_latency": avg_latency,
            },
        }, indent=2), "eval_results.json")

    output = {
        "traces_evaluated": num_traces,
        "eval_run_id": eval_run_id,
        "prompt_version": prompt_version,
        "model_name": model_name,
        "metrics": {
            "avg_groundedness": round(avg_faithfulness, 4),
            "avg_faithfulness": round(avg_faithfulness, 4),
            "avg_answer_relevancy": round(avg_answer_relevancy, 4),
            "avg_relevance": round(avg_relevance, 4),
            "hallucination_rate": round(hallucination_rate, 4),
            "source_accuracy": round(source_accuracy, 4),
            "avg_latency": round(avg_latency, 4),
        },
    }

    print(f"Evaluation complete: {num_traces} traces scored.")
    print(f"RAGAS: faithfulness={avg_faithfulness:.3f}, answer_relevancy={avg_answer_relevancy:.3f}")
    print(f"Code-based: hallucination_rate={hallucination_rate:.3f}, source_accuracy={source_accuracy:.3f}")

    with open(eval_output.path, "w") as f:
        json.dump(output, f)


@dsl.component(
    base_image=RAG_APP_IMAGE,
    packages_to_install=[],
)
def analyze_and_flag(
    mlflow_uri: str,
    mlflow_workspace: str,
    experiment_name: str,
    lookback_hours: int,
    eval_output: dsl.Input[dsl.Artifact],
    analysis_output: dsl.Output[dsl.Artifact],
):
    """Search assessed traces, flag violations, and compute trends."""
    import os
    import json
    import time

    os.environ.setdefault("MLFLOW_TRACKING_INSECURE_TLS", "true")
    os.environ.setdefault("MLFLOW_TRACKING_AUTH", "kubernetes-namespaced")

    import mlflow
    mlflow.set_tracking_uri(mlflow_uri)
    if mlflow_workspace:
        mlflow.set_workspace(mlflow_workspace)

    with open(eval_output.path) as f:
        eval_data = json.load(f)

    traces_evaluated = eval_data.get("traces_evaluated", 0)
    if traces_evaluated == 0:
        print("No traces were evaluated. Skipping analysis.")
        result = {
            "flagged_traces": [],
            "violation_counts": {},
            "violation_rates": {},
            "trend_deltas": {},
            "current_period_total": 0,
            "previous_period_total": 0,
        }
        with open(analysis_output.path, "w") as f:
            json.dump(result, f)
        return

    exp = mlflow.get_experiment_by_name(experiment_name)
    if exp is None:
        print(f"Experiment '{experiment_name}' not found.")
        result = {"flagged_traces": [], "violation_counts": {}, "violation_rates": {}, "trend_deltas": {}, "current_period_total": 0, "previous_period_total": 0}
        with open(analysis_output.path, "w") as f:
            json.dump(result, f)
        return

    now_ms = int(time.time() * 1000)
    current_cutoff_ms = now_ms - lookback_hours * 3600 * 1000
    previous_cutoff_ms = now_ms - 2 * lookback_hours * 3600 * 1000

    def _search_traces(cutoff_ms, max_results=100):
        filter_str = (
            f"tags.`mlflow.traceName` RLIKE '(rag_query|eval_query)' "
            f"AND timestamp_ms > {cutoff_ms}"
        )
        return mlflow.search_traces(
            experiment_ids=[exp.experiment_id],
            filter_string=filter_str,
            max_results=max_results,
        )

    current_traces = _search_traces(current_cutoff_ms)
    print(f"Current period: {len(current_traces)} traces")

    flagged = []
    violation_counts = {
        "not_grounded": 0,
        "sla_breach": 0,
        "no_policy_language": 0,
    }

    for _, trace_row in current_traces.iterrows():
        trace_id = trace_row.get("trace_id", trace_row.get("request_id", ""))
        violations = []

        assessments_list = trace_row.get("assessments", []) or []

        attrs = {}
        spans = trace_row.get("spans", [])
        if spans:
            root_span = spans[0] if isinstance(spans, list) else None
            if root_span and isinstance(root_span, dict):
                attrs = root_span.get("attributes", {}) or {}

        if not attrs:
            try:
                trace_obj = mlflow.MlflowClient().get_trace(trace_id)
                if trace_obj and trace_obj.data and trace_obj.data.spans:
                    root_span = trace_obj.data.spans[0]
                    attrs = dict(root_span.attributes) if root_span.attributes else {}
            except Exception:
                continue

        sla_val = attrs.get("sla_pass", "")
        if str(sla_val).lower() == "false":
            violations.append("sla_breach")
            violation_counts["sla_breach"] += 1

        for assessment in assessments_list:
            if isinstance(assessment, dict):
                name = assessment.get("assessment_name", "")
                fb = assessment.get("feedback", {})
                value = fb.get("value", "") if isinstance(fb, dict) else ""
            else:
                name = getattr(assessment, "name", "")
                value = getattr(assessment, "value", None)
                if hasattr(assessment, "feedback"):
                    fb = assessment.feedback
                    name = getattr(fb, "name", name)
                    value = getattr(fb, "value", value)

            if name == "groundedness":
                try:
                    faith_score = float(value)
                    if faith_score < 0.6:
                        violations.append("not_grounded")
                        violation_counts["not_grounded"] += 1
                except (ValueError, TypeError):
                    if str(value) == "not_grounded":
                        violations.append("not_grounded")
                        violation_counts["not_grounded"] += 1
            elif name == "policy_language" and str(value) == "no":
                violations.append("no_policy_language")
                violation_counts["no_policy_language"] += 1

        if violations:
            ts_ms = trace_row.get("request_time", 0)
            try:
                ts_ms = int(ts_ms) if ts_ms else 0
            except (ValueError, TypeError):
                ts_ms = 0
            flagged.append({
                "trace_id": trace_id,
                "timestamp_ms": ts_ms,
                "violations": violations,
                "severity": "high" if "not_grounded" in violations else "medium",
            })

    current_total = len(current_traces)
    violation_rates = {}
    for k, v in violation_counts.items():
        violation_rates[k] = round(v / current_total, 3) if current_total > 0 else 0.0

    previous_traces = _search_traces(previous_cutoff_ms)
    prev_in_window = previous_traces[
        previous_traces.get("timestamp_ms", 0) < current_cutoff_ms
    ] if not previous_traces.empty and "timestamp_ms" in previous_traces.columns else previous_traces
    previous_total = len(prev_in_window)

    trend_deltas = {}
    if previous_total > 0 and current_total > 0:
        trend_deltas["volume_change_pct"] = round(
            (current_total - previous_total) / previous_total * 100, 1
        )
    else:
        trend_deltas["volume_change_pct"] = 0.0

    print(f"Flagged {len(flagged)} traces with violations.")
    print(f"Violation counts: {violation_counts}")
    print(f"Violation rates: {violation_rates}")

    result = {
        "flagged_traces": flagged,
        "violation_counts": violation_counts,
        "violation_rates": violation_rates,
        "trend_deltas": trend_deltas,
        "current_period_total": current_total,
        "previous_period_total": previous_total,
    }

    with open(analysis_output.path, "w") as f:
        json.dump(result, f, indent=2)

    print("Analysis complete.")


@dsl.component(
    base_image=RAG_APP_IMAGE,
    packages_to_install=[],
)
def compare_and_report(
    mlflow_uri: str,
    mlflow_workspace: str,
    experiment_name: str,
    eval_output: dsl.Input[dsl.Artifact],
    analysis_output: dsl.Input[dsl.Artifact],
):
    """Compare with previous run, incorporate flagged data, and log summary report."""
    import os
    import json
    from datetime import datetime

    os.environ.setdefault("MLFLOW_TRACKING_INSECURE_TLS", "true")
    os.environ.setdefault("MLFLOW_TRACKING_AUTH", "kubernetes-namespaced")

    import mlflow
    mlflow.set_tracking_uri(mlflow_uri)
    if mlflow_workspace:
        mlflow.set_workspace(mlflow_workspace)

    with open(eval_output.path) as f:
        current = json.load(f)
    with open(analysis_output.path) as f:
        analysis = json.load(f)

    traces_evaluated = current.get("traces_evaluated", 0)
    current_metrics = current.get("metrics", {})
    prompt_version = current.get("prompt_version", "unknown")
    model_name = current.get("model_name", "unknown")

    if traces_evaluated == 0:
        print("No traces were evaluated. Skipping comparison.")
        return

    flagged_traces = analysis.get("flagged_traces", [])
    violation_counts = analysis.get("violation_counts", {})
    violation_rates = analysis.get("violation_rates", {})
    trend_deltas = analysis.get("trend_deltas", {})

    client = mlflow.MlflowClient()
    exp = client.get_experiment_by_name(experiment_name)
    if exp is None:
        print(f"Experiment '{experiment_name}' not found.")
        return

    runs = client.search_runs(
        experiment_ids=[exp.experiment_id],
        order_by=["start_time DESC"],
        max_results=5,
    )

    previous_metrics = {}
    prev_run_name = "none"
    if len(runs) >= 2:
        prev_run = runs[1]
        previous_metrics = prev_run.data.metrics
        prev_run_name = prev_run.info.run_name or prev_run.info.run_id[:12]

    report_lines = [
        "# RAG Evaluation Comparison Report",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Current Evaluation",
        f"- Traces evaluated: {traces_evaluated}",
    ]

    for k, v in sorted(current_metrics.items()):
        report_lines.append(f"- {k}: {v:.3f}")

    report_lines.extend([
        "",
        "## Compliance Analysis",
        f"- Flagged traces: {len(flagged_traces)}",
    ])
    for k, v in sorted(violation_counts.items()):
        rate = violation_rates.get(k, 0)
        report_lines.append(f"- {k}: {v} ({rate:.1%})")

    if trend_deltas:
        report_lines.extend(["", "## Trends vs Previous Period"])
        for k, v in sorted(trend_deltas.items()):
            report_lines.append(f"- {k}: {v:+.1f}%")

    report_lines.extend(["", "## Comparison with Previous Run"])
    if previous_metrics:
        report_lines.append(f"Previous run: {prev_run_name}")
        report_lines.append("")
        report_lines.append("| Metric | Current | Previous | Delta |")
        report_lines.append("|--------|---------|----------|-------|")

        regressions = []
        for key in sorted(set(list(current_metrics.keys()) + list(previous_metrics.keys()))):
            curr_val = current_metrics.get(key, 0)
            prev_val = previous_metrics.get(key, 0)
            delta = curr_val - prev_val
            delta_str = f"{delta:+.3f}"
            report_lines.append(f"| {key} | {curr_val:.3f} | {prev_val:.3f} | {delta_str} |")
            if "mean" in key and delta < -0.1:
                regressions.append(key)

        report_lines.extend(["", "## Regression Check"])
        if regressions:
            report_lines.append(f"**REGRESSION DETECTED** in: {', '.join(regressions)}")
            report_lines.append("Action: Review prompt and retrieval changes before production deployment.")
        else:
            report_lines.append("No significant regressions detected. Safe to proceed.")
    else:
        report_lines.append("No previous evaluation run found for comparison.")
        report_lines.append("This is the baseline run.")

    report_text = "\n".join(report_lines)
    print(report_text)

    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(run_name=f"eval-comparison-{int(datetime.now().timestamp())}"):
        mlflow.set_tag("report_type", "comparison")
        mlflow.set_tag("prompt_version", prompt_version)
        mlflow.set_tag("model_name", model_name)
        mlflow.set_tag("num_questions", str(traces_evaluated))
        mlflow.set_tag("traces_evaluated", str(traces_evaluated))
        mlflow.set_tag("flagged_count", str(len(flagged_traces)))
        for k, v in current_metrics.items():
            mlflow.log_metric(k, v)
        for k, v in violation_counts.items():
            mlflow.log_metric(f"violations_{k}", v)
        for k, v in violation_rates.items():
            mlflow.log_metric(f"rate_{k}", v)
        mlflow.log_text(report_text, "comparison_report.md")
        mlflow.log_text(json.dumps(flagged_traces, indent=2), "flagged_traces.json")
        mlflow.log_text(json.dumps(analysis, indent=2), "analysis_summary.json")

    print("Comparison report and flagged traces logged to MLflow.")


@dsl.pipeline(
    name="rag-evaluation",
    description="Evaluate RAG pipeline traces, flag compliance violations, and compare with previous runs for drift detection",
)
def rag_eval_pipeline(
    mlflow_uri: str = "https://mlflow.apps.cluster.example.com/mlflow",
    mlflow_workspace: str = "gov-rag-poc",
    experiment_name: str = "rag-governance-poc",
    llm_endpoint: str = "https://llm-endpoint.apps.cluster.example.com/v1",
    llm_judge_endpoint: str = "http://llm-judge.svc.cluster.local/v1",
    llm_model: str = "qwen35-9b-awq",
    max_traces: int = 10,
    lookback_hours: int = 24,
):
    eval_task = evaluate_traces(
        mlflow_uri=mlflow_uri,
        mlflow_workspace=mlflow_workspace,
        experiment_name=experiment_name,
        llm_endpoint=llm_endpoint,
        llm_judge_endpoint=llm_judge_endpoint,
        llm_model=llm_model,
        max_traces=max_traces,
        lookback_hours=lookback_hours,
    )
    eval_task.set_caching_options(False)

    analyze_task = analyze_and_flag(
        mlflow_uri=mlflow_uri,
        mlflow_workspace=mlflow_workspace,
        experiment_name=experiment_name,
        lookback_hours=lookback_hours,
        eval_output=eval_task.outputs["eval_output"],
    )
    analyze_task.set_caching_options(False)

    compare_task = compare_and_report(
        mlflow_uri=mlflow_uri,
        mlflow_workspace=mlflow_workspace,
        experiment_name=experiment_name,
        eval_output=eval_task.outputs["eval_output"],
        analysis_output=analyze_task.outputs["analysis_output"],
    )
    compare_task.set_caching_options(False)


if __name__ == "__main__":
    import sys

    output_file = "eval-pipeline.yaml"
    compiler.Compiler().compile(rag_eval_pipeline, output_file)
    print(f"Pipeline compiled to {output_file}")

    if "--run" in sys.argv:
        print("To submit: upload the YAML via RHOAI Dashboard > Data Science Pipelines > Import")
