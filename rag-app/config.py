import os

LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "https://inference-gateway.apps.cluster.example.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3-8b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-placeholder")

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
MLFLOW_EXPERIMENT_NAME = os.getenv("MLFLOW_EXPERIMENT_NAME", "anz-rag-governance-poc")
MLFLOW_WORKSPACE = os.getenv("MLFLOW_WORKSPACE", "")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

SAMPLE_DOCS_DIR = os.getenv("SAMPLE_DOCS_DIR", os.path.join(os.path.dirname(__file__), "sample_docs"))

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "4"))

APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
