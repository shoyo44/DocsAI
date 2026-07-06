"""
Agent Orchestrator — coordinates plan generation, execution, and final synthesis.
Supports real-time progress tracing and token-by-token streaming callbacks.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Callable, Awaitable

from app.agent.planner import AgentPlanner
from app.agent.executor import AgentExecutor

logger = logging.getLogger("docqa.agent")


async def run_agent(
    query:            str,
    tenant_id:        str,
    store:            Any,
    cf_client:        Any,
    pipeline_factory: Any,
    reranker:         Any,
    on_status:        Optional[Callable[[str], Awaitable[None]]] = None,
    on_token:         Optional[Callable[[str], Awaitable[None]]] = None,
) -> Dict[str, Any]:
    """
    Run the multi-step agent pipeline:
    1. Plan steps using the AgentPlanner.
    2. Execute steps using the AgentExecutor.
    3. Synthesize the final answer based on the execution trace.
    """
    t_start = time.time()
    
    # ── 1. Plan ───────────────────────────────────────────────────────────────────
    if on_status:
        await on_status("Decomposing user request and generating step-by-step query plan...")
    planner = AgentPlanner(cf_client)
    plan = await planner.plan(query)
    
    if on_status:
        await on_status(f"Generated plan with {len(plan)} steps.")
    
    # ── 2. Execute ────────────────────────────────────────────────────────────────
    executor = AgentExecutor(
        graph_store=store,
        cf_client=cf_client,
        pipeline_factory=pipeline_factory,
        reranker=reranker,
    )
    exec_res = await executor.execute(plan, tenant_id, on_status)
    
    if not exec_res.get("success", False):
        return {
            "success":          False,
            "plan":             plan,
            "results":          {},
            "answer":           f"Agent planning or execution failed: {exec_res.get('error')}",
            "trace":            exec_res.get("trace", []),
            "total_latency_ms": round((time.time() - t_start) * 1000, 2),
        }
        
    results = exec_res["results"]
    trace   = exec_res["trace"]

    # ── 3. Synthesize Final Answer ────────────────────────────────────────────
    # Optimization: if plan contains exactly one step and it completed successfully,
    # return its result directly to preserve vertical-specific schema (e.g. citations, confidence).
    if len(plan) == 1:
        single_step_id = plan[0]["id"]
        single_res = results.get(single_step_id, {})
        if "error" not in single_res:
            # If a token callback is registered, stream the answer
            ans_text = single_res.get("answer", "")
            if on_token and ans_text:
                # Mock token stream for non-streaming single step tools to ensure UI transitions smoothly
                for char in ans_text:
                    await on_token(char)
            
            single_res["plan"]             = plan
            single_res["results"]          = results
            single_res["trace"]            = trace
            single_res["total_latency_ms"] = round((time.time() - t_start) * 1000, 2)
            single_res["success"]          = True
            return single_res

    # Multi-step synthesis
    logger.info("Synthesizing final response for multi-step agent query.")
    if on_status:
        await on_status("Synthesizing comparative answers from execution trace...")
    try:
        steps_summary = []
        for step in plan:
            sid = step["id"]
            tool = step["tool"]
            step_res = results.get(sid, {})
            
            if "error" in step_res:
                summary = f"Step {sid} ({tool}) failed with error: {step_res['error']}"
            elif tool == "search_documents":
                summary = f"Step {sid} (search {step['params'].get('vertical')}): {step_res.get('answer')}"
            elif tool == "compare_documents":
                summary = f"Step {sid} (comparison): {step_res.get('comparison')}"
            elif tool == "get_document_metadata":
                summary = f"Step {sid} (metadata): {step_res.get('documents')}"
            elif tool == "llm_answer":
                summary = f"Step {sid} (reasoning): {step_res.get('answer')}"
            else:
                summary = f"Step {sid} output: {step_res}"
                
            steps_summary.append(summary)

        context_blocks = "\n\n".join(steps_summary)
        
        synthesis_prompt = (
            f"You are the DocsAI Agent coordinator. The user asked: '{query}'\n\n"
            f"To answer this, we executed a plan and got the following results:\n\n"
            f"{context_blocks}\n\n"
            f"Synthesize a final, professional, complete response answering the user's initial question "
            f"incorporating all relevant insights from the execution steps. Use markdown format. "
            f"Cite the source steps (e.g. 'From the HR vertical...', 'When comparing the regulation changes...') "
            f"as appropriate to show where the information came from."
        )

        sys_prompt = (
            "You are a master coordinator. Synthesize the step results into a clear, cohesive report. "
            "Do not mention internal step IDs (like step_1, step_2) to the user, describe them as context verticals/sources."
        )

        if on_token:
            final_answer_chunks = []
            async for token in cf_client.stream_chat(
                system_prompt=sys_prompt,
                user_message=synthesis_prompt,
                max_tokens=3000,
            ):
                await on_token(token)
                final_answer_chunks.append(token)
            final_answer = "".join(final_answer_chunks)
        else:
            final_answer = await cf_client.chat(
                system_prompt=sys_prompt,
                user_message=synthesis_prompt,
                max_tokens=3000,
            )

    except Exception as exc:
        logger.exception("Synthesis failed, returning raw results representation:")
        final_answer = (
            "I completed the execution plan, but encountered an error synthesizing the final summary.\n\n"
            f"Raw results of steps:\n{results}"
        )

    return {
        "success":          True,
        "plan":             plan,
        "results":          results,
        "answer":           final_answer,
        "trace":            trace,
        "total_latency_ms": round((time.time() - t_start) * 1000, 2),
    }
