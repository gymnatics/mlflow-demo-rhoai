"""RAG pipeline with end-to-end MLflow tracing and data lineage."""

import os
import re
import time
import mlflow
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

import config
from prompt_manager import load_prompt

_DEFAULT_POLICY_TERMS = "policy,section,lvr,kyc,aml,cdd,compliance,regulatory,retention"
POLICY_TERMS = os.getenv("POLICY_TERMS", _DEFAULT_POLICY_TERMS).split(",")
SLA_THRESHOLD_MS = 10_000

_GUARDRAIL_BLOCKED_PHRASE = "the response was blocked because it contained sensitive information"

_PII_PATTERNS = [
    (re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.-]+\b'), '[EMAIL REDACTED]'),
    (re.compile(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{4}\b'), '[PHONE REDACTED]'),
    (re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'), '[CARD REDACTED]'),
    (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), '[SSN REDACTED]'),
]


def _mask_pii(text: str) -> str:
    """Mask PII patterns in text before sending to the model."""
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _is_guardrail_refusal(response: str) -> bool:
    """Detect the NeMo Guardrails canned refusal message."""
    return _GUARDRAIL_BLOCKED_PHRASE in response.lower()


mlflow.set_tracking_uri(config.MLFLOW_TRACKING_URI)
if config.MLFLOW_WORKSPACE:
    mlflow.set_workspace(config.MLFLOW_WORKSPACE)
mlflow.set_experiment(config.MLFLOW_EXPERIMENT_NAME)
mlflow.langchain.autolog()


class RAGPipeline:
    def __init__(self, prompt_version: int | None = None):
        self.prompt_version = prompt_version
        self._vectorstore = None
        self._embeddings = None
        self._llm = None

    def _get_embeddings(self):
        if self._embeddings is None:
            self._embeddings = HuggingFaceEmbeddings(
                model_name=config.EMBEDDING_MODEL,
                model_kwargs={"device": "cpu"},
            )
        return self._embeddings

    @mlflow.trace(name="load_documents", span_type="RETRIEVAL")
    def _load_documents(self):
        loader = DirectoryLoader(
            config.SAMPLE_DOCS_DIR,
            glob="**/*.md",
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"},
        )
        docs = loader.load()
        for doc in docs:
            doc.metadata["source_file"] = os.path.basename(doc.metadata.get("source", ""))
            doc.metadata["source_dir"] = config.SAMPLE_DOCS_DIR
        return docs

    @mlflow.trace(name="build_vector_index", span_type="RETRIEVAL")
    def build_index(self):
        docs = self._load_documents()
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP,
        )
        chunks = splitter.split_documents(docs)
        embeddings = self._get_embeddings()
        self._vectorstore = FAISS.from_documents(chunks, embeddings)
        return len(chunks)

    @mlflow.trace(name="add_uploaded_documents", span_type="RETRIEVAL")
    def add_documents(self, file_path: str, file_name: str) -> int:
        """Add a document file to the live vector store."""
        if self._vectorstore is None:
            self.build_index()

        if file_name.lower().endswith(".csv"):
            from langchain_community.document_loaders import CSVLoader
            loader = CSVLoader(file_path, encoding="utf-8")
        else:
            loader = TextLoader(file_path, encoding="utf-8")
        docs = loader.load()
        for doc in docs:
            doc.metadata["source_file"] = file_name
            doc.metadata["source_dir"] = "user_upload"

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP,
        )
        chunks = splitter.split_documents(docs)
        self._vectorstore.add_documents(chunks)
        return len(chunks)

    @mlflow.trace(name="retrieve_context", span_type="RETRIEVAL")
    def retrieve(self, query: str) -> list[dict]:
        if self._vectorstore is None:
            self.build_index()
        results = self._vectorstore.similarity_search_with_score(
            query, k=config.RETRIEVAL_TOP_K
        )
        context_docs = []
        for doc, score in results:
            context_docs.append({
                "content": doc.page_content,
                "source_file": doc.metadata.get("source_file", "unknown"),
                "score": float(score),
            })
        return context_docs

    def _get_llm(self):
        if self._llm is None:
            kwargs = dict(
                base_url=config.LLM_ENDPOINT,
                api_key=config.LLM_API_KEY,
                model=config.LLM_MODEL,
                temperature=0.1,
                max_tokens=2048,
            )
            if "guardrail" not in config.LLM_ENDPOINT.lower():
                kwargs["extra_body"] = {
                    "chat_template_kwargs": {"enable_thinking": False}
                }
            self._llm = ChatOpenAI(**kwargs)
        return self._llm

    @mlflow.trace(name="rag_query", span_type="CHAIN")
    def query(self, user_question: str) -> dict:
        t0 = time.monotonic()

        system_template, prompt_metadata = load_prompt(self.prompt_version)

        context_docs = self.retrieve(user_question)
        raw_context = "\n\n---\n\n".join(d["content"] for d in context_docs)
        context_text = _mask_pii(raw_context)
        source_files = list({d["source_file"] for d in context_docs})

        prompt = ChatPromptTemplate.from_messages([
            ("system", "{system_prompt}"),
            ("human", "Context:\n{context}\n\nQuestion: {question}"),
        ])

        chain = prompt | self._get_llm() | StrOutputParser()

        response = chain.invoke({
            "system_prompt": system_template,
            "context": context_text,
            "question": user_question,
        })

        guardrail_blocked = _is_guardrail_refusal(response)
        if guardrail_blocked:
            response = (
                "**Guardrail Block:** " + response
            )

        latency_ms = int((time.monotonic() - t0) * 1000)
        sla_pass = latency_ms < SLA_THRESHOLD_MS
        policy_terms_found = sum(
            1 for t in POLICY_TERMS if t in response.lower()
        )
        source_count = len(source_files)

        active_span = mlflow.get_current_active_span()
        if active_span:
            active_span.set_attributes({
                "prompt_version": str(prompt_metadata.get("prompt_version", "unknown")),
                "prompt_name": prompt_metadata.get("prompt_name", "unknown"),
                "model_endpoint": config.LLM_ENDPOINT,
                "model_name": config.LLM_MODEL,
                "embedding_model": config.EMBEDDING_MODEL,
                "source_documents": ", ".join(source_files),
                "retrieval_top_k": config.RETRIEVAL_TOP_K,
                "app_version": config.APP_VERSION,
                "sla_pass": str(sla_pass),
                "latency_ms": latency_ms,
                "policy_terms_count": policy_terms_found,
                "source_count": source_count,
                "guardrail_blocked": str(guardrail_blocked),
            })

        try:
            mlflow.update_current_trace(tags={
                "sla_pass": str(sla_pass),
                "latency_ms": str(latency_ms),
                "policy_terms_count": str(policy_terms_found),
                "source_count": str(source_count),
                "guardrail_blocked": str(guardrail_blocked),
                "prompt_version": str(prompt_metadata.get("prompt_version", "unknown")),
                "model_name": config.LLM_MODEL,
                "app_version": config.APP_VERSION,
            })
        except Exception:
            pass

        return {
            "answer": response,
            "source_documents": source_files,
            "context_chunks": context_docs,
            "prompt_metadata": prompt_metadata,
            "model": config.LLM_MODEL,
            "model_endpoint": config.LLM_ENDPOINT,
        }
