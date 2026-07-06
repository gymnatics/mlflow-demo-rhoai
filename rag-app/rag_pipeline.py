"""RAG pipeline with end-to-end MLflow tracing and data lineage."""

import os
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
            self._llm = ChatOpenAI(
                base_url=config.LLM_ENDPOINT,
                api_key=config.LLM_API_KEY,
                model=config.LLM_MODEL,
                temperature=0.1,
                max_tokens=2048,
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": False}
                },
            )
        return self._llm

    @mlflow.trace(name="rag_query", span_type="CHAIN")
    def query(self, user_question: str) -> dict:
        system_template, prompt_metadata = load_prompt(self.prompt_version)

        context_docs = self.retrieve(user_question)
        context_text = "\n\n---\n\n".join(d["content"] for d in context_docs)
        source_files = list({d["source_file"] for d in context_docs})

        prompt = ChatPromptTemplate.from_messages([
            ("system", "{system_prompt}\n\nContext:\n{context}"),
            ("human", "{question}"),
        ])

        chain = prompt | self._get_llm() | StrOutputParser()

        response = chain.invoke({
            "system_prompt": system_template,
            "context": context_text,
            "question": user_question,
        })

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
            })

        return {
            "answer": response,
            "source_documents": source_files,
            "context_chunks": context_docs,
            "prompt_metadata": prompt_metadata,
            "model": config.LLM_MODEL,
            "model_endpoint": config.LLM_ENDPOINT,
        }
