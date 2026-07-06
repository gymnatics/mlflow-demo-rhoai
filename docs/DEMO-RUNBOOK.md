# ANZ NZ Governance POC -- Demo Runbook

Step-by-step script for demonstrating each KPI to ANZ stakeholders.

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
   > "What are the eligibility criteria for a personal loan at ANZ?"

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
     register_prompt("v2", "You are a banking policy assistant for ANZ NZ. "
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
