"""MLflow Prompt Registry helpers for versioned prompt management."""

import mlflow
import mlflow.genai
from config import MLFLOW_TRACKING_URI, MLFLOW_WORKSPACE

mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
if MLFLOW_WORKSPACE:
    mlflow.set_workspace(MLFLOW_WORKSPACE)

SYSTEM_PROMPT_NAME = "anz-rag-system-prompt"
DEFAULT_SYSTEM_PROMPT = (
    "You are a knowledgeable banking policy assistant for ANZ Bank New Zealand. "
    "Answer questions based ONLY on the provided context from official ANZ policy documents. "
    "If the context does not contain enough information to answer the question, say so clearly. "
    "Always cite the specific policy document and section when possible. "
    "Do not speculate or provide information beyond what is in the context."
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
