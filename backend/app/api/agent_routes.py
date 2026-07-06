"""
Agent routes — executes multi-step planning and orchestration.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.dependencies import get_llm_client, get_graph_store, get_reranker
from app.agent.agent import run_agent
from app.agent.planner import AgentPlanner

logger = logging.getLogger("docqa.api.agent")
router = APIRouter()


class AgentQueryRequest(BaseModel):
    query:     str
    tenant_id: str


@router.post("/agent/query")
async def execute_agent_query(
    payload: AgentQueryRequest,
    request: Request,
    store:  Any = Depends(get_graph_store),
    cf_client: Any = Depends(get_llm_client),
    reranker: Any = Depends(get_reranker),
):
    """Decompose query, execute tool steps, and synthesize response."""
    try:
        pipeline_factory = request.app.state.pipeline_factory

        result = await run_agent(
            query=payload.query,
            tenant_id=payload.tenant_id,
            store=store,
            cf_client=cf_client,
            pipeline_factory=pipeline_factory,
            reranker=reranker,
        )
        return result
    except Exception as exc:
        logger.exception("Agent query execution failed:")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/agent/plan")
async def preview_agent_plan(
    payload: AgentQueryRequest,
    cf_client: Any = Depends(get_llm_client),
):
    """Decompose query and return only the generated plan DAG for review/debugging."""
    try:
        planner = AgentPlanner(cf_client)
        plan = await planner.plan(payload.query)
        return {"query": payload.query, "plan": plan}
    except Exception as exc:
        logger.exception("Agent plan generation failed:")
        raise HTTPException(status_code=500, detail=str(exc))
