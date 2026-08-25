"""Audit Portal: single Streamlit app for governance trace browsing and report export."""

import os
import io
import json
import time
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import mlflow

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
MLFLOW_WORKSPACE = os.getenv("MLFLOW_WORKSPACE", "")
EXPERIMENT_NAME = os.getenv("MLFLOW_EXPERIMENT_NAME", "rag-governance-poc")
EVAL_EXPERIMENT_NAME = EXPERIMENT_NAME

mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
if MLFLOW_WORKSPACE:
    mlflow.set_workspace(MLFLOW_WORKSPACE)

st.set_page_config(
    page_title="Governance Audit Portal",
    page_icon="🔍",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def fetch_traces(_experiment_name: str) -> pd.DataFrame:
    """Fetch traces from MLflow and return as a DataFrame."""
    client = mlflow.MlflowClient()

    try:
        experiment = client.get_experiment_by_name(_experiment_name)
    except Exception:
        return pd.DataFrame()

    if experiment is None:
        return pd.DataFrame()

    try:
        traces_df = mlflow.search_traces(
            experiment_ids=[experiment.experiment_id],
            max_results=100,
        )
    except Exception:
        return pd.DataFrame()

    if traces_df is None or traces_df.empty:
        return pd.DataFrame()

    def _clean_attr(val):
        """Strip extra JSON quotes from span attribute values."""
        s = str(val).strip()
        if s.startswith('"') and s.endswith('"'):
            s = s[1:-1]
        return s

    rows = []
    for _, trace_row in traces_df.iterrows():
        trace_id = trace_row.get("trace_id", "")
        state = trace_row.get("state", "UNKNOWN")
        request_time = trace_row.get("request_time", None)
        execution_duration = trace_row.get("execution_duration", None)
        spans = trace_row.get("spans", [])
        assessments_list = trace_row.get("assessments", [])
        trace_tags = trace_row.get("tags", {}) or {}

        root_span = spans[0] if spans else None
        attrs = {}
        if root_span and isinstance(root_span, dict):
            attrs = root_span.get("attributes", {}) or {}
        elif root_span and hasattr(root_span, "attributes"):
            attrs = dict(root_span.attributes) if root_span.attributes else {}

        timestamp = None
        if request_time:
            try:
                timestamp = datetime.fromtimestamp(int(request_time) / 1000)
            except (ValueError, TypeError, OSError):
                pass

        row = {
            "trace_id": trace_id,
            "timestamp": timestamp,
            "status": str(state),
            "execution_time_ms": execution_duration,
            "prompt_version": trace_tags.get("prompt_version", _clean_attr(attrs.get("prompt_version", ""))),
            "model_name": trace_tags.get("model_name", _clean_attr(attrs.get("model_name", ""))),
            "model_endpoint": _clean_attr(attrs.get("model_endpoint", "")),
            "source_documents": _clean_attr(attrs.get("source_documents", "")),
            "app_version": trace_tags.get("app_version", _clean_attr(attrs.get("app_version", ""))),
            "num_spans": len(spans) if spans else 0,
            "sla_pass": trace_tags.get("sla_pass", _clean_attr(attrs.get("sla_pass", ""))),
            "latency_ms": trace_tags.get("latency_ms", _clean_attr(attrs.get("latency_ms", ""))),
            "policy_terms_count": trace_tags.get("policy_terms_count", _clean_attr(attrs.get("policy_terms_count", ""))),
            "source_count": trace_tags.get("source_count", _clean_attr(attrs.get("source_count", ""))),
            "guardrail_blocked": trace_tags.get("guardrail_blocked", _clean_attr(attrs.get("guardrail_blocked", ""))),
        }

        groundedness_value = ""
        if assessments_list:
            for assessment in assessments_list:
                if isinstance(assessment, dict):
                    name = assessment.get("assessment_name", "")
                    fb = assessment.get("feedback", {})
                    value = fb.get("value", "") if isinstance(fb, dict) else ""
                    if not value:
                        value = assessment.get("value", "")
                else:
                    name = getattr(assessment, "name", "")
                    value = getattr(assessment, "value", "")
                if name == "groundedness" and value != "error":
                    groundedness_value = str(value)
                    break
        row["groundedness"] = groundedness_value

        request_data = trace_row.get("request", {})
        response_data = trace_row.get("response", {})

        if isinstance(request_data, dict):
            row["user_query"] = request_data.get("user_question", str(request_data))
        elif request_data is not None:
            row["user_query"] = str(request_data)
        else:
            row["user_query"] = ""

        if isinstance(response_data, dict):
            row["response"] = response_data.get("answer", str(response_data))
        elif response_data is not None:
            row["response"] = str(response_data)
        else:
            row["response"] = ""

        rows.append(row)

    df = pd.DataFrame(rows)
    if "timestamp" in df.columns:
        df = df.sort_values("timestamp", ascending=False)
    return df


def build_export_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare a clean DataFrame for export."""
    export_cols = [
        "trace_id", "timestamp", "status", "execution_time_ms",
        "prompt_version", "model_name", "model_endpoint",
        "source_documents", "app_version",
        "sla_pass", "latency_ms", "policy_terms_count", "source_count",
        "groundedness", "guardrail_blocked",
        "user_query", "response",
    ]
    available = [c for c in export_cols if c in df.columns]
    return df[available].copy()


def build_summary(df: pd.DataFrame) -> dict:
    """Compute summary statistics for the dashboard."""
    if df.empty:
        return {
            "total_interactions": 0,
            "avg_latency_ms": 0,
            "prompt_versions_used": [],
            "models_used": [],
            "success_rate": 0,
            "date_range": ("N/A", "N/A"),
        }

    return {
        "total_interactions": len(df),
        "avg_latency_ms": round(df["execution_time_ms"].mean(), 1)
        if "execution_time_ms" in df.columns
        else 0,
        "prompt_versions_used": sorted(
            df["prompt_version"].dropna().unique().tolist()
        ),
        "models_used": sorted(df["model_name"].dropna().unique().tolist()),
        "success_rate": round(
            (df["status"] == "OK").sum() / len(df) * 100, 1
        )
        if "status" in df.columns
        else 0,
        "date_range": (
            str(df["timestamp"].min().date()) if df["timestamp"].notna().any() else "N/A",
            str(df["timestamp"].max().date()) if df["timestamp"].notna().any() else "N/A",
        ),
    }


# ---------------------------------------------------------------------------
# Evaluation data loading
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30)
def fetch_eval_runs(_eval_experiment_name: str) -> pd.DataFrame:
    """Fetch evaluation runs from the eval experiment."""
    client = mlflow.MlflowClient()
    try:
        experiment = client.get_experiment_by_name(_eval_experiment_name)
    except Exception:
        return pd.DataFrame()

    if experiment is None:
        return pd.DataFrame()

    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        order_by=["start_time DESC"],
    )

    if not runs:
        return pd.DataFrame()

    rows = []
    for run in runs:
        tags = run.data.tags
        metrics = run.data.metrics
        rows.append({
            "run_id": run.info.run_id,
            "run_name": run.info.run_name or run.info.run_id[:12],
            "start_time": datetime.fromtimestamp(run.info.start_time / 1000),
            "prompt_version": tags.get("prompt_version", "?"),
            "model_name": tags.get("model_name", "?"),
            "eval_type": tags.get("eval_type", "legacy"),
            "has_ground_truth": tags.get("has_ground_truth", "false"),
            "num_questions": int(tags.get("num_questions", "0")),
            "avg_groundedness": metrics.get("avg_groundedness", 0),
            "avg_relevance": metrics.get("avg_relevance", 0),
            "avg_faithfulness": metrics.get("avg_faithfulness", 0),
            "avg_answer_relevancy": metrics.get("avg_answer_relevancy", 0),
            "avg_context_precision": metrics.get("avg_context_precision", 0),
            "avg_context_recall": metrics.get("avg_context_recall", 0),
            "avg_factual_correctness": metrics.get("avg_factual_correctness", 0),
            "avg_answer_similarity": metrics.get("avg_answer_similarity", 0),
            "hallucination_rate": metrics.get("hallucination_rate", 0),
            "source_accuracy": metrics.get("source_accuracy", 0),
            "avg_latency": metrics.get("avg_latency", 0),
        })

    return pd.DataFrame(rows)


@st.cache_data(ttl=60)
def fetch_eval_details(_run_id: str) -> pd.DataFrame:
    """Fetch per-question evaluation results for a specific run."""
    client = mlflow.MlflowClient()
    try:
        artifacts = client.list_artifacts(_run_id)
        artifact_names = [a.path for a in artifacts]

        if "eval_results.json" in artifact_names:
            local_path = client.download_artifacts(_run_id, "eval_results.json")
            return pd.read_json(local_path)
    except Exception:
        pass
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# KFP Pipeline helpers (for triggering eval runs)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def fetch_flagged_traces(_experiment_name: str) -> tuple[list, dict]:
    """Fetch flagged traces from the latest pipeline comparison run."""
    client = mlflow.MlflowClient()
    try:
        experiment = client.get_experiment_by_name(_experiment_name)
    except Exception:
        return [], {}

    if experiment is None:
        return [], {}

    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        filter_string="tags.report_type = 'comparison'",
        order_by=["start_time DESC"],
        max_results=1,
    )

    if not runs:
        return [], {}

    run = runs[0]
    flagged = []
    summary = {}

    try:
        local_path = client.download_artifacts(run.info.run_id, "flagged_traces.json")
        with open(local_path) as f:
            flagged = json.load(f)
    except Exception:
        pass

    try:
        local_path = client.download_artifacts(run.info.run_id, "analysis_summary.json")
        with open(local_path) as f:
            summary = json.load(f)
    except Exception:
        pass

    return flagged, summary


NAMESPACE = os.getenv("NAMESPACE", "gov-rag-poc")
KFP_HOST = os.getenv(
    "KFP_HOST",
    f"https://ds-pipeline-pipelines-definition.{NAMESPACE}.svc:8443",
)
PIPELINE_YAML = os.getenv("PIPELINE_YAML", "/app/eval-pipeline.yaml")
PIPELINE_NAME = "rag-evaluation"

# Disable the KFP SDK healthz probe at import time -- the DSPA 8443
# endpoint behind the service mesh never responds to it reliably.
import urllib3 as _urllib3
_urllib3.disable_warnings()
from kfp import Client as _KfpClient
_KfpClient.get_kfp_healthz = lambda self, **kw: None


def _get_kfp_client():
    """Get a KFP client connected to the in-cluster DSPA."""
    sa_token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"

    if os.path.exists(sa_token_path):
        with open(sa_token_path) as f:
            token = f.read().strip()
    else:
        token = os.getenv("KFP_TOKEN", "")

    return _KfpClient(
        host=KFP_HOST,
        existing_token=token,
        namespace=NAMESPACE,
        ssl_ca_cert=None,
        verify_ssl=False,
    )


def submit_eval_pipeline(max_traces: int = 50) -> dict:
    """Submit the evaluation pipeline as a KFP run."""
    try:
        client = _get_kfp_client()

        run = client.create_run_from_pipeline_package(
            pipeline_file=PIPELINE_YAML,
            arguments={
                "mlflow_uri": os.getenv("MLFLOW_TRACKING_URI", ""),
                "mlflow_workspace": os.getenv("MLFLOW_WORKSPACE", ""),
                "experiment_name": EVAL_EXPERIMENT_NAME,
                "llm_endpoint": os.getenv("LLM_ENDPOINT", ""),
                "llm_judge_endpoint": os.getenv("LLM_JUDGE_ENDPOINT", os.getenv("LLM_ENDPOINT", "")),
                "llm_model": os.getenv("LLM_MODEL", ""),
                "max_traces": max_traces,
            },
            run_name=f"eval-{int(time.time())}",
            experiment_name="eval-triggered",
        )
        return {
            "run_id": run.run_id,
            "state": "Submitted",
            "message": f"Pipeline run submitted: {run.run_id}",
        }
    except Exception as e:
        return {"run_id": "", "state": "Error", "message": str(e)}


def get_pipeline_run_status(run_id: str) -> dict:
    """Check the status of a KFP pipeline run."""
    try:
        client = _get_kfp_client()
        run = client.get_run(run_id)
        state = run.state or "Unknown"
        return {"state": state, "message": f"Pipeline run: {state}"}
    except Exception as e:
        return {"state": "Error", "message": str(e)}


def list_pipeline_runs(max_runs: int = 10) -> list[dict]:
    """List recent pipeline runs."""
    try:
        client = _get_kfp_client()
        response = client.list_runs(page_size=max_runs, sort_by="created_at desc")
        result = []
        for run in (response.runs or []):
            result.append({
                "name": run.display_name or run.run_id[:12],
                "state": run.state or "Unknown",
                "created": run.created_at,
                "run_id": run.run_id,
            })
        return result
    except Exception:
        return []


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.title("Governance Audit Portal")
st.caption("Self-service trace browsing and compliance report generation")

df = fetch_traces(EXPERIMENT_NAME)

tab_dashboard, tab_browse, tab_eval, tab_export = st.tabs(
    ["Dashboard", "Browse Traces", "Evaluation", "Export Report"]
)

# ---- Dashboard Tab ----
with tab_dashboard:
    if df.empty:
        st.info(
            "No traces found. Run some queries through the RAG application first."
        )
    else:
        summary = build_summary(df)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Interactions", summary["total_interactions"])
        col2.metric("Avg Latency", f"{summary['avg_latency_ms']} ms")
        col3.metric("Success Rate", f"{summary['success_rate']}%")
        col4.metric(
            "Prompt Versions",
            len(summary["prompt_versions_used"]),
        )

        st.markdown("---")

        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("Interactions Over Time")
            if "timestamp" in df.columns and df["timestamp"].notna().any():
                daily = (
                    df.set_index("timestamp")
                    .resample("D")
                    .size()
                    .reset_index(name="count")
                )
                fig = px.bar(
                    daily, x="timestamp", y="count",
                    labels={"timestamp": "Date", "count": "Interactions"},
                )
                fig.update_layout(height=300, margin=dict(t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)

        with col_right:
            st.subheader("Latency Distribution")
            if "execution_time_ms" in df.columns:
                fig2 = px.histogram(
                    df, x="execution_time_ms", nbins=30,
                    labels={"execution_time_ms": "Latency (ms)"},
                )
                fig2.update_layout(height=300, margin=dict(t=10, b=10))
                st.plotly_chart(fig2, use_container_width=True)

        if summary["prompt_versions_used"]:
            st.subheader("Usage by Prompt Version")
            version_counts = df["prompt_version"].value_counts().reset_index()
            version_counts.columns = ["Prompt Version", "Count"]
            fig3 = px.pie(
                version_counts, values="Count", names="Prompt Version",
            )
            fig3.update_layout(height=300, margin=dict(t=10, b=10))
            st.plotly_chart(fig3, use_container_width=True)

        st.markdown("---")
        st.subheader("Compliance Overview")

        sla_values = df["sla_pass"].astype(str).str.lower()
        sla_pass_count = (sla_values == "true").sum()
        sla_breach_count = (sla_values == "false").sum()
        sla_total = sla_pass_count + sla_breach_count
        sla_pass_rate = round(sla_pass_count / sla_total * 100, 1) if sla_total > 0 else 0

        faith_scores = []
        for val in df["groundedness"]:
            try:
                faith_scores.append(float(val))
            except (ValueError, TypeError):
                if str(val) == "grounded":
                    faith_scores.append(1.0)
                elif str(val) == "not_grounded":
                    faith_scores.append(0.0)
        ground_total = len(faith_scores)
        avg_faith = round(sum(faith_scores) / ground_total * 100, 1) if ground_total > 0 else 0
        grounded_count = sum(1 for s in faith_scores if s >= 0.6)
        not_grounded_count = ground_total - grounded_count

        policy_vals = df["policy_terms_count"].apply(
            lambda x: int(x) > 0 if str(x).isdigit() else False
        )
        policy_count = policy_vals.sum()
        policy_rate = round(policy_count / len(df) * 100, 1) if len(df) > 0 else 0

        comp_c1, comp_c2, comp_c3, comp_c4 = st.columns(4)
        comp_c1.metric("SLA Pass Rate", f"{sla_pass_rate}%",
                       delta=f"{sla_pass_count}/{sla_total} traces")
        comp_c2.metric("Avg Faithfulness", f"{avg_faith}%",
                       delta=f"{grounded_count}/{ground_total} above 70%"
                       if ground_total > 0 else "Not yet evaluated")
        comp_c3.metric("Regulatory Terms", f"{policy_rate}%",
                       delta=f"{policy_count}/{len(df)} traces")
        comp_c4.metric("SLA Breaches", sla_breach_count,
                       delta=f"{sla_breach_count} of {sla_total}",
                       delta_color="inverse")

        eval_df_dash = fetch_eval_runs(EVAL_EXPERIMENT_NAME)
        if not eval_df_dash.empty:
            eval_df_dash = eval_df_dash[eval_df_dash["num_questions"] > 0]
        if not eval_df_dash.empty:
            latest = eval_df_dash.iloc[0]
            st.markdown("**Latest Evaluation Run**")
            ev_c1, ev_c2, ev_c3, ev_c4, ev_c5, ev_c6 = st.columns(6)
            ev_c1.metric("Run", latest["run_name"][:25])
            ev_c2.metric("Faithfulness", f"{latest['avg_faithfulness']:.0%}")
            ev_c3.metric("Ans Relevancy", f"{latest.get('avg_answer_relevancy', 0):.0%}")
            ev_c4.metric("Ctx Precision", f"{latest.get('avg_context_precision', 0):.0%}")
            ev_c5.metric("Hallucination", f"{latest['hallucination_rate']*100:.0f}%")
            ev_c6.metric("Avg Latency", f"{latest['avg_latency']:.1f}s")

# ---- Browse Traces Tab ----
TRACES_PER_PAGE = 20

with tab_browse:
    if df.empty:
        st.info("No traces available.")
    else:
        st.subheader("Filter Traces")

        filter_row1_c1, filter_row1_c2, filter_row1_c3 = st.columns(3)

        with filter_row1_c1:
            date_range = st.date_input(
                "Date Range",
                value=(
                    df["timestamp"].min().date()
                    if df["timestamp"].notna().any()
                    else datetime.now().date() - timedelta(days=30),
                    df["timestamp"].max().date()
                    if df["timestamp"].notna().any()
                    else datetime.now().date(),
                ),
            )

        with filter_row1_c2:
            version_options = ["All"] + sorted(
                df["prompt_version"].dropna().unique().tolist()
            )
            selected_version = st.selectbox("Prompt Version", version_options)

        with filter_row1_c3:
            status_options = ["All"] + sorted(
                df["status"].dropna().unique().tolist()
            )
            selected_status = st.selectbox("Status", status_options)

        st.markdown("**Compliance Filters**")
        filter_row2_c1, filter_row2_c2, filter_row2_c3 = st.columns(3)

        with filter_row2_c1:
            sla_filter = st.selectbox(
                "SLA Status", ["All", "Pass", "Breach"], key="sla_filter"
            )

        with filter_row2_c2:
            groundedness_filter = st.selectbox(
                "Groundedness",
                ["All", "Grounded", "Not Grounded", "Not Scored"],
                key="groundedness_filter",
            )

        with filter_row2_c3:
            policy_filter = st.selectbox(
                "Regulatory Terms",
                ["All", "Has Regulatory Terms", "No Regulatory Terms"],
                key="policy_filter",
                help=(
                    "Checks whether the response references banking regulatory terms "
                    "(e.g., LVR, KYC, AML, compliance). "
                    "Responses about policy should cite specific terms."
                ),
            )

        filtered = df.copy()
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start, end = date_range
            if "timestamp" in filtered.columns:
                mask = filtered["timestamp"].dt.date.between(start, end)
                filtered = filtered[mask]
        if selected_version != "All":
            filtered = filtered[filtered["prompt_version"] == selected_version]
        if selected_status != "All":
            filtered = filtered[filtered["status"] == selected_status]

        if sla_filter == "Pass":
            filtered = filtered[filtered["sla_pass"].astype(str).str.lower() == "true"]
        elif sla_filter == "Breach":
            filtered = filtered[filtered["sla_pass"].astype(str).str.lower() == "false"]

        if groundedness_filter == "Grounded":
            def _is_grounded(val):
                try:
                    return float(val) >= 0.6
                except (ValueError, TypeError):
                    return str(val) == "grounded"
            filtered = filtered[filtered["groundedness"].apply(_is_grounded)]
        elif groundedness_filter == "Not Grounded":
            def _is_not_grounded(val):
                try:
                    return float(val) < 0.6
                except (ValueError, TypeError):
                    return str(val) == "not_grounded"
            filtered = filtered[filtered["groundedness"].apply(_is_not_grounded)]
        elif groundedness_filter == "Not Scored":
            def _is_not_scored(val):
                s = str(val).strip()
                if s in ("", "error"):
                    return True
                try:
                    float(s)
                    return False
                except (ValueError, TypeError):
                    return s not in ("grounded", "not_grounded")
            filtered = filtered[filtered["groundedness"].apply(_is_not_scored)]

        if policy_filter == "Has Regulatory Terms":
            filtered = filtered[
                filtered["policy_terms_count"].apply(
                    lambda x: int(x) > 0 if str(x).isdigit() else False
                )
            ]
        elif policy_filter == "No Regulatory Terms":
            filtered = filtered[
                filtered["policy_terms_count"].apply(
                    lambda x: int(x) == 0 if str(x).isdigit() else True
                )
            ]

        st.caption(
            "Faithfulness scores (0-1) appear after running the Evaluation Pipeline with RAGAS. "
            "Scores >= 70% show as Grounded (green), < 70% as Not Grounded (red)."
        )

        total_traces = len(filtered)
        total_pages = max(1, (total_traces + TRACES_PER_PAGE - 1) // TRACES_PER_PAGE)

        page_col1, page_col2 = st.columns([3, 1])
        with page_col1:
            st.caption(f"Showing {total_traces} of {len(df)} traces")
        with page_col2:
            current_page = st.number_input(
                "Page", min_value=1, max_value=total_pages, value=1, key="browse_page"
            )

        start_idx = (current_page - 1) * TRACES_PER_PAGE
        end_idx = min(start_idx + TRACES_PER_PAGE, total_traces)
        page_df = filtered.iloc[start_idx:end_idx]

        for _, row in page_df.iterrows():
            ts = row.get("timestamp", "")
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(ts) else "N/A"

            sla_badge = ""
            sla_val = str(row.get("sla_pass", "")).lower()
            if sla_val == "true":
                sla_badge = " | :green[SLA Pass]"
            elif sla_val == "false":
                sla_badge = " | :red[SLA Breach]"

            ground_badge = ""
            ground_val = str(row.get("groundedness", ""))
            if ground_val and ground_val not in ("", "error"):
                try:
                    faith_score = float(ground_val)
                    if faith_score >= 0.6:
                        ground_badge = f" | :green[Grounded ({faith_score:.0%})]"
                    else:
                        ground_badge = f" | :red[Not Grounded ({faith_score:.0%})]"
                except (ValueError, TypeError):
                    if ground_val == "grounded":
                        ground_badge = " | :green[Grounded]"
                    elif ground_val == "not_grounded":
                        ground_badge = " | :red[Not Grounded]"

            guardrail_badge = ""
            guardrail_val = str(row.get("guardrail_blocked", "")).lower()
            if guardrail_val == "true":
                guardrail_badge = " | :orange[Guardrail Blocked]"

            label = (
                f"**{ts_str}** | "
                f"Prompt {row.get('prompt_version', '?')} | "
                f"{row.get('execution_time_ms', '?')} ms | "
                f"{row.get('status', '?')}"
                f"{sla_badge}{ground_badge}{guardrail_badge}"
            )
            with st.expander(label):
                st.markdown(f"**Trace ID:** `{row.get('trace_id', '')}`")
                st.markdown(f"**Model:** {row.get('model_name', 'N/A')} @ {row.get('model_endpoint', 'N/A')}")
                st.markdown(f"**Sources:** {row.get('source_documents', 'N/A')}")
                st.markdown(f"**App Version:** {row.get('app_version', 'N/A')}")

                compliance_parts = []
                if row.get("sla_pass"):
                    compliance_parts.append(f"SLA: {'Pass' if str(row['sla_pass']).lower() == 'true' else 'Breach'}")
                if row.get("latency_ms"):
                    compliance_parts.append(f"Latency: {row['latency_ms']}ms")
                if row.get("policy_terms_count"):
                    compliance_parts.append(f"Policy Terms: {row['policy_terms_count']}")
                if row.get("source_count"):
                    compliance_parts.append(f"Sources: {row['source_count']}")
                if row.get("groundedness"):
                    gv = row["groundedness"]
                    try:
                        compliance_parts.append(f"Faithfulness: {float(gv):.0%}")
                    except (ValueError, TypeError):
                        compliance_parts.append(f"Groundedness: {gv}")
                if str(row.get("guardrail_blocked", "")).lower() == "true":
                    compliance_parts.append("Guardrail: Blocked")

                if compliance_parts:
                    st.markdown(f"**Compliance:** {' | '.join(compliance_parts)}")

                st.markdown("---")
                st.markdown("**User Query:**")
                st.text(row.get("user_query", ""))
                st.markdown("**Response:**")
                st.text(row.get("response", ""))

        if total_pages > 1:
            st.caption(f"Page {current_page} of {total_pages}")

# ---- Evaluation Tab ----
with tab_eval:
    st.subheader("Run Evaluation")
    st.caption(
        "Generate traces and score them with LLM judges. "
        "In production, this runs automatically via a daily CronJob."
    )

    run_col1, run_col2 = st.columns([3, 2])
    with run_col1:
        st.markdown(
            "Evaluate recent chatbot traces with LLM judges (groundedness, relevance, "
            "faithfulness) and compare with previous runs to detect drift."
        )
    with run_col2:
        run_clicked = st.button(
            "Run Evaluation Pipeline", type="primary", use_container_width=True,
        )
        if run_clicked:
            result = submit_eval_pipeline()
            if result["state"] == "Submitted":
                st.session_state["active_pipeline_run"] = result["run_id"]
                st.success(result["message"])
            else:
                st.error(result["message"])

    active_run = st.session_state.get("active_pipeline_run")
    if active_run:
        run_status = get_pipeline_run_status(active_run)
        state = run_status["state"]
        if state in ("PENDING", "RUNNING", "Submitted"):
            st.info(f"Pipeline run `{active_run[:12]}...`: {run_status['message']}")
            time.sleep(8)
            st.rerun()
        elif state in ("SUCCEEDED", "Complete"):
            st.success(f"Pipeline run complete. Assessments attached to traces.")
            st.session_state.pop("active_pipeline_run", None)
            st.cache_data.clear()
        elif state in ("FAILED", "ERROR"):
            st.error(f"Pipeline run failed: {run_status['message']}")
            st.session_state.pop("active_pipeline_run", None)
        elif state in ("Unknown", "Error"):
            st.session_state.pop("active_pipeline_run", None)
        else:
            st.warning(f"Pipeline status: {state}")
            st.session_state.pop("active_pipeline_run", None)

    recent_runs = list_pipeline_runs()
    if recent_runs:
        with st.expander(f"Recent pipeline runs ({len(recent_runs)})"):
            for r in recent_runs[:10]:
                ts = r["created"].strftime("%Y-%m-%d %H:%M") if r["created"] else "?"
                st.text(f"{r['name']}  |  {r['state']}  |  {ts}")

    st.markdown("---")
    st.subheader("Evaluation Results")

    col_refresh, col_spacer = st.columns([1, 5])
    with col_refresh:
        if st.button("Refresh Results", key="refresh_eval"):
            st.cache_data.clear()
            st.rerun()

    eval_df = fetch_eval_runs(EVAL_EXPERIMENT_NAME)

    if not eval_df.empty:
        eval_df = eval_df[eval_df["num_questions"] > 0]

    if eval_df.empty:
        st.info("No evaluation runs found yet. Click 'Run Evaluation' above to start one.")
    else:
        st.markdown("### Prompt Version Comparison")

        metric_cols = [
            "avg_faithfulness",
        ]
        display_names = {
            "avg_faithfulness": "Faithfulness",
        }

        comparison_cols = ["run_name", "prompt_version", "num_questions"] + metric_cols + [
            "hallucination_rate", "source_accuracy", "avg_latency",
        ]
        available_cols = [c for c in comparison_cols if c in eval_df.columns]
        comparison = eval_df[available_cols].copy()

        col_renames = {
            "run_name": "Run", "prompt_version": "Prompt", "num_questions": "Questions",
            "avg_faithfulness": "Faithfulness",
            "hallucination_rate": "Hallucination %", "source_accuracy": "Source Accuracy",
            "avg_latency": "Latency (s)",
        }
        comparison = comparison.rename(columns={k: v for k, v in col_renames.items() if k in comparison.columns})

        if "Hallucination %" in comparison.columns:
            comparison["Hallucination %"] = (comparison["Hallucination %"] * 100).round(1)
        if "Source Accuracy" in comparison.columns:
            comparison["Source Accuracy"] = (comparison["Source Accuracy"] * 100).round(1)

        score_cols_display = [c for c in ["Faithfulness"] if c in comparison.columns]
        format_dict = {c: "{:.2f}" for c in score_cols_display}
        if "Hallucination %" in comparison.columns:
            format_dict["Hallucination %"] = "{:.1f}%"
        if "Source Accuracy" in comparison.columns:
            format_dict["Source Accuracy"] = "{:.1f}%"
        if "Latency (s)" in comparison.columns:
            format_dict["Latency (s)"] = "{:.2f}"

        styled = comparison.style.format(format_dict)
        if score_cols_display:
            styled = styled.background_gradient(
                subset=score_cols_display, cmap="RdYlGn", vmin=0, vmax=1,
            )
        st.dataframe(styled, use_container_width=True, hide_index=True)

        # RAGAS benchmark runs (with ground truth) shown separately
        benchmark_runs = eval_df[eval_df.get("has_ground_truth", "false") == "true"] if "has_ground_truth" in eval_df.columns else pd.DataFrame()
        if not benchmark_runs.empty:
            st.markdown("### RAGAS Benchmark Runs (with Ground Truth)")
            bench_cols = ["run_name", "prompt_version", "num_questions",
                          "avg_faithfulness", "avg_answer_relevancy", "avg_context_precision",
                          "avg_context_recall", "avg_factual_correctness"]
            bench_available = [c for c in bench_cols if c in benchmark_runs.columns]
            bench_df = benchmark_runs[bench_available].copy()
            bench_renames = {
                "run_name": "Run", "prompt_version": "Prompt", "num_questions": "Questions",
                "avg_faithfulness": "Faithfulness", "avg_answer_relevancy": "Ans Relevancy",
                "avg_context_precision": "Ctx Precision", "avg_context_recall": "Ctx Recall",
                "avg_factual_correctness": "Factual Corr.",
            }
            bench_df = bench_df.rename(columns={k: v for k, v in bench_renames.items() if k in bench_df.columns})
            bench_score_cols = [c for c in ["Faithfulness", "Ans Relevancy", "Ctx Precision", "Ctx Recall", "Factual Corr."] if c in bench_df.columns]
            bench_fmt = {c: "{:.2f}" for c in bench_score_cols}
            bench_styled = bench_df.style.format(bench_fmt)
            if bench_score_cols:
                bench_styled = bench_styled.background_gradient(subset=bench_score_cols, cmap="RdYlGn", vmin=0, vmax=1)
            st.dataframe(bench_styled, use_container_width=True, hide_index=True)

        st.markdown("### RAGAS Metrics by Run")
        chart_data = eval_df.melt(
            id_vars=["run_name", "prompt_version"],
            value_vars=[c for c in metric_cols if c in eval_df.columns],
            var_name="Metric",
            value_name="Score",
        )
        chart_data["Metric"] = chart_data["Metric"].map(display_names)

        fig = px.bar(
            chart_data,
            x="Metric",
            y="Score",
            color="run_name",
            barmode="group",
            labels={"Score": "Score (0-1)", "run_name": "Eval Run"},
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig.update_layout(
            height=400,
            margin=dict(t=10, b=10),
            yaxis_range=[0, 1.1],
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("Flagged Traces")
    st.caption("Traces flagged by the evaluation pipeline for compliance violations.")

    flagged_traces, analysis_summary = fetch_flagged_traces(EVAL_EXPERIMENT_NAME)

    if analysis_summary:
        v_counts = analysis_summary.get("violation_counts", {})
        v_rates = analysis_summary.get("violation_rates", {})
        trend = analysis_summary.get("trend_deltas", {})

        flag_c1, flag_c2, flag_c3, flag_c4 = st.columns(4)
        flag_c1.metric("Flagged Traces", len(flagged_traces))
        flag_c2.metric(
            "Not Grounded",
            v_counts.get("not_grounded", 0),
            help=f"{v_rates.get('not_grounded', 0):.1%} of traces",
        )
        flag_c3.metric(
            "SLA Breaches",
            v_counts.get("sla_breach", 0),
            help=f"{v_rates.get('sla_breach', 0):.1%} of traces",
        )
        flag_c4.metric(
            "Missing Policy Terms",
            v_counts.get("no_policy_language", 0),
            help=f"{v_rates.get('no_policy_language', 0):.1%} of traces",
        )

        if trend.get("volume_change_pct"):
            st.caption(
                f"Volume trend vs previous period: {trend['volume_change_pct']:+.1f}%"
            )

    if not flagged_traces:
        st.info(
            "No flagged traces found. Run the evaluation pipeline to analyze recent traces."
        )
    else:
        SEVERITY_COLORS = {
            "high": ":red",
            "medium": ":orange",
            "low": ":blue",
        }

        for ft in flagged_traces:
            severity = ft.get("severity", "medium")
            color = SEVERITY_COLORS.get(severity, ":orange")
            violations = ft.get("violations", [])
            ts_ms = ft.get("timestamp_ms", 0)
            ts_str = (
                datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
                if ts_ms
                else "N/A"
            )

            violation_labels = {
                "not_grounded": "Not Grounded",
                "sla_breach": "SLA Breach",
                "no_policy_language": "Missing Policy Terms",
            }
            violation_display = ", ".join(
                violation_labels.get(v, v) for v in violations
            )

            with st.expander(
                f"{color}[{severity.upper()}] {ts_str} -- {violation_display}"
            ):
                st.markdown(f"**Trace ID:** `{ft.get('trace_id', '')}`")
                st.markdown(f"**Severity:** {severity.upper()}")
                st.markdown(f"**Violations:**")
                for v in violations:
                    st.markdown(f"- {violation_labels.get(v, v)}")

# ---- Export Report Tab ----
with tab_export:
    st.subheader("Generate Compliance Report")

    if df.empty:
        st.info("No trace data available for export.")
    else:
        exp_col1, exp_col2 = st.columns(2)

        with exp_col1:
            export_date_range = st.date_input(
                "Report Date Range",
                value=(
                    df["timestamp"].min().date()
                    if df["timestamp"].notna().any()
                    else datetime.now().date() - timedelta(days=30),
                    df["timestamp"].max().date()
                    if df["timestamp"].notna().any()
                    else datetime.now().date(),
                ),
                key="export_date",
            )

        with exp_col2:
            export_format = st.selectbox(
                "Export Format",
                ["Excel (.xlsx) — Recommended", "CSV", "JSON"],
            )

        export_version_options = ["All"] + sorted(
            df["prompt_version"].dropna().unique().tolist()
        )
        export_version = st.selectbox(
            "Prompt Version Filter", export_version_options, key="export_version"
        )

        if st.button("Generate Report", type="primary"):
            export_df = df.copy()

            if isinstance(export_date_range, tuple) and len(export_date_range) == 2:
                start, end = export_date_range
                if "timestamp" in export_df.columns:
                    mask = export_df["timestamp"].dt.date.between(start, end)
                    export_df = export_df[mask]

            if export_version != "All":
                export_df = export_df[
                    export_df["prompt_version"] == export_version
                ]

            clean_df = build_export_dataframe(export_df)
            summary = build_summary(export_df)

            st.success(f"Report generated: {len(clean_df)} traces")

            if export_format.startswith("Excel"):
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    summary_data = {
                        "Metric": [
                            "Report Generated",
                            "Date Range",
                            "Total Interactions",
                            "Average Latency (ms)",
                            "Success Rate (%)",
                            "Prompt Versions Used",
                            "Models Used",
                        ],
                        "Value": [
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            f"{summary['date_range'][0]} to {summary['date_range'][1]}",
                            summary["total_interactions"],
                            summary["avg_latency_ms"],
                            summary["success_rate"],
                            ", ".join(summary["prompt_versions_used"]) or "N/A",
                            ", ".join(summary["models_used"]) or "N/A",
                        ],
                    }
                    pd.DataFrame(summary_data).to_excel(
                        writer, sheet_name="Summary", index=False
                    )
                    clean_df.to_excel(
                        writer, sheet_name="Traces", index=False
                    )
                buf.seek(0)
                st.download_button(
                    label="Download Excel Report",
                    data=buf,
                    file_name=f"audit_report_{datetime.now():%Y%m%d}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

            elif export_format == "CSV":
                csv_data = clean_df.to_csv(index=False)
                st.download_button(
                    label="Download CSV Report",
                    data=csv_data,
                    file_name=f"audit_report_{datetime.now():%Y%m%d}.csv",
                    mime="text/csv",
                )

            elif export_format == "JSON":
                json_output = {
                    "report_metadata": {
                        "generated_at": datetime.now().isoformat(),
                        "date_range": {
                            "from": summary["date_range"][0],
                            "to": summary["date_range"][1],
                        },
                        "total_interactions": summary["total_interactions"],
                        "avg_latency_ms": summary["avg_latency_ms"],
                        "success_rate_pct": summary["success_rate"],
                        "prompt_versions": summary["prompt_versions_used"],
                        "models": summary["models_used"],
                    },
                    "traces": json.loads(
                        clean_df.to_json(orient="records", date_format="iso")
                    ),
                }
                json_data = json.dumps(json_output, indent=2)
                st.download_button(
                    label="Download JSON Report",
                    data=json_data,
                    file_name=f"audit_report_{datetime.now():%Y%m%d}.json",
                    mime="application/json",
                )
