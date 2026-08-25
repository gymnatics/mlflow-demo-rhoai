"""MLflow Prompt Registry helpers for versioned prompt management."""

import mlflow
import mlflow.genai
from config import MLFLOW_TRACKING_URI, MLFLOW_WORKSPACE

mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
if MLFLOW_WORKSPACE:
    mlflow.set_workspace(MLFLOW_WORKSPACE)

SYSTEM_PROMPT_NAME = "rag-system-prompt"
DEFAULT_SYSTEM_PROMPT = (
    "You are a knowledgeable policy compliance assistant. "
    "Answer questions based ONLY on the provided context from official policy documents. "
    "If the context does not contain enough information to answer the question, say so clearly. "
    "Always cite the specific policy document and section when possible. "
    "Do not speculate or provide information beyond what is in the context.\n\n"
    "IMPORTANT - ALWAYS USE THE CONTEXT:\n"
    "- You MUST answer using the data provided in the context. "
    "Do NOT refuse to answer or claim you cannot access the data -- it is right there in the context.\n"
    "- Some sensitive fields in the context may be marked as [REDACTED]. "
    "If a user asks for a redacted field, state that the information has been redacted by the data protection guardrails.\n"
    "- Answer ONLY what was specifically asked. Do NOT volunteer additional fields or data that were not requested.\n"
    "- Keep answers concise and directly relevant to the question.\n\n"
    "COMPLIANCE FORMAT REQUIREMENTS:\n"
    "- Structure your answer with clear references to the specific policy document and section number\n"
    "- Present factual information in a concise, auditable format\n"
    "- If the context contains regulatory references (e.g. acts, regulations), include them exactly as stated in the context\n"
    "- Do not add regulatory references or legal citations that are not explicitly present in the provided context\n"
    "- Every claim in your answer must be directly traceable to the provided context"
)


def register_prompt(version_tag: str = "v1", template: str | None = None):
    """Register or update a prompt in the MLflow Prompt Registry."""
    body = template or DEFAULT_SYSTEM_PROMPT
    try:
        prompt = mlflow.genai.register_prompt(
            name=SYSTEM_PROMPT_NAME,
            template=body,
            commit_message=f"Release {version_tag}",
            tags={"version_tag": version_tag},
        )
        return prompt
    except Exception:
        prompt = mlflow.genai.register_prompt(
            name=SYSTEM_PROMPT_NAME,
            template=body,
            commit_message=f"Update to {version_tag}",
            tags={"version_tag": version_tag},
        )
        return prompt


def load_prompt(version: int | None = None) -> tuple[str, dict]:
    """Load a prompt from the registry. Returns (template_text, metadata)."""
    try:
        if version:
            prompt = mlflow.genai.load_prompt(f"prompts:/{SYSTEM_PROMPT_NAME}/{version}")
        else:
            client = mlflow.MlflowClient()
            versions = client.search_prompt_versions(SYSTEM_PROMPT_NAME)
            if not versions:
                raise ValueError("No prompt versions found")
            latest_version = versions[0].version
            prompt = mlflow.genai.load_prompt(f"prompts:/{SYSTEM_PROMPT_NAME}/{latest_version}")

        metadata = {
            "prompt_name": SYSTEM_PROMPT_NAME,
            "prompt_version": getattr(prompt, "version", version or "latest"),
        }
        template_text = prompt.template if hasattr(prompt, "template") else str(prompt)
        return template_text, metadata
    except Exception:
        return DEFAULT_SYSTEM_PROMPT, {
            "prompt_name": SYSTEM_PROMPT_NAME,
            "prompt_version": "fallback",
        }


def list_prompt_versions() -> list[dict]:
    """List all registered versions of the system prompt."""
    try:
        client = mlflow.MlflowClient()
        versions = client.search_prompt_versions(SYSTEM_PROMPT_NAME)
        result = []
        for v in versions:
            result.append({
                "version": v.version,
                "commit_message": v.commit_message,
                "tags": v.tags,
            })
        return result
    except Exception:
        return []
