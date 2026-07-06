"""
Agent Planner — parses user query into a execution plan (DAG of steps).

Uses the LLM client with structured JSON instructions.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from app.config.verticals import SUPPORTED_VERTICALS

logger = logging.getLogger("docqa.agent.planner")

PLANNER_SYSTEM_PROMPT = f"""
You are the Orchestration Planner for DocsAI.
Your task is to take a user's natural language request and decompose it into a sequence of structured execution steps (a DAG).

The available tools you can call are:

1. `search_documents`
   - Purpose: Retrieve and query documents within a single vertical.
   - Parameters:
     - `vertical`: (string) one of {SUPPORTED_VERTICALS}
     - `query`: (string) a clear search query for that vertical
     - `keyword`: (string, optional) keyword booster

2. `compare_documents`
   - Purpose: Direct comparison between two document retrievals.
   - Parameters:
     - `vertical_a`: (string) vertical for search A
     - `query_a`: (string) query for search A
     - `vertical_b`: (string) vertical for search B
     - `query_b`: (string) query for search B
     - `aspects`: (string, optional) guidelines on comparison aspect

3. `get_document_metadata`
   - Purpose: List documents uploaded by the tenant.
   - Parameters: None

4. `llm_answer`
   - Purpose: General reasoning, analysis, math, or final synthesis from prior steps.
   - Parameters:
     - `prompt`: (string) prompt text. Can include variables referencing prior steps in format:
       `{{{{step_N}}}}` for full JSON output of step_N, or `{{{{step_N.fieldname}}}}` for a nested field (e.g. `{{{{step_1.answer}}}}` or `{{{{step_2.comparison}}}}`).
     - `system_prompt`: (string, optional) override instructions.

GUIDELINES:
- Output MUST be a valid JSON array of step objects.
- Each step MUST have:
  - `id`: (string) unique identifier (e.g., "step_1", "step_2")
  - `tool`: (string) tool name
  - `params`: (dict) arguments matching the tool signature
  - `dependencies`: (list of strings) IDs of prior steps that MUST complete before this step runs.
- Use placeholders like `{{{{step_N.answer}}}}` to wire outputs from one step as inputs to a subsequent step.
- Do NOT output any explanation, notes, or wrapper markdown text. Only return the raw JSON array.
- If the query is simple and maps to a single vertical RAG lookup, output a single-step plan calling `search_documents`.
- If the query needs cross-vertical queries, output multiple parallel search steps and a final `compare_documents` or `llm_answer` step.

Example Output:
[
  {{
    "id": "step_1",
    "tool": "search_documents",
    "params": {{
      "vertical": "law",
      "query": "Find intellectual property liability rules."
    }},
    "dependencies": []
  }},
  {{
    "id": "step_2",
    "tool": "search_documents",
    "params": {{
      "vertical": "compliance",
      "query": "SOC2 compliance IP guidelines."
    }},
    "dependencies": []
  }},
  {{
    "id": "step_3",
    "tool": "llm_answer",
    "params": {{
      "prompt": "Analyze if the contract liability terms: {{{{step_1.answer}}}} comply with the SOC2 rules: {{{{step_2.answer}}}}."
    }},
    "dependencies": ["step_1", "step_2"]
  }}
]
"""


class AgentPlanner:
    """Uses LLM to decompose a request into a task DAG."""

    def __init__(self, llm_client: Any):
        self.llm = llm_client

    async def plan(self, query: str) -> List[Dict[str, Any]]:
        """
        Generate execution plan for a user query.
        Returns a list of step definitions.
        """
        logger.info("Generating plan for query: %r", query)
        try:
            raw_response = await self.llm.chat(
                system_prompt=PLANNER_SYSTEM_PROMPT,
                user_message=f"Plan execution steps for query: '{query}'",
                max_tokens=2000,
            )
            return self._parse_plan(raw_response, query)

        except Exception as exc:
            logger.exception("Failed to generate plan via LLM:")
            return self._fallback_plan(query)

    def _parse_plan(self, text: str, query: str) -> List[Dict[str, Any]]:
        """Parse, clean, and validate LLM output into JSON."""
        # Clean markdown wrappers if any
        cleaned = text.strip()
        if cleaned.startswith("```"):
            # strip start line ```json or ```
            cleaned = re.sub(r"^```[a-zA-Z0-9]*\n", "", cleaned)
            cleaned = re.sub(r"\n```$", "", cleaned)
            cleaned = cleaned.strip()

        try:
            plan = json.loads(cleaned)
            if not isinstance(plan, list):
                raise ValueError("Plan must be a list of steps.")

            # Validate each step has required fields
            for idx, step in enumerate(plan):
                if not isinstance(step, dict):
                    raise ValueError(f"Step {idx} is not a dictionary.")
                if "id" not in step:
                    step["id"] = f"step_{idx + 1}"
                if "tool" not in step:
                    raise ValueError(f"Step {step['id']} missing 'tool' name.")
                if "params" not in step or not isinstance(step["params"], dict):
                    step["params"] = {}
                if "dependencies" not in step or not isinstance(step["dependencies"], list):
                    step["dependencies"] = []

            logger.info("Plan parsed successfully with %d steps.", len(plan))
            return plan

        except Exception as exc:
            logger.warning("Failed to parse plan JSON (%s), falling back. Raw text: %r", exc, text)
            return self._fallback_plan(query)

    def _fallback_plan(self, query: str) -> List[Dict[str, Any]]:
        """
        Fallback plan in case planner fails or outputs invalid JSON.
        Runs a search on 'law' by default or a general LLM response.
        """
        logger.info("Providing fallback single-step plan.")
        # Detect if it looks like a vertical specific question
        vertical = "law"
        lower_q = query.lower()
        for v in SUPPORTED_VERTICALS:
            if v in lower_q:
                vertical = v
                break

        return [
            {
                "id": "step_1",
                "tool": "search_documents",
                "params": {
                    "vertical": vertical,
                    "query": query,
                },
                "dependencies": [],
            }
        ]
