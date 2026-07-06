# ANZ NZ Governance POC

Red Hat AI Enterprise Governance & Control Plane -- Proof of Concept for ANZ Bank New Zealand.

## Scope

This POC demonstrates three governance KPIs using a banking-themed RAG application with MLflow tracing on RHOAI 3.4:

| KPI | Description | Component |
|-----|-------------|-----------|
| **1.1 / 1.9.1** | Data lineage, source traceability, prompt release tracking | RAG App + MLflow Prompt Registry |
| **1.3** | Prompt and output logging | RAG App + MLflow Tracing + OTel docs |
| **2.1 / 2.2** | Evidence-based control compliance and self-service auditability | Audit Portal |

## Architecture

```
Developer ──> Chainlit RAG Chat ──> RAG Pipeline ──> MaaS Model Endpoint
                                        │
                                        ├── FAISS Vector Store (banking policy docs)
                                        ├── MLflow Prompt Registry (versioned prompts)
                                        └── MLflow Tracing (all interactions)

Auditor ──> Audit Portal (Streamlit) ──> MLflow API
                │
                ├── Dashboard (stats, charts)
                ├── Browse Traces (search, filter, drill-down)
                └── Export Report (Excel / CSV / JSON)

Production path: MLflow ──OTLP──> OTel Collector ──> Enterprise SIEM
```

## Components

### RAG Chat App (`rag-app/`)

Chainlit-based banking policy Q&A with full MLflow tracing.

- **Pipeline steps visible in chat**: retrieval, prompt loading, LLM generation
- **Prompt versioning**: prompts registered in MLflow Prompt Registry
- **Data lineage**: every trace captures source documents, embedding model, prompt version, model endpoint, app version

### Audit Portal (`audit-portal/`)

Single Streamlit app for compliance/audit personas. Three tabs:

- **Dashboard**: interaction volume, latency, success rate, prompt version usage
- **Browse Traces**: searchable/filterable table with expandable detail views
- **Export Report**: date range + filters + download (Excel/CSV/JSON)

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

### Deploy

```bash
./deploy.sh
```

The script will:
1. Prompt for LLM endpoint, model name, and API key
2. Auto-detect the MLflow tracking URI
3. Build container images via OpenShift BuildConfig
4. Deploy both apps with Routes
5. Register the initial prompt version

### Access

- **RAG Chat App**: `https://anz-rag-app-anz-governance-poc.apps.<cluster>`
- **Audit Portal**: `https://anz-audit-portal-anz-governance-poc.apps.<cluster>`
- **MLflow UI**: via RHOAI dashboard

### Teardown

```bash
./deploy.sh --delete
```

## Demo

See [docs/DEMO-RUNBOOK.md](docs/DEMO-RUNBOOK.md) for step-by-step demo scripts for each KPI.

## OTel / SIEM Integration

See [docs/OTEL-SIEM-INTEGRATION.md](docs/OTEL-SIEM-INTEGRATION.md) for the production export pattern.

## Out of Scope

These KPIs are handled by other team members:

| KPI | Description | Owner |
|-----|-------------|-------|
| 1.2 / 1.5 | Model safety, drift, regression comparison | Evaluation workflows |
| 1.4 | Access revocation / kill switch | MaaS API key management |
| 1.6 | Hard-coded guardrails | NeMo Guardrails / TrustyAI |
| 1.7 | Groundedness evaluation | lm-eval + LLM-as-judge |
| 3.1 / 3.2 | Token budgets, QoS controls | MaaS rate limiting |
| 4.1 / 4.2 | Application identification, CMDB | Product gap |

## Future Extensions

- **Automated evaluation** (`eval/eval_runner.py`): batch test suite with LLM-as-judge scoring. Imports existing `rag_pipeline.query()` -- no code changes needed.
- **OTel Collector deployment**: one manifest + one env var on MLflow. See docs.
- **Additional policy documents**: drop `.md` files into `rag-app/sample_docs/` and redeploy.
