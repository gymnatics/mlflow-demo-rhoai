"""Seed mock traces into local MLflow for Audit Portal testing."""

import mlflow
import random
import time
from datetime import datetime, timedelta

mlflow.set_tracking_uri("http://127.0.0.1:5555")
mlflow.set_experiment("rag-governance-poc")

SAMPLE_QUERIES = [
    ("What are the eligibility criteria for a personal loan?",
     "To be eligible for a personal loan, applicants must be 18 years or older and a resident or citizen. Minimum annual income of 30,000 (gross) is required, along with employment tenure of at least 6 months. Satisfactory credit history with no defaults in the last 24 months is also required. (Source: lending_policy.md, Section 1.1)"),
    ("What is the maximum LVR for investment properties?",
     "The maximum Loan-to-Value Ratio (LVR) for investment properties is 65%. For owner-occupied properties, the standard maximum LVR is 80%, or up to 90% with lender's mortgage insurance. (Source: lending_policy.md, Section 2.2)"),
    ("How long must KYC records be retained?",
     "All CDD records must be retained for a minimum of 5 years after the end of the customer relationship. Transaction records must be retained for a minimum of 5 years after the transaction date. Records must be sufficient to reconstruct each transaction and demonstrate compliance with the AML/CFT Act. (Source: kyc_policy.md, Section 6)"),
    ("What controls are required for GenAI applications?",
     "Production GenAI applications require: (1) version-controlled and approved prompts, (2) logging of all outputs including full prompt, response, model version, and timestamp, (3) input and output guardrails to prevent prompt injection and sensitive data leakage, (4) human oversight for decisions affecting customers, and (5) token usage and cost monitoring with budget controls. (Source: data_governance_policy.md, Section 3.2)"),
    ("What are the hardship provisions for borrowers?",
     "Borrowers experiencing financial hardship may apply for temporary repayment adjustments. Applications must be assessed within 5 working days. Options include interest-only periods, term extensions, or temporary payment reductions. (Source: lending_policy.md, Section 3.2)"),
    ("When is Enhanced Due Diligence required?",
     "Enhanced Due Diligence (EDD) must be applied when: the customer is a Politically Exposed Person (domestic or foreign), the customer is from a high-risk FATF jurisdiction, there are complex or unusual transaction patterns, for correspondent banking relationships, or when new technologies limit identity verification. (Source: kyc_policy.md, Section 2.3)"),
    ("What is the threshold for cash transaction reporting?",
     "All cash transactions of 10,000 or more (or equivalent in foreign currency) must be reported to the national Financial Intelligence Unit (FIU). International wire transfers of 1,000 or more must include originator information. (Source: kyc_policy.md, Section 3.2)"),
    ("How are AI models classified by risk tier?",
     "AI models are classified into four risk tiers: Tier 1 (Critical) requires Executive Risk Committee approval with quarterly review, Tier 2 (High) requires Model Risk Committee approval with semi-annual review, Tier 3 (Medium) requires Business Unit Risk Manager approval with annual review, and Tier 4 (Low) requires Model Owner approval with annual review. (Source: data_governance_policy.md, Section 3.3)"),
]

PROMPT_VERSIONS = ["v1", "v2"]
MODELS = ["qwen3-8b"]
SOURCE_DOCS = ["lending_policy.md", "kyc_policy.md", "data_governance_policy.md"]

print("Seeding mock traces into MLflow...")

for i in range(20):
    query, answer = random.choice(SAMPLE_QUERIES)
    prompt_ver = random.choice(PROMPT_VERSIONS)
    model = random.choice(MODELS)
    sources = random.sample(SOURCE_DOCS, k=random.randint(1, 2))
    latency = random.randint(200, 2000)

    days_ago = random.randint(0, 14)
    trace_time = datetime.now() - timedelta(days=days_ago, hours=random.randint(0, 23))

    @mlflow.trace(
        name="rag_query",
        span_type="CHAIN",
        attributes={
            "prompt_version": prompt_ver,
            "model_name": model,
            "model_endpoint": "https://inference-gateway.apps.cluster.example.com/v1",
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            "source_documents": ", ".join(sources),
            "app_version": "1.0.0",
        },
    )
    def mock_rag_query(question, expected_answer, sleep_ms):
        time.sleep(sleep_ms / 1000)
        return {"answer": expected_answer, "source_documents": sources}

    result = mock_rag_query(query, answer, latency)
    print(f"  Trace {i+1}/20: '{query[:50]}...' (prompt={prompt_ver})")

print(f"\nDone! 20 mock traces seeded into experiment 'rag-governance-poc'")
print("MLflow UI: http://127.0.0.1:5555")
