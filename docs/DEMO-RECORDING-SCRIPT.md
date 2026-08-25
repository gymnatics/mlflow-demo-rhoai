# Full Demo Recording Script and Live Checklist

## Pre-Recording Setup (do this BEFORE hitting record)

1. **Ensure eval results already exist** -- ask 3-5 chatbot questions first, then click "Run Evaluation Pipeline" in the Audit Portal's Evaluation tab. Wait ~3-5 minutes for the 3-step KFP pipeline to complete (RAGAS faithfulness scoring + violation flagging + comparison report). This is all you need -- no CLI or `eval_runner.py` required.
2. **Open these tabs in your browser** (in order, left to right):
   - Tab 1: RAG Chatbot (`https://<RAG_APP_NAME>-<NAMESPACE>.<CLUSTER_DOMAIN>`)
   - Tab 2: Audit Portal (`https://<AUDIT_PORTAL_NAME>-<NAMESPACE>.<CLUSTER_DOMAIN>`)
   - Tab 3: MLflow UI (`https://rh-ai.<CLUSTER_DOMAIN>/mlflow`)
   - Tab 4: RHOAI Dashboard (`https://rh-ai.<CLUSTER_DOMAIN>`)
   - Tab 5: Terminal (for CLI commands)
3. **Clear old chat sessions** in the chatbot (refresh the page)
4. **Set chatbot to prompt v2** (governed) via the gear icon
5. **Verify the model is warm** -- ask a quick test question in the chatbot, delete it

## Recording Script (Total: ~23 minutes)

---

### Scene 1: Platform Overview (3 min)

**Tab: RHOAI Dashboard**

- Show the RHOAI dashboard home
- Navigate to: Model Serving > show the Qwen model deployed
- Navigate to: Gen AI Studio > show model playground and API keys
- Navigate to: Data Science Pipelines > show the eval pipeline is registered

**Narration:**
> "This is Red Hat OpenShift AI -- the single pane of glass for AI governance. From here, you can see every model deployed, who can access it, how it's being used, and the full trace of every interaction. Let me walk you through each layer, starting with the AI application itself."

---

### Scene 2: Demo Group A -- RAG Chatbot with Guardrails (5 min)

**KPIs covered: 1.2/1.5 (Model Safety, Drift & Regression) | 1.6 (Hard-Coded Guardrails)**

**Tab: RAG Chatbot**

**Part A: Governed Behaviour (2 min)**

- Show the startup message (prompt version v2, model, embedding model, app version)
- Ask: "What are the eligibility criteria for a personal loan?"
- Wait for response
- Expand the pipeline steps:
  - "Retrieve Context" -- show similarity scores and source documents
  - "Load Prompt" -- show the governed prompt version and template
  - "LLM Generation" -- show model name and endpoint
- Point out: structured response, grounded in policy documents, cites sources

**Narration:**
> "This is the governed experience. The prompt instructs the model to answer ONLY from the retrieved policy documents. Every step is visible: retrieval, prompt loading, generation. The response is structured, grounded, and cites the source."

**Part B: Ungoverned Behaviour -- Drift Demo (1.5 min)**

- Click the gear icon, switch to prompt v1 (naive/ungoverned)
- Ask the same question again
- Note the different response (less structured, may add general knowledge beyond the documents)
- Point out the contrast: v1 may hallucinate or add information not in the source docs

**Narration:**
> "Now I've switched to an ungoverned prompt -- no grounding instructions. Same question, but the model may add general knowledge beyond the policy documents. This is drift. Without prompt governance, the model behaviour is unpredictable. The evaluation pipeline catches this automatically -- we'll see that shortly."

**Part C: Guardrails (1.5 min)**

- Switch back to prompt v2
- Ask a question designed to elicit PII-adjacent content (e.g., "Can you show me an example of a customer loan application with contact details?")
- Show the guardrails intercepting -- NeMo blocks PII content (email, phone, credit card)
- Point out: the response is safe, PII is blocked at the output rail level

**Narration:**
> "Now let me show the safety layer. I'm asking something that might surface personal information. Watch -- the NeMo Guardrails intercept and block any PII in the output. Email, phone numbers, credit card numbers -- all blocked. This is defence in depth: even if the model generates something it shouldn't, the guardrails catch it. Two independent safety layers working together."

---

### Scene 3: Demo Group B -- Audit Portal (5 min)

**KPIs covered: 2.1/2.2 (Evidence-Based Control Compliance & Self-Service Auditability)**

**Tab: Audit Portal**

**Narration (transition):**
> "So that's the user experience -- safe, controlled, traceable. Now let me switch personas. I'm a risk or compliance reviewer. I need to see what's happening with AI in my organisation. One URL, four capabilities."

**Part A: Dashboard (1 min)**

- Show the Dashboard tab:
  - Compliance Overview: SLA pass rate, groundedness score, regulatory terms count
  - Interaction volume over time
  - Latency distribution
  - Usage by prompt version

**Narration:**
> "At a glance: how many interactions, what's the SLA compliance rate, what's the average groundedness score. No CLI, no Python -- just a dashboard."

**Part B: Browse Traces with Compliance Filters (2 min)**

- Switch to Browse Traces tab
- Show the three compliance filters:
  - **SLA Status**: filter to "Breach" -- show any traces exceeding 10s
  - **Groundedness**: filter to "Not Grounded" -- show traces with faithfulness < 70%
  - **Regulatory Terms**: filter to "No Regulatory Terms" -- show traces missing banking policy language
- Expand a flagged trace:
  - Show compliance badge (red "Not Grounded" or "SLA Breach")
  - Show the full query and response text
  - Show compliance attributes (latency_ms, policy_terms_count, sla_pass)

**Narration:**
> "Three compliance filters. I can instantly find SLA breaches, potential hallucinations, or responses missing regulatory language. Click into any trace -- see the full interaction, the compliance badges, and all the metadata. No admin access needed."

**Part C: Evaluation Tab (1 min)**

- Switch to Evaluation tab
- Show evaluation results table (colour-coded metrics)
- Scroll to Flagged Traces section:
  - Show flagged count, violation types
  - Show severity-coded entries (HIGH/MEDIUM)

**Narration:**
> "The evaluation pipeline automatically identifies violations. Flagged traces are severity-coded -- high for hallucinations, medium for SLA breaches. No human reviewer needed to find these."

**Part D: Export (1 min)**

- Switch to Export Report tab
- Select date range (last 7 days)
- Select format: Excel (.xlsx)
- Click "Generate Report"
- Click "Download Excel Report"
- (Optional: briefly open the Excel to show Summary + Traces sheets)

**Narration:**
> "Export a compliance evidence pack in one click. Excel, CSV, or JSON. Attach it to an audit report, import into a GRC tool, or archive for retention. Self-service -- no tickets, no waiting."

---

### Scene 4: Demo Group C -- Audit Portal + MLflow (6 min)

**KPIs covered: 1.1/1.9.1 (Data Lineage) | 1.3 (Prompt & Output Logging) | 1.7 (Groundedness & Hallucination)**

**Tab: MLflow UI (Tab 3)**

**Narration (transition):**
> "Let's go one level deeper. Everything you just saw in the Audit Portal is powered by MLflow tracing underneath. Let me show you what's captured."

**Part A: Data Lineage and Traceability (2 min)**

- Show the traces list -- all recent interactions appear in real-time
- Click into a trace -- show the span tree:
  - `rag_query` (root) > `retrieve_context` > `load_prompt` > `ChatOpenAI`
- Click into the `retrieve_context` span -- show source documents with similarity scores
- Click into the `load_prompt` span -- show prompt version loaded
- Show trace attributes: `prompt_version`, `model_name`, `model_endpoint`, `source_documents`, `app_version`
- Show trace tags: `sla_pass`, `latency_ms`, `policy_terms_count`

**Narration:**
> "Every interaction produces a full trace. Data lineage: which documents were retrieved and their similarity scores. Which prompt version. Which model and endpoint. The app release version. Every field needed for audit -- captured automatically, zero manual instrumentation."

**Part B: Prompt and Output Logging (1.5 min)**

- Click into the `ChatOpenAI` span
- Show the full prompt text sent to the model (the complete input)
- Show the full response text (the complete output)
- Navigate to Prompt Registry: show v1 and v2 templates side by side
- Point out: both interactions from Scene 2 are here with different `prompt_version` tags

**Narration:**
> "Complete prompt and output logging. Click into the LLM span -- you see the exact text sent to the model and the exact response. In the Prompt Registry, every version is tracked. Same question, different prompt versions, fully traceable. And in production, these same traces flow via OTel to your enterprise SIEM -- Splunk, Dynatrace. One config change, no code rebuild."

**Part C: Groundedness and Hallucination Scoring (2.5 min)**

- Click on a trace that has been evaluated > click "Show assessments"
- Show the scorer results: `groundedness = 0.77` (faithfulness score as continuous 0-1)
- Explain: "0.77 means 77% of claims in the response are supported by the retrieved context"
- Switch to Tab 2 (Audit Portal) > Evaluation tab
- Click "Run Evaluation Pipeline" (trigger for demo -- don't wait)
- Show pre-existing evaluation results: comparison table with colour-coded metrics
- Show the bar chart comparing metrics across prompt versions
- Point out: v2 (governed) scores higher on faithfulness than v1 (ungoverned)

**Then switch back to Tab 4 (RHOAI Dashboard):**
- Navigate to Data Science Pipelines > Runs
- Show the pipeline run (should be running or just completed)
- Show the pipeline DAG: Score -> Analyze & Flag -> Report
- Say: "In production, this runs on a schedule. Faithfulness drops below 70% -- flagged automatically."

**Narration:**
> "RAGAS faithfulness scoring via EvalHub. It decomposes each response into individual claims and verifies each against the context -- a continuous 0-1 score, not binary yes/no. 0.77 means 77% of claims are grounded. The same EvalHub platform runs safety benchmarks, performance benchmarks, and RAG quality evaluation -- one unified control plane. The pipeline runs daily: score, analyse, flag violations, compare with previous runs to detect drift."

---

### Scene 5: Demo Group D -- Controls and Observability (3 min)

**KPIs covered: 1.4 (Kill Switch) | 3.1/3.2 (Token Budgets & QoS) | 4.1/4.2 (Gateway Inventory)**

**Tab: RHOAI Dashboard + Terminal**

**Narration (transition):**
> "Finally, let's look at the administrative controls. Who has access to AI, and how do we manage it?"

**Part A: Gateway Inventory (1.5 min)**

- Dashboard: Settings > Subscriptions -- show active subscriptions
- Gen AI Studio > API Keys -- show key management
- Gen AI Studio > Models -- show published models
- Terminal: run `oc get maassubscription -n models-as-a-service`
- Briefly show the observability metrics: token usage per subscription, request volume

**Narration:**
> "Every AI consumer is identified via subscriptions. Each subscription maps to a group, which maps to a team. CLI or dashboard -- complete inventory. The observability dashboard shows token usage per subscription, request volume per model. If it goes through the gateway, we can observe it."

**Part B: Kill Switch and Rate Limits (1.5 min)**

- Show an API key in the dashboard
- Demonstrate revocation (or explain the flow if destructive action not desired live):
  - "Revoking this key immediately cuts off the application's access to the model"
- Show rate limiting / token budget configuration (if visible in subscription details)
- Briefly mention: "Structured CMDB/app-owner fields are on the product roadmap -- RHAIRFE-2312. Today, subscription-to-team mapping is via group membership."

**Narration:**
> "Kill switch: revoke an API key and the application loses access immediately. Rate limits cap token consumption per subscription -- prevents abuse. Provider abstraction means applications never hit model endpoints directly; everything goes through the gateway. The structured CMDB linkage for app-owner and business service records is on the roadmap. Today, each subscription maps to a team via group membership."

---

### Scene 6: Summary (1 min)

**Tab: Slides (or any)**

**Narration:**
> "To summarize: we demonstrated governance across the full AI lifecycle. The chatbot shows safe consumption with prompt governance and guardrails. The Audit Portal gives compliance a single pane of glass -- filters, flagged violations, evidence export. MLflow captures full lineage and the evaluation pipeline scores every interaction for hallucination risk. And the gateway provides visibility and control over who uses what. The POC validates the controls -- the next step is a pilot to validate the operations."

---

## Live Demo Checklist

Before going live, verify:

- [ ] Both apps are running: `oc get pods -n <NAMESPACE> -l 'app in (<RAG_APP_NAME>,<AUDIT_PORTAL_NAME>)'`
- [ ] Model is responding: ask a test question in the chatbot
- [ ] MLflow has traces: check the experiments in MLflow UI
- [ ] Eval results exist: check the eval experiment has runs with assessments
- [ ] Pipeline is registered: check RHOAI Dashboard > Data Science Pipelines
- [ ] Audit Portal loads: all 4 tabs render correctly
- [ ] Compliance filters work: Browse Traces shows SLA/Groundedness/Regulatory filters
- [ ] Have the Excel export pre-downloaded as backup (in case export fails live)
- [ ] Chatbot set to prompt v2 (governed) at start

## Timing Guide

| Scene | Duration | Demo Group | KPIs |
|-------|----------|-----------|------|
| 1. Platform Overview | 3 min | -- | Context setting |
| 2. RAG Chatbot + Guardrails | 5 min | A | 1.2/1.5, 1.6 |
| 3. Audit Portal | 5 min | B | 2.1/2.2 |
| 4. Audit Portal + MLflow | 6 min | C | 1.1/1.9.1, 1.3, 1.7 |
| 5. Controls & Observability | 3 min | D | 1.4, 3.1/3.2, 4.1/4.2 |
| 6. Summary | 1 min | -- | Recap |
| **Total** | **~23 min** | | **All KPIs** |

## Recording Tips

- Use **1920x1080** resolution for screen recording
- **Zoom browser to 110-125%** so text is readable in the video
- **Pause 1-2 seconds** after each click so the viewer can follow
- **Narrate what you're clicking** -- "I'm clicking into this trace to show the span tree"
- If something takes time to load, narrate while waiting -- "The model is generating a response..."
- For the eval pipeline trigger (Scene 4), do NOT wait for it -- trigger and move on to show pre-existing results
- **Transition cues between groups** are critical -- use them to reframe the audience's perspective (user -> auditor -> technical -> admin)
