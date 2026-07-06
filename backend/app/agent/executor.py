"""
Agent Executor — executes planned steps in topological dependency order.

Supports parallel execution of independent steps and dynamic parameter substitution.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Set

from app.agent.tools import TOOLS

logger = logging.getLogger("docqa.agent.executor")


class AgentExecutor:
    """Executes a list of steps in topological order, supporting parallel runs."""

    def __init__(
        self,
        graph_store: Any,
        cf_client: Any,
        pipeline_factory: Any,
        reranker: Any,
    ):
        self.store            = graph_store
        self.cf_client        = cf_client
        self.pipeline_factory = pipeline_factory
        self.reranker         = reranker

    async def execute(
        self,
        steps: List[Dict[str, Any]],
        tenant_id: str,
        on_status: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Execute all plan steps.

        Args:
            steps: List of step definitions (id, tool, params, dependencies).
            tenant_id: Current tenant context.
            on_status: Optional async callback to yield step progress updates.

        Returns:
            A dictionary containing results for each step, execution times, and trace metadata.
        """
        logger.info("Starting execution of %d steps for tenant %s", len(steps), tenant_id)
        
        # 1. Topological Sort into execution layers
        try:
            layers = self._topological_sort_layers(steps)
        except ValueError as err:
            logger.error("Sort failed: %s", err)
            return {"error": str(err), "success": False, "trace": []}

        # Context provided to all tools
        context = {
            "store":            self.store,
            "llm_client":       self.cf_client,
            "pipeline_factory": self.pipeline_factory,
            "reranker":         self.reranker,
            "tenant_id":        tenant_id,
        }

        results: Dict[str, Any] = {}
        trace_logs: List[Dict[str, Any]] = []
        overall_start = time.time()

        # 2. Execute layer by layer
        for layer_idx, layer in enumerate(layers):
            logger.info("Executing execution layer %d: %r", layer_idx, layer)
            
            if on_status:
                step_names = ", ".join(f"{s_id} ({next(s['tool'] for s in steps if s['id'] == s_id)})" for s_id in layer)
                await on_status(f"Executing execution layer {layer_idx + 1}/{len(layers)} (Steps: {step_names})...")
            
            # Form task list for parallel gather
            layer_tasks = []
            layer_step_defs = []
            for step_id in layer:
                # Find step definition
                step_def = next(s for s in steps if s["id"] == step_id)
                layer_step_defs.append(step_def)
                
                # Perform template substitution on parameters
                resolved_params = self._substitute_templates(step_def["params"], results)
                logger.debug("Resolved params for %s: %r", step_id, resolved_params)
                
                # Retrieve tool from registry
                tool_name = step_def["tool"]
                if tool_name not in TOOLS:
                    raise ValueError(f"Unknown tool '{tool_name}' in step {step_id}")
                
                tool_fn = TOOLS[tool_name]
                layer_tasks.append(self._run_single_step(step_id, tool_fn, resolved_params, context))

            # Run layer tasks concurrently
            layer_results = await asyncio.gather(*layer_tasks, return_exceptions=True)

            # Record results and trace logs
            for step_def, res in zip(layer_step_defs, layer_results):
                step_id = step_def["id"]
                if isinstance(res, Exception):
                    logger.error("Step %s raised exception: %s", step_id, res)
                    res_val = {"error": str(res), "success": False}
                else:
                    res_val = res

                results[step_id] = res_val
                trace_logs.append({
                    "step_id":      step_id,
                    "tool":         step_def["tool"],
                    "status":       "FAILED" if "error" in res_val else "SUCCESS",
                    "latency_ms":   res_val.get("_latency_ms", 0),
                    "result_keys":  list(res_val.keys()) if isinstance(res_val, dict) else [],
                })

        overall_latency = round((time.time() - overall_start) * 1000, 2)
        logger.info("Agent execution completed in %.2fms", overall_latency)

        return {
            "success":         True,
            "results":         results,
            "trace":           trace_logs,
            "total_latency_ms": overall_latency,
        }

    async def _run_single_step(
        self,
        step_id: str,
        tool_fn: Any,
        params: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Wrapper to run a single tool step and measure latency."""
        t0 = time.time()
        try:
            res = await tool_fn(params, context)
            if not isinstance(res, dict):
                res = {"value": res}
        except Exception as exc:
            logger.exception("Step %s failed:", step_id)
            res = {"error": str(exc)}
        
        latency = round((time.time() - t0) * 1000, 2)
        res["_latency_ms"] = latency
        return res

    def _topological_sort_layers(self, steps: List[Dict[str, Any]]) -> List[List[str]]:
        """Sort steps into a list of layers that can be executed in parallel."""
        steps_by_id = {s["id"]: s for s in steps}
        completed: Set[str] = set()
        layers: List[List[str]] = []
        remaining = set(steps_by_id.keys())

        while remaining:
            current_layer: List[str] = []
            for step_id in list(remaining):
                step = steps_by_id[step_id]
                # Check if all dependencies are already satisfied
                if all(dep in completed for dep in step.get("dependencies", [])):
                    current_layer.append(step_id)
            
            if not current_layer:
                raise ValueError("Cyclic dependency or missing dependency detected in agent plan!")
            
            layers.append(current_layer)
            completed.update(current_layer)
            remaining.difference_update(current_layer)

        return layers

    def _substitute_templates(self, val: Any, results: Dict[str, Any]) -> Any:
        """Recursively replace {{step_N.field}} or {{step_N}} placeholders with actual results."""
        if isinstance(val, str):
            # Check for exact full match first to preserve rich object types (dict, list, etc.)
            match = re.match(r"^\{\{([a-zA-Z0-9_]+)(?:\.([a-zA-Z0-9_]+))?\}\}$", val)
            if match:
                step_id, field = match.groups()
                if step_id in results:
                    step_res = results[step_id]
                    if field:
                        if isinstance(step_res, dict) and field in step_res:
                            return step_res[field]
                        elif hasattr(step_res, field):
                            return getattr(step_res, field)
                        return f"[{field} not found in {step_id}]"
                    return step_res
                return val

            # Substring interpolation
            def replacer(m):
                step_id, field = m.groups()
                if step_id in results:
                    step_res = results[step_id]
                    if field:
                        if isinstance(step_res, dict) and field in step_res:
                            return str(step_res[field])
                        elif hasattr(step_res, field):
                            return str(getattr(step_res, field))
                        return f"[{field} not found]"
                    return str(step_res)
                return m.group(0)

            return re.sub(r"\{\{([a-zA-Z0-9_]+)(?:\.([a-zA-Z0-9_]+))?\}\}", replacer, val)

        elif isinstance(val, list):
            return [self._substitute_templates(item, results) for item in val]
        elif isinstance(val, dict):
            return {k: self._substitute_templates(v, results) for k, v in val.items()}
        return val
