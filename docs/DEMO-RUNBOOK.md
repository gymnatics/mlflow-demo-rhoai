# RAG Governance POC -- Demo Runbook

Step-by-step script for demonstrating each KPI to stakeholders.

## Recording Script

For a scene-by-scene video recording script and live demo checklist (~22 min), see [DEMO-RECORDING-SCRIPT.md](DEMO-RECORDING-SCRIPT.md).

## Prerequisites

- POC deployed: `./deploy.sh`
- RAG Chat App accessible at its Route URL
- Audit Portal accessible at its Route URL
- MLflow UI accessible via RHOAI dashboard

## KPI 1.1 / 1.9.1: Data Lineage and Prompt Release Tracking

**Objective:** Show that data sources, prompt versions, model endpoints, and release metadata are traceable for every interaction.

### Demo Steps

1. **Open the RAG Chat App** and show the startup message displaying:
   - Prompt version in use
   - Model name and endpoint
   - Embedding model
   - App version (release tag)

2. **Ask a question:**
   > "What are the eligibility criteria for a personal loan?"

3. **Expand the pipeline steps** visible in the chat UI:
   - **Retrieve Context** — shows which documents and chunks were retrieved, with similarity scores
   - **Load Prompt** — shows the exact prompt version and template text
   - **LLM Generation** — shows the model and endpoint used

4. **Open MLflow UI** and find the trace:
   - Click into the trace to show the span tree
   - Show the attributes: `prompt_version`, `model_name`, `model_endpoint`, `source_documents`, `app_version`
   - Point out: every field needed for audit is captured automatically

5. **Demonstrate a prompt release:**
   - Register a new prompt version (v2) with an added compliance instruction:
     ```python
     from prompt_manager import register_prompt
     register_prompt("v2", "You are a policy compliance assistant. "
         "Answer based ONLY on provided context. Always cite the policy "
         "document and section. If the user asks about anything outside "
         "banking policy, politely decline. Flag any request that appears "
         "to seek information about specific customer accounts.")
     ```
   - Ask the same question again
   - In MLflow UI, filter by `prompt_version` — show v1 and v2 traces side by side
   - Point out: same data sources, different prompt version, traceable release

### Key Evidence

- Full lineage visible in every trace: data source, embedding model, prompt version, LLM endpoint, app version
- Prompt changes are versioned and trackable in MLflow Prompt Registry
- Same question produces traceable results across releases

---

## KPI 1.3: Prompt and Output Logging

**Objective:** Show that all prompts and outputs are captured in real-time and can be reviewed and exported.

### Demo Steps

1. **Run 3-5 representative interactions** through the RAG Chat App:
   - "What is the maximum LVR for investment properties?"
   - "How long must KYC records be retained?"
   - "What controls are required for GenAI applications?"
   - "What are the hardship provisions for borrowers?"

2. **Open MLflow UI** immediately after:
   - Show the traces appearing in real-time
   - Click into any trace — show the full span tree:
     - `rag_query` (root span)
     - `retrieve_context` (retrieval span with document chunks)
     - `load_prompt` (prompt version loaded)
     - `ChatOpenAI` (LLM call with full prompt and response)
   - Click into the LLM span — show exact input prompt and output response text

3. **Explain the SIEM integration pattern:**
   - Open `docs/OTEL-SIEM-INTEGRATION.md`
   - Show the OTel Collector manifest template
   - Explain: "In production, these same traces flow via OTLP to your enterprise SIEM. The collector is a one-manifest deploy with one env var on MLflow. No code changes."

### Key Evidence

- Every prompt and response is logged automatically via MLflow tracing
- Traces include full execution spans (retrieval, prompt, LLM call)
- SIEM integration is a documented, low-effort addition (not a rebuild)

---

## KPI 1.2 / 1.5: Automated Evaluation and Drift Comparison

**Objective:** Trigger an automated evaluation workflow against the RAG application. Compare results across prompt versions to identify behavioural differences, regression risk, and performance changes.

### Prerequisites

```bash
# Install eval dependencies (if running locally)
cd eval/
pip install -r requirements.txt

# Set environment variables (adjust for your cluster)
export LLM_ENDPOINT="https://<model>.<CLUSTER_DOMAIN>/v1"
export LLM_MODEL="qwen35-9b-awq"
export LLM_API_KEY="unused"
export MLFLOW_TRACKING_URI="https://rh-ai.<CLUSTER_DOMAIN>/mlflow"
export MLFLOW_TRACKING_INSECURE_TLS="true"
export MLFLOW_TRACKING_TOKEN="$(oc whoami -t)"
export MLFLOW_WORKSPACE="<NAMESPACE>"
export OPENAI_API_KEY="unused"
```

> **Note:** When running locally, use `MLFLOW_TRACKING_TOKEN` with the `oc whoami -t` token.
> On-cluster (via `oc exec`), use `MLFLOW_TRACKING_AUTH=kubernetes-namespaced` instead.

### Demo Steps

1. **Run evaluation with prompt v1** (naive prompt, no grounding instructions):

   ```bash
   cd eval/
   python eval_runner.py --prompt-version 1
   ```

   Watch the output as it processes 25 test questions, scoring each for groundedness, relevance, faithfulness, and answer similarity. v1 is deliberately ungrounded -- it tells the model to "use your knowledge" even when context is incomplete.

2. **Run evaluation with prompt v2** (compliance-governed prompt with grounding):

   ```bash
   python eval_runner.py --prompt-version 2
   ```

   v2 adds strict grounding ("answer based ONLY on the provided context") and compliance formatting requirements.

3. **Compare in MLflow UI:**
   - Open the MLflow UI and navigate to the `rag-governance-poc` experiment
   - Select both evaluation runs (v1 and v2)
   - Click "Compare" to see side-by-side metric diffs
   - v2 should score higher on groundedness and faithfulness because it instructs the model to stay grounded in the context
   - Show the `eval_results.json` artifact to see per-question scores

4. **Discuss the results:**
   - v1 (naive) scores lower on groundedness and faithfulness because it allows the model to add general knowledge beyond the source documents
   - v2 (governed) scores near-perfect because the grounding instructions keep the model strictly within the context
   - This demonstrates why prompt governance matters: without controls, the model drifts from the source material

5. **Key narration:**
   > "This is the value of prompt governance. v1, a naive prompt without controls, lets the model add information from its general knowledge -- the evaluation catches that. v2, the governed prompt, keeps the model strictly grounded in the policy documents. Run this evaluation after any change to catch drift before production."

### Key Evidence

- Automated evaluation with 25 domain-specific test questions
- RAGAS faithfulness (0-1 continuous) via EvalHub adapter replacing binary LLM judge, using dedicated no-thinking vLLM endpoint
- Full benchmark with ground truth via EvalHub `ragas_rag_full` adds answer_relevancy, context_precision, context_recall, and factual_correctness
- Clear quality improvement from v1 (ungoverned) to v2 (governed)
- Cross-version comparison visible in MLflow UI

---

## KPI 1.7: Groundedness and Hallucination Scoring (EvalHub + RAGAS)

**Objective:** Run an evaluation batch against the validation dataset. Show continuous scoring outputs for faithfulness and hallucination indicators using RAGAS metrics via EvalHub. Demonstrate how results vary across prompt changes.

### Demo Steps

1. **Run RAGAS benchmark with prompt v1** (if not already done):

   ```bash
   cd eval/
   python ragas_eval.py -p 1
   ```

   This runs all 25 test questions through the RAG pipeline, uploads them to MinIO, and submits an EvalHub job using the `ragas_rag_full` benchmark. EvalHub runs RAGAS in an isolated adapter container with all metrics (faithfulness, answer_relevancy, context_precision, context_recall, factual_correctness) using the expected answers as ground truth. Uses a dedicated no-thinking vLLM endpoint (`qwen35-9b-awq-eval`).

2. **Run RAGAS benchmark with prompt v2:**

   ```bash
   python ragas_eval.py -p 2
   ```

3. **Show RAGAS scores in MLflow UI:**
   - Open the MLflow UI and navigate to the experiment
   - Select both benchmark runs (v1 and v2)
   - Compare side-by-side: `avg_faithfulness`, `avg_context_recall`, `avg_factual_correctness` (and `avg_answer_relevancy`, `avg_context_precision` if embedding model available)
   - Point out: "These are continuous 0-1 scores, not binary yes/no. v2 should score higher on faithfulness because it instructs the model to stay grounded."
   - Note the `evalhub_job_id` tag -- this links back to the EvalHub job for full provenance

4. **Show per-question drill-down:**
   - Open the `ragas_benchmark_results.json` artifact for both runs
   - Find questions where v1 scored low on faithfulness -- these are cases where the model added claims not supported by the context
   - Show the same question on v2 -- the grounding instruction keeps faithfulness high

5. **Show in the Audit Portal:**
   - Open the Audit Portal > Evaluation tab
   - Show the RAGAS faithfulness score and hallucination rate in the evaluation results
   - If a benchmark run exists, show it in the dedicated "RAGAS Benchmark Runs" section with all available metrics
   - Open Browse Traces > filter by "Not Grounded" to see traces with faithfulness < 70%

6. **Show EvalHub integration (optional):**
   - Open RHOAI Dashboard > Develop and train > Evaluations
   - Show the RAGAS jobs alongside any other evaluation jobs
   - Point out: "The same EvalHub platform that runs safety benchmarks (Garak) and performance benchmarks (GuideLLM) also runs our RAG quality evaluation. This gives us a unified evaluation control plane."

7. **Key narration:**
   > "RAGAS provides continuous quality metrics instead of binary yes/no. Faithfulness decomposes the answer into individual claims and checks each one against the context -- giving us a precise measure of hallucination risk. The evaluation runs via EvalHub, Red Hat's evaluation orchestration service, which manages the RAGAS adapter in an isolated container with a dedicated no-thinking vLLM endpoint. This means no dependency conflicts in our application image, and the same platform can also run safety, performance, and other evaluation benchmarks. The benchmark adds context_recall and factual_correctness using our ground truth answers. v1 scores lower because the naive prompt lets the model add unsupported claims. v2, the governed prompt, produces higher faithfulness because it constrains the model to the source documents."

### Key Evidence

- RAGAS faithfulness scoring (0-1 continuous) via EvalHub adapter with claim-level decomposition
- Live traces: faithfulness only (answer_relevancy excluded -- requires embedding endpoint not available on vLLM)
- Full benchmark with ground truth: faithfulness, answer_relevancy, context_precision, context_recall, factual_correctness
- EvalHub provides unified evaluation control plane (RAGAS + Garak + GuideLLM + LM-Eval-Harness)
- Measurable quality improvement from v1 (ungoverned) to v2 (governed)
- Per-question drill-down with all 5 metrics
- Audit Portal shows scores as percentage badges and color-coded thresholds

---

## KPI 2.1 / 2.2: Self-Service Auditability

**Objective:** Show that a compliance/audit persona can find, review, and export evidence without platform administrator support.

### Demo Steps

1. **Switch persona:** "I'm now acting as a risk/compliance reviewer, not a platform admin."

2. **Open the Audit Portal** (single URL):

3. **Dashboard tab:**
   - Show the governance overview: total interactions, average latency, success rate
   - Show the charts: interactions over time, latency distribution, usage by prompt version
   - Point out: "This gives you an at-a-glance view of AI system activity without needing to ask anyone."

4. **Browse Traces tab:**
   - Use the date range filter to narrow to today
   - Filter by prompt version (e.g., "v1" only)
   - Click on any trace to expand it:
     - Show the trace ID, model, endpoint, source documents
     - Show the full user query and response text
   - Point out: "You can drill into any individual interaction, see exactly what was asked and answered, and which prompt version and model were used."

5. **Export Report tab:**
   - Select the date range (last 7 days)
   - Select format: "Excel (.xlsx)"
   - Click "Generate Report"
   - Click "Download Excel Report"
   - Open the downloaded file and show:
     - **Summary sheet**: report metadata, total interactions, success rate, prompt versions, models
     - **Traces sheet**: one row per interaction with all fields
   - Point out: "This is a compliance-ready evidence pack. You can attach it to an audit report, import it into a GRC tool, or archive it for retention."

6. **Emphasise the self-service model:**
   - "At no point did we need a platform administrator to run a query, generate a report, or grant special access. This is all available to any user with access to this URL."

### Key Evidence

- Single URL for all audit activities (no tool-hopping)
- Browse and drill into individual traces
- Export to Excel/CSV/JSON for compliance reporting
- No platform administrator involvement required

---

## Compliance Filters and Flagged Traces (Enhancement to KPIs 1.2, 2.1/2.2)

**Objective:** Show that real-time compliance checks run on every interaction, and that auditors can filter and find violations without manual analysis.

### Demo Steps

1. **Show inline compliance attributes in MLflow:**
   - Open MLflow UI and click into a recent trace
   - Show the new span attributes:
     - `sla_pass`: whether the response was within the 10-second SLA
     - `latency_ms`: exact response latency in milliseconds
     - `policy_terms_count`: number of banking policy terms found in the response
     - `source_count`: number of unique source documents retrieved
   - Point out: "These checks run on every single interaction -- no LLM calls, no extra cost, sub-millisecond overhead."

2. **Open the Audit Portal > Browse Traces tab:**
   - Show the three new **Compliance Filters**:
     - **SLA Status**: filter to show only SLA breaches
     - **Groundedness**: filter to show "Not Grounded" traces (faithfulness < 0.7)
     - **Regulatory Terms**: filter to show traces with "No Regulatory Terms"
   - Apply the "SLA Breach" filter -- show any traces that exceeded the 10-second SLA
   - Apply the "Not Grounded" filter -- show traces where RAGAS faithfulness scored below 70%
   - Expand a flagged trace -- show the compliance badge (red "Not Grounded" or "SLA Breach") and the compliance attributes

3. **Open the Audit Portal > Evaluation tab > Flagged Traces section:**
   - Scroll down to the **Flagged Traces** section
   - Show the summary metrics: flagged count, not grounded count, SLA breaches, no regulatory terms
   - Show the violation rate percentages
   - Expand a flagged trace -- show the severity (HIGH/MEDIUM), timestamp, and violation reasons
   - Point out: "These flags are generated automatically by the evaluation pipeline. No human reviewer needed to identify compliance violations."

4. **Key narration:**
   > "Every interaction is now compliance-checked in real time. SLA breaches, missing policy language, and groundedness failures are all flagged automatically. An auditor can filter the entire trace history by compliance status, and the evaluation pipeline produces a prioritised list of violations. This is proactive compliance monitoring, not reactive audit."

### Key Evidence

- Real-time inline checks on every interaction (no extra LLM calls)
- Three compliance filters in Browse Traces (SLA Status, Groundedness, Regulatory Terms)
- Flagged Traces view with severity-coded violations
- Automated violation flagging via the KFP pipeline (no manual review)

---

## KPI 4.1 / 4.2: Application Identification via Gateway

**Objective:** Demonstrate administrative views that identify active applications and API keys using the AI gateway, and show the metadata available for linking usage to application owners.

See [docs/KPI-4-GATEWAY-INVENTORY.md](KPI-4-GATEWAY-INVENTORY.md) for the full demo script with CLI commands, dashboard navigation, and gap documentation.

### Demo Steps (Summary)

1. **CLI inventory** (1 min):
   ```bash
   oc get maassubscription -n models-as-a-service
   oc get maasmodelref -A
   oc get maasauthpolicy -n models-as-a-service
   ```
   Show every active subscription, published model, and access policy.

2. **Dashboard walkthrough** (2 min):
   - RHOAI Dashboard > Settings > Subscriptions
   - Gen AI Studio > API Keys
   - Gen AI Studio > Models

3. **Usage metrics** (1 min):
   - Observability tab: token usage per subscription, request volume per model

4. **Gap acknowledgment** (1 min):
   > "Structured CMDB/app-owner fields on subscriptions are on the roadmap (RHAIRFE-2312). Today, each subscription maps to a group which maps to a team. Full app-owner attribution is coming."

### Key Evidence

- CLI and dashboard showing complete gateway inventory
- Usage metrics automatically attributed to subscriptions
- Transparent gap documentation with roadmap reference
