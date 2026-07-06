# ANZ Banking Policy Assistant

Welcome to the **ANZ NZ Governance POC** -- a RAG-powered banking policy assistant with full MLflow tracing.

## What This Demonstrates

- **KPI 1.1 / 1.9.1**: Every interaction is traced with data lineage -- prompt version, model endpoint, source documents, and release metadata.
- **KPI 1.3**: All prompts and outputs are logged in real-time via MLflow tracing. Expand the pipeline steps below each response to see retrieval, prompt loading, and LLM generation details.

## How to Use

Ask questions about ANZ banking policies, for example:

- "What are the eligibility criteria for a personal loan?"
- "What is the maximum LVR for investment properties?"
- "How long must KYC records be retained?"
- "What controls are required for GenAI applications?"

Each response will show **pipeline steps** that you can expand to see the full RAG execution trace.
