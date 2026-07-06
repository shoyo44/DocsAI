"""
Agent Tools — implementations of tools executed by the Agent Executor.

Tools:
    - search_documents: Run RAG search inside a specific vertical.
    - compare_documents: Compare documents/answers across verticals.
    - get_document_metadata: List documents owned by the tenant.
    - llm_answer: Generate a custom text answer using the LLM client.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.dependencies import get_embedding

logger = logging.getLogger("docqa.agent.tools")


async def tool_search_documents(
    params: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Search documents within a specific vertical (law, compliance, hr, startup, university).
    """
    vertical = params.get("vertical")
    query    = params.get("query")
    keyword  = params.get("keyword", "")

    if not vertical:
        return {"error": "Missing 'vertical' parameter in search_documents."}
    if not query:
        return {"error": "Missing 'query' parameter in search_documents."}

    store            = context["store"]
    llm_client       = context["llm_client"]
    pipeline_factory = context["pipeline_factory"]
    reranker         = context["reranker"]
    tenant_id        = context["tenant_id"]

    try:
        pipeline = pipeline_factory.build_pipeline(vertical, llm_client, reranker)
        embedding = await get_embedding(query)
        result = await pipeline.query(
            query_text=query,
            embedding=embedding,
            store=store,
            tenant_id=tenant_id,
            keyword=keyword,
        )
        return result
    except Exception as exc:
        logger.exception("Error executing search_documents tool:")
        return {"error": str(exc)}


async def tool_compare_documents(
    params: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compare information or search results from two different vertical lookups.
    """
    vertical_a = params.get("vertical_a")
    query_a    = params.get("query_a")
    vertical_b = params.get("vertical_b")
    query_b    = params.get("query_b")
    aspects    = params.get("aspects", "Compare similarities, contradictions, and key differences.")

    if not all([vertical_a, query_a, vertical_b, query_b]):
        return {"error": "Missing parameters. Must provide vertical_a, query_a, vertical_b, query_b."}

    store            = context["store"]
    llm_client       = context["llm_client"]
    pipeline_factory = context["pipeline_factory"]
    reranker         = context["reranker"]
    tenant_id        = context["tenant_id"]

    try:
        # Run Search A
        pipe_a = pipeline_factory.build_pipeline(vertical_a, llm_client, reranker)
        embed_a = await get_embedding(query_a)
        res_a = await pipe_a.query(query_a, embed_a, store, tenant_id)

        # Run Search B
        pipe_b = pipeline_factory.build_pipeline(vertical_b, llm_client, reranker)
        embed_b = await get_embedding(query_b)
        res_b = await pipe_b.query(query_b, embed_b, store, tenant_id)

        # Perform comparative analysis
        prompt = (
            f"You are a senior document analyst. Compare the outputs from these two retrieval steps.\n\n"
            f"Comparison Instructions: {aspects}\n\n"
            f"--- Result A (Vertical: {vertical_a}, Query: '{query_a}') ---\n"
            f"Answer: {res_a.get('answer')}\n\n"
            f"--- Result B (Vertical: {vertical_b}, Query: '{query_b}') ---\n"
            f"Answer: {res_b.get('answer')}\n\n"
            f"Provide a clear, cohesive markdown response detailing your comparison, contradictions, "
            f"and recommendations."
        )

        comparison = await llm_client.chat(
            system_prompt="You are a senior analyst. Output a professional comparative report in Markdown.",
            user_message=prompt,
            max_tokens=2000,
        )

        return {
            "comparison": comparison,
            "answer_a": res_a.get("answer"),
            "answer_b": res_b.get("answer"),
            "chunks_used_a": res_a.get("chunks_used", []),
            "chunks_used_b": res_b.get("chunks_used", []),
        }

    except Exception as exc:
        logger.exception("Error executing compare_documents tool:")
        return {"error": str(exc)}


async def tool_get_document_metadata(
    params: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Retrieve document metadata list for the current tenant.
    """
    store     = context["store"]
    tenant_id = context["tenant_id"]

    try:
        records = store.list_documents(tenant_id)
        return {"documents": records}
    except Exception as exc:
        logger.exception("Error executing get_document_metadata tool:")
        return {"error": str(exc)}


async def tool_llm_answer(
    params: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Generate an answer using general reasoning from inputs.
    """
    prompt        = params.get("prompt")
    system_prompt = params.get("system_prompt", "You are an AI reasoning agent. Answer the question carefully.")

    if not prompt:
        return {"error": "Missing 'prompt' parameter in llm_answer."}

    llm_client = context["llm_client"]

    try:
        response = await llm_client.chat(
            system_prompt=system_prompt,
            user_message=prompt,
            max_tokens=2500,
        )
        return {"answer": response}
    except Exception as exc:
        logger.exception("Error executing llm_answer tool:")
        return {"error": str(exc)}


# Tool registry map
TOOLS = {
    "search_documents":      tool_search_documents,
    "compare_documents":     tool_compare_documents,
    "get_document_metadata": tool_get_document_metadata,
    "llm_answer":            tool_llm_answer,
}
