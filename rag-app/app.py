"""Chainlit RAG chat application with MLflow tracing and Steps visualization."""

import chainlit as cl
from rag_pipeline import RAGPipeline
from prompt_manager import load_prompt, list_prompt_versions, register_prompt
import config


@cl.on_chat_start
async def on_start():
    pipeline = RAGPipeline()

    await cl.Message(content="Building vector index from banking policy documents...").send()
    num_chunks = pipeline.build_index()
    cl.user_session.set("pipeline", pipeline)

    system_prompt, prompt_meta = load_prompt()
    prompt_version = prompt_meta.get("prompt_version", "fallback")

    await cl.Message(
        content=(
            f"**ANZ Banking Policy Assistant** ready.\n\n"
            f"- **Documents indexed:** {num_chunks} chunks from {config.SAMPLE_DOCS_DIR}\n"
            f"- **Prompt version:** {prompt_version}\n"
            f"- **Model:** {config.LLM_MODEL} @ {config.LLM_ENDPOINT}\n"
            f"- **Embedding model:** {config.EMBEDDING_MODEL}\n"
            f"- **App version:** {config.APP_VERSION}\n\n"
            f"All interactions are traced in MLflow. Ask me anything about ANZ banking policies."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    pipeline: RAGPipeline = cl.user_session.get("pipeline")
    user_question = message.content

    # --- Step 1: Retrieve context ---
    async with cl.Step(name="Retrieve Context", type="retrieval") as retrieval_step:
        retrieval_step.input = user_question
        context_docs = pipeline.retrieve(user_question)

        source_summary = []
        for i, doc in enumerate(context_docs, 1):
            source_summary.append(
                f"**Chunk {i}** (score: {doc['score']:.3f}) from `{doc['source_file']}`:\n"
                f"> {doc['content'][:200]}..."
            )
        retrieval_step.output = "\n\n".join(source_summary)

    # --- Step 2: Load prompt version ---
    async with cl.Step(name="Load Prompt", type="tool") as prompt_step:
        system_template, prompt_metadata = load_prompt(pipeline.prompt_version)
        prompt_step.input = f"Prompt: {prompt_metadata.get('prompt_name', 'unknown')}"
        prompt_step.output = (
            f"**Version:** {prompt_metadata.get('prompt_version', 'unknown')}\n\n"
            f"**Template:**\n```\n{system_template}\n```"
        )

    # --- Step 3: Generate response ---
    async with cl.Step(name="LLM Generation", type="llm") as llm_step:
        llm_step.input = (
            f"**Model:** {config.LLM_MODEL}\n"
            f"**Endpoint:** {config.LLM_ENDPOINT}\n"
            f"**Question:** {user_question}"
        )
        result = pipeline.query(user_question)
        llm_step.output = result["answer"]

    # --- Send final response ---
    source_files = result.get("source_documents", [])
    source_text = ", ".join(f"`{s}`" for s in source_files) if source_files else "none"
    prompt_ver = result.get("prompt_metadata", {}).get("prompt_version", "unknown")

    response_msg = (
        f"{result['answer']}\n\n"
        f"---\n"
        f"*Sources: {source_text} | Prompt: {prompt_ver} | Model: {result['model']}*"
    )

    await cl.Message(content=response_msg).send()


@cl.on_settings_update
async def on_settings_update(settings):
    """Allow changing prompt version from the UI settings."""
    pipeline: RAGPipeline = cl.user_session.get("pipeline")
    new_version = settings.get("prompt_version")
    if new_version and new_version != "latest":
        pipeline.prompt_version = int(new_version)
    else:
        pipeline.prompt_version = None
    cl.user_session.set("pipeline", pipeline)
    await cl.Message(
        content=f"Prompt version updated to: {new_version or 'latest'}"
    ).send()
