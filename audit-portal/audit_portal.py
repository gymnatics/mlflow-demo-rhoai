"""Audit Portal: single Streamlit app for governance trace browsing and report export."""

import os
import io
import json
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import mlflow

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
MLFLOW_WORKSPACE = os.getenv("MLFLOW_WORKSPACE", "")
EXPERIMENT_NAME = os.getenv("MLFLOW_EXPERIMENT_NAME", "anz-rag-governance-poc")

mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
if MLFLOW_WORKSPACE:
    mlflow.set_workspace(MLFLOW_WORKSPACE)

st.set_page_config(
    page_title="ANZ Governance Audit Portal",
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

    traces = client.search_traces(
        experiment_ids=[experiment.experiment_id],
        max_results=100,
    )

    if not traces:
        return pd.DataFrame()

    rows = []
    for trace in traces:
        info = trace.info
        root_span = trace.data.spans[0] if trace.data.spans else None

        attrs = {}
        if root_span and root_span.attributes:
            attrs = dict(root_span.attributes)

        status_raw = str(info.status) if info.status else "UNKNOWN"
        status_clean = status_raw.replace("TraceStatus.", "")

        row = {
            "trace_id": info.request_id,
            "timestamp": datetime.fromtimestamp(info.timestamp_ms / 1000)
            if info.timestamp_ms
            else None,
            "status": status_clean,
            "execution_time_ms": info.execution_time_ms,
            "prompt_version": attrs.get("prompt_version", ""),
            "model_name": attrs.get("model_name", ""),
            "model_endpoint": attrs.get("model_endpoint", ""),
            "source_documents": attrs.get("source_documents", ""),
            "app_version": attrs.get("app_version", ""),
            "num_spans": len(trace.data.spans) if trace.data.spans else 0,
        }

        if root_span:
            inputs = root_span.inputs
            outputs = root_span.outputs
            if isinstance(inputs, dict):
                row["user_query"] = inputs.get("user_question", str(inputs))
            elif inputs is not None:
                row["user_query"] = str(inputs)
            else:
                row["user_query"] = ""

            if isinstance(outputs, dict):
                row["response"] = outputs.get("answer", str(outputs))
            elif outputs is not None:
                row["response"] = str(outputs)
            else:
                row["response"] = ""
        else:
            row["user_query"] = ""
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
# UI
# ---------------------------------------------------------------------------

st.title("ANZ Governance Audit Portal")
st.caption("Self-service trace browsing and compliance report generation")

df = fetch_traces(EXPERIMENT_NAME)

tab_dashboard, tab_browse, tab_export = st.tabs(
    ["Dashboard", "Browse Traces", "Export Report"]
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

# ---- Browse Traces Tab ----
TRACES_PER_PAGE = 20

with tab_browse:
    if df.empty:
        st.info("No traces available.")
    else:
        st.subheader("Filter Traces")

        filter_col1, filter_col2, filter_col3 = st.columns(3)

        with filter_col1:
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

        with filter_col2:
            version_options = ["All"] + sorted(
                df["prompt_version"].dropna().unique().tolist()
            )
            selected_version = st.selectbox("Prompt Version", version_options)

        with filter_col3:
            status_options = ["All"] + sorted(
                df["status"].dropna().unique().tolist()
            )
            selected_status = st.selectbox("Status", status_options)

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
            label = (
                f"**{ts_str}** | "
                f"Prompt {row.get('prompt_version', '?')} | "
                f"{row.get('execution_time_ms', '?')} ms | "
                f"{row.get('status', '?')}"
            )
            with st.expander(label):
                st.markdown(f"**Trace ID:** `{row.get('trace_id', '')}`")
                st.markdown(f"**Model:** {row.get('model_name', 'N/A')} @ {row.get('model_endpoint', 'N/A')}")
                st.markdown(f"**Sources:** {row.get('source_documents', 'N/A')}")
                st.markdown(f"**App Version:** {row.get('app_version', 'N/A')}")
                st.markdown("---")
                st.markdown("**User Query:**")
                st.text(row.get("user_query", ""))
                st.markdown("**Response:**")
                st.text(row.get("response", ""))

        if total_pages > 1:
            st.caption(f"Page {current_page} of {total_pages}")

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
                    file_name=f"anz_audit_report_{datetime.now():%Y%m%d}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

            elif export_format == "CSV":
                csv_data = clean_df.to_csv(index=False)
                st.download_button(
                    label="Download CSV Report",
                    data=csv_data,
                    file_name=f"anz_audit_report_{datetime.now():%Y%m%d}.csv",
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
                    file_name=f"anz_audit_report_{datetime.now():%Y%m%d}.json",
                    mime="application/json",
                )
