# RAG Governance POC

Red Hat AI Enterprise Governance & Control Plane -- Reusable Proof of Concept for regulated industries.

## Overview

This POC demonstrates **governance KPIs** using a policy-themed RAG application with MLflow tracing on RHOAI 3.4. It is designed to be re-skinned for any client by editing `project.env` and swapping sample documents.

| KPI | Description | Component | Status |
|-----|-------------|-----------|--------|
| **1.1 / 1.9.1** | Data lineage, source traceability, prompt release tracking | RAG App + MLflow Prompt Registry | Deployed |
| **1.2 / 1.5** | Automated evaluation, drift comparison, regression detection | Eval Runner + MLflow Evaluate | Deployed |
| **1.3** | Prompt and output logging + SIEM export | RAG App + MLflow Tracing + OTel docs (Splunk, Dynatrace, SCOM) | Deployed |
| **1.7** | Groundedness evaluation, hallucination scoring | Eval Runner + EvalHub RAGAS adapter (faithfulness, answer_relevancy) | Deployed |
| **2.1 / 2.2** | Evidence-based control compliance and self-service auditability | Audit Portal | Deployed |
| **4.1 / 4.2** | Application identification via AI gateway | MaaS Gateway + Observability | Demo + Docs |

## Architecture

```
Developer ──> Chainlit RAG Chat ──> RAG Pipeline ──> MaaS Model Endpoint
                                        │
                                        ├── FAISS Vector Store (policy docs)
                                        ├── MLflow Prompt Registry (versioned prompts)
                                        ├── MLflow Tracing (all interactions)
                                        └── Inline Compliance Checks (SLA, policy terms, source count)

Evaluator ──> KFP Pipeline (3-step) ──> MLflow
                  │
                  ├── Step 1: Score (EvalHub RAGAS: faithfulness, answer_relevancy + code-based: policy, latency)
                  ├── Step 2: Analyze (flag violations where faithfulness < 0.7, compute trends)
                  └── Step 3: Report (comparison, flagged traces, trend deltas)

EvalHub (TrustyAI) ──> RAGAS Adapter ──> Judge LLM
                           │
                           └── Runs in isolated container — no RAGAS dependency in app image

Auditor ──> Audit Portal (Streamlit) ──> MLflow API
                │
                ├── Dashboard (stats, charts)
                ├── Browse Traces (search, filter, compliance filters, drill-down)
                ├── Evaluation (results, flagged traces view)
                └── Export Report (Excel / CSV / JSON)

Admin ──> MaaS Gateway ──> Observability Dashboard
              │
              ├── Subscriptions + API keys (who has access)
              ├── Token usage per subscription (cost attribution)
              └── Request volume per model (utilisation)

Production path: MLflow ──OTLP──> OTel Collector ──> Splunk / Dynatrace
                                                  └──> SCOM (alerts via bridge)
```

## Components

### RAG Chat App (`rag-app/`)

Chainlit-based policy Q&A with full MLflow tracing and real-time compliance checks.

- **Pipeline steps visible in chat**: retrieval, prompt loading, LLM generation
- **Prompt versioning**: prompts registered in MLflow Prompt Registry
- **Data lineage**: every trace captures source documents, embedding model, prompt version, model endpoint, app version
- **Inline compliance checks**: every interaction is automatically checked for SLA compliance (< 10s), policy language presence, and source document coverage -- results stored as trace span attributes

### Audit Portal (`audit-portal/`)

Single Streamlit app for compliance/audit personas. Four tabs:

- **Dashboard**: interaction volume, latency, success rate, prompt version usage
- **Browse Traces**: searchable/filterable table with compliance filters (SLA status, groundedness, policy language) and expandable detail views with compliance badges
- **Evaluation**: evaluation results, prompt version comparison, per-question drill-down, and flagged traces view with severity-coded violations
- **Export Report**: date range + filters + download (Excel/CSV/JSON)

### Evaluation Module (`eval/`)

Batch evaluation runner and KFP pipeline for automated quality assessment, violation flagging, and drift detection.

- **eval_runner.py** -- runs RAG pipeline against test dataset, scores via EvalHub RAGAS adapter, logs to MLflow
- **eval_pipeline.py** -- KFP v2 3-step pipeline: Score -> Analyze & Flag -> Report
- **ragas_eval.py** -- full RAGAS benchmark via EvalHub (`ragas_rag_full`) with ground truth
- **test_dataset.json** -- 25 Q&A pairs derived from the sample policy documents
- RAGAS metrics via EvalHub: faithfulness, answer_relevancy (live traces); + context_recall, factual_correctness (benchmark with ground truth)
- **EvalHub integration**: RAGAS runs in an isolated adapter container via the TrustyAI EvalHub operator -- no RAGAS dependency in the app image
- **Compliance analysis**: automatic violation flagging (faithfulness < 0.7, SLA breach, missing policy terms) with trend comparison
- Supports cross-version comparison (run with different prompt versions and compare in MLflow)

### Kubernetes Manifests (`manifests/`)

- `namespace.yaml` -- POC namespace
- `rag-app.yaml` -- RAG app Deployment + Service + Route
- `audit-portal.yaml` -- Audit Portal Deployment + Service + Route
- `otel-collector.yaml` -- OTel Collector reference template (not deployed by default)

## Quick Start

### Prerequisites

- RHOAI 3.4 with MLflow operator enabled
- A model endpoint (MaaS inference gateway or InferenceService)
- `oc` CLI authenticated to the cluster

### Configuration

Edit `project.env` to set your project prefix, namespace, and cluster domain:

```bash
PROJECT_PREFIX=gov           # Change to your client prefix
NAMESPACE=gov-rag-poc        # Derived from prefix
CLUSTER_DOMAIN=apps.cluster.example.com
LLM_MODEL=qwen35-9b-awq
```

### Deploy

```bash
./deploy.sh
```

The script will:
1. Source `project.env` for naming conventions
2. Prompt for LLM endpoint, model name, and API key
3. Auto-detect the MLflow tracking URI
4. Build container images via OpenShift BuildConfig
5. Deploy both apps with Routes
6. Register the initial prompt version

### Access

- **RAG Chat App**: `https://<RAG_APP_NAME>-<NAMESPACE>.apps.<cluster>`
- **Audit Portal**: `https://<AUDIT_PORTAL_NAME>-<NAMESPACE>.apps.<cluster>`
- **MLflow UI**: via RHOAI dashboard

### Teardown

```bash
./deploy.sh --delete
```

## Re-skinning for a New Client

1. Edit `project.env` -- set `PROJECT_PREFIX`, `CLUSTER_DOMAIN`, `LLM_MODEL`
2. Replace `rag-app/sample_docs/*.md` with your client's policy documents
3. Update `eval/test_dataset.json` with Q&A pairs matching the new documents
4. Optionally set `POLICY_TERMS` env var with domain-specific compliance keywords
5. Run `./deploy.sh`

## Demo

See [docs/DEMO-RUNBOOK.md](docs/DEMO-RUNBOOK.md) for step-by-step demo scripts for all KPIs.

## Gateway Inventory (KPI 4.1/4.2)

See [docs/KPI-4-GATEWAY-INVENTORY.md](docs/KPI-4-GATEWAY-INVENTORY.md) for the application identification demo script, including CLI commands, dashboard navigation, and gap documentation.

## OTel / SIEM Integration

See [docs/OTEL-SIEM-INTEGRATION.md](docs/OTEL-SIEM-INTEGRATION.md) for the production export pattern, including configurations for Splunk, Dynatrace, and SCOM gap documentation.

## Running Evaluations

```bash
# Install eval dependencies
pip install -r eval/requirements.txt

# Set environment variables
export LLM_ENDPOINT="https://<model>.<CLUSTER_DOMAIN>/v1"
export LLM_JUDGE_ENDPOINT="http://<model>-predictor.<namespace>.svc.cluster.local/v1"
export LLM_MODEL="qwen35-9b-awq"
export LLM_API_KEY="unused"
export MLFLOW_TRACKING_URI="https://rh-ai.<CLUSTER_DOMAIN>/mlflow"
export MLFLOW_TRACKING_INSECURE_TLS="true"
export MLFLOW_TRACKING_TOKEN="$(oc whoami -t)"
export MLFLOW_WORKSPACE="<NAMESPACE>"
export OPENAI_API_KEY="unused"

# Run evaluation with prompt v1 (EvalHub RAGAS: faithfulness, answer_relevancy)
python eval/eval_runner.py --prompt-version 1

# Run with prompt v2 and compare in MLflow
python eval/eval_runner.py --prompt-version 2

# Run full RAGAS benchmark via EvalHub (ragas_rag_full: all metrics incl. context_recall, factual_correctness)
python eval/ragas_eval.py -p 1
python eval/ragas_eval.py -p 2
```

Results appear in the `rag-governance-poc` experiment in MLflow. Use the Compare view to see drift across prompt versions.

## Out of Scope

These KPIs are handled by other team members:

| KPI | Description | Owner |
|-----|-------------|-------|
| 1.4 | Access revocation / kill switch | MaaS API key management |
| 1.6 | Hard-coded guardrails | NeMo Guardrails / TrustyAI |
| 3.1 / 3.2 | Token budgets, QoS controls | MaaS rate limiting |

## Future Extensions

- **OTel Collector deployment**: one manifest + one env var on MLflow. See docs.
- **Additional policy documents**: drop `.md` files into `rag-app/sample_docs/` and redeploy.
- **CI/CD integration**: run `eval_runner.py` in a pipeline to gate prompt releases on quality thresholds.
- **Alerting**: configure threshold-based alerts on violation rates (e.g., groundedness drop > 10% triggers notification).
