"""
WebSocket streaming routes — yields LLM response tokens in real-time.
Includes:
- Input guardrails checking (toxic prompt & leakage prevention).
- SQLite-backed semantic cache bypass lookup.
- Real-time step progress tracing & streaming final synthesis for Agent query path.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncIterator

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.dependencies import get_embedding
from app.config.verticals import SUPPORTED_VERTICALS
from app.generators._base import parse_json_response
from app.core.guardrails import check_guardrails
from app.agent.agent import run_agent

logger = logging.getLogger("docqa.api.stream")
router = APIRouter()


class StreamingJsonExtractor:
    def __init__(self):
        self.buffer = ""
        self.in_answer = False
        self.escaped = False
        self.pattern = re.compile(r'"answer"\s*:\s*"')

    def feed(self, token: str) -> str:
        self.buffer += token
        output = ""
        
        if not self.in_answer:
            match = self.pattern.search(self.buffer)
            if match:
                self.in_answer = True
                start_idx = match.end()
                content = self.buffer[start_idx:]
                self.buffer = ""
                output += self.process_string_content(content)
        else:
            output += self.process_string_content(token)
            
        return output

    def process_string_content(self, text: str) -> str:
        res = []
        for char in text:
            if self.escaped:
                if char == 'n':
                    res.append('\n')
                elif char == 't':
                    res.append('\t')
                elif char == 'r':
                    res.append('\r')
                elif char == 'b':
                    res.append('\b')
                elif char == 'f':
                    res.append('\f')
                else:
                    res.append(char)
                self.escaped = False
            elif char == '\\':
                self.escaped = True
            elif char == '"':
                self.in_answer = False
                break
            else:
                res.append(char)
        return "".join(res)


class StreamingResponseFilter:
    def __init__(self):
        self.buffer = ""
        self.mode = None  # "json" or "plain"
        self.extractor = None

    def feed(self, token: str) -> str:
        if self.mode is None:
            self.buffer += token
            stripped = self.buffer.strip()
            if not stripped:
                return ""

            fence_stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)

            if fence_stripped.startswith("{"):
                self.buffer = fence_stripped

                if len(self.buffer) > 200 and '"answer"' not in self.buffer:
                    self.mode = "plain"
                    ret = self.buffer
                    self.buffer = ""
                    return ret

                pattern = re.compile(r'"answer"\s*:\s*"')
                match = pattern.search(self.buffer)
                if match:
                    self.mode = "json"
                    self.extractor = StreamingJsonExtractor()
                    ret = self.extractor.feed(self.buffer)
                    self.buffer = ""
                    return ret
                return ""
            elif stripped.startswith("{"):
                if len(self.buffer) > 200 and '"answer"' not in self.buffer:
                    self.mode = "plain"
                    ret = self.buffer
                    self.buffer = ""
                    return ret

                pattern = re.compile(r'"answer"\s*:\s*"')
                match = pattern.search(self.buffer)
                if match:
                    self.mode = "json"
                    self.extractor = StreamingJsonExtractor()
                    ret = self.extractor.feed(self.buffer)
                    self.buffer = ""
                    return ret
                return ""
            else:
                self.mode = "plain"
                ret = self.buffer
                self.buffer = ""
                return ret
        elif self.mode == "plain":
            return token
        else:
            return self.extractor.feed(token)


# ─── Standard RAG WebSocket ──────────────────────────────────────────────────

@router.websocket("/stream")
@router.websocket("/ws/query")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket RAG streaming server.
    Optimized: Includes prompt guardrails checking and semantic caching lookup.
    """
    await websocket.accept()
    logger.info("WebSocket connection established.")

    try:
        # 1. Receive query payload
        raw_msg = await websocket.receive_text()
        try:
            payload = json.loads(raw_msg)
        except json.JSONDecodeError:
            await websocket.send_json({"error": "Invalid JSON format."})
            await websocket.close(code=1003)
            return

        is_frontend = "question" in payload
        query_text = payload.get("question") or payload.get("query_text")
        tenant_id  = payload.get("tenant_id")
        vertical   = payload.get("vertical")
        keyword    = payload.get("keyword", "")

        # 2. Validation
        if not all([query_text, tenant_id, vertical]):
            await websocket.send_json({"error": "Missing required fields: question/query_text, tenant_id, vertical."})
            await websocket.close(code=1008)
            return

        if vertical != "auto" and vertical not in SUPPORTED_VERTICALS:
            await websocket.send_json({"error": f"Unsupported vertical '{vertical}'."})
            await websocket.close(code=1008)
            return

        # ── Guardrail check ──
        violation = check_guardrails(query_text)
        if violation:
            logger.warning("Safety Guardrail Violation for query %r: %s", query_text, violation)
            if is_frontend:
                await websocket.send_json({
                    "type": "token",
                    "data": violation
                })
                await websocket.send_json({
                    "type": "done",
                    "data": {
                        "content": violation,
                        "answer": violation,
                        "citations": [],
                        "not_found": True
                    }
                })
            else:
                await websocket.send_json({"token": violation})
                await websocket.send_json({"done": True})
            await websocket.close()
            return

        # Fetch dependency singletons from app state
        app              = websocket.app
        cf_client        = app.state.cf_client
        reranker         = app.state.reranker
        graph_store      = app.state.graph_store
        pipeline_factory = app.state.pipeline_factory
        semantic_cache   = app.state.semantic_cache

        # AI Intent Router / Auto-vertical detection
        if vertical == "auto":
            try:
                await websocket.send_json({
                    "type": "status",
                    "data": "🧠 AI Routing: Classifying query intent..."
                })
                system_prompt = (
                    "You are an intent routing agent. Classify the user query into exactly one of these vertical categories:\n"
                    "- 'law' (for legal contracts, NDAs, clauses, legal obligations)\n"
                    "- 'university' (for academic papers, research, authors, journal publications)\n"
                    "- 'startup' (for pitch decks, startup investments, VCs, pitch deck contributors)\n"
                    "- 'compliance' (for compliance policies, regulatory standards, audits)\n"
                    "- 'hr' (for employee manuals, handbooks, HR questions)\n\n"
                    "Respond with ONLY the classification category name (exactly one of 'law', 'university', 'startup', 'compliance', 'hr') in lowercase. Do not write anything else."
                )
                routing_response = await cf_client.chat(
                    system_prompt=system_prompt,
                    user_message=query_text,
                    max_tokens=15,
                    temperature=0.0
                )
                detected = routing_response.strip().lower()
                matched_v = None
                for v in ("law", "university", "startup", "compliance", "hr"):
                    if v in detected:
                        matched_v = v
                        break
                if matched_v:
                    vertical = matched_v
                    logger.info("🧠 AI Router matched query to vertical: %s", vertical)
                    await websocket.send_json({
                        "type": "status",
                        "data": f"✅ AI Router matches: Shifting to {vertical.upper()} vertical..."
                    })
                else:
                    vertical = "university"  # fallback
                    await websocket.send_json({
                        "type": "status",
                        "data": "⚠️ AI Router fallback: Shifting to UNIVERSITY vertical..."
                    })
            except Exception as routing_err:
                logger.error("AI Routing failed: %s", routing_err)
                vertical = "university"

        # 3. Check Semantic Cache
        try:
            embedding = await get_embedding(query_text)
            cached = semantic_cache.get(tenant_id, vertical, embedding)
            if cached:
                ans = cached.get("answer", cached.get("content", ""))
                if is_frontend:
                    await websocket.send_json({
                        "type": "token",
                        "data": ans
                    })
                    await websocket.send_json({
                        "type": "done",
                        "data": cached
                    })
                else:
                    await websocket.send_json({"token": ans})
                    await websocket.send_json({"done": True})
                await websocket.close()
                return
        except Exception as exc:
            logger.error("Failed to generate embedding / lookup cache for stream: %s", exc)
            if is_frontend:
                await websocket.send_json({
                    "type": "error",
                    "data": f"Error initiating retrieval: {exc}"
                })
            else:
                await websocket.send_json({"error": f"Error initiating retrieval: {exc}"})
            await websocket.close(code=1011)
            return

        # 4. Assemble pipeline
        pipeline = pipeline_factory.build_pipeline(vertical, cf_client, reranker)

        # Override parameters from payload if provided
        temperature = payload.get("temperature")
        if temperature is not None:
            pipeline.config["temperature"] = float(temperature)
            
        top_k_val = payload.get("top_k")
        if top_k_val is not None:
            pipeline.config["top_k"] = int(top_k_val)
            
        score_floor = payload.get("score_floor")
        if score_floor is not None:
            pipeline.config["score_floor"] = float(score_floor)

        # 5. Retrieve & Rerank Chunks
        top_k      = pipeline.config.get("top_k", 10)
        raw_chunks = await pipeline.retriever.retrieve_with_fallback(
            embedding, graph_store, tenant_id, top_k, keyword=keyword
        )

        if not raw_chunks:
            fallback_ans = "I could not find relevant information in the provided documents."
            if is_frontend:
                await websocket.send_json({
                    "type": "chunks",
                    "data": []
                })
                await websocket.send_json({
                    "type": "token",
                    "data": fallback_ans
                })
                await websocket.send_json({
                    "type": "done",
                    "data": {
                        "content": fallback_ans,
                        "citations": []
                    }
                })
            else:
                await websocket.send_json({"token": fallback_ans})
                await websocket.send_json({"done": True})
            await websocket.close()
            return

        reranked    = await pipeline.reranker.rerank(query_text, raw_chunks)
        floor       = pipeline.config.get("score_floor", 0.40)
        qualified   = [c for c in reranked if c.best_score >= floor] or reranked[:5]

        # 6. Send evidence chunks if frontend
        if is_frontend:
            chunks_data = []
            for c in qualified:
                chunks_data.append({
                    "page": c.page,
                    "score": c.best_score,
                    "text": c.text,
                    "doc_name": c.doc_name
                })
            await websocket.send_json({
                "type": "chunks",
                "data": chunks_data
            })

        # 7. Build LLM Context
        context_str, used_ids, _ = pipeline.ctx_mgr.build_context(qualified, pipeline.vertical)

        # 8. Stream LLM tokens
        response_filter = StreamingResponseFilter()
        complete_raw_text = ""
        complete_filtered_text = ""

        try:
            async for token in pipeline.generator.stream(
                query_text,
                qualified,
                {**pipeline.config, "_context": context_str, "_used_ids": used_ids},
            ):
                complete_raw_text += token
                if is_frontend:
                    filtered = response_filter.feed(token)
                    if filtered:
                        complete_filtered_text += filtered
                        await websocket.send_json({
                            "type": "token",
                            "data": filtered
                        })
                else:
                    await websocket.send_json({"token": token})
        except Exception as e_stream:
            logger.warning("Streaming call failed: %s. Falling back to non-streaming.", e_stream)

        # Fallback to non-streaming if stream yielded no tokens
        if not complete_raw_text or len(complete_raw_text.strip()) < 10:
            logger.info("Stream yielded empty response. Falling back to non-streaming generate.")
            try:
                output_model = await pipeline.generator.generate(
                    query_text,
                    qualified,
                    {**pipeline.config, "_context": context_str, "_used_ids": used_ids},
                )
                output_dict = output_model.model_dump()
                answer_text = output_dict.get("answer", "")
                
                if is_frontend:
                    if answer_text:
                        await websocket.send_json({
                            "type": "token",
                            "data": answer_text
                        })
                    output_dict["content"] = answer_text
                    
                    if "citations" in output_dict:
                        citations = output_dict["citations"]
                        if isinstance(citations, list):
                            formatted_citations = []
                            for cit in citations:
                                if isinstance(cit, dict):
                                    formatted_citations.append(cit)
                                elif hasattr(cit, "model_dump"):
                                    formatted_citations.append(cit.model_dump())
                                else:
                                    formatted_citations.append(str(cit))
                            output_dict["citations"] = formatted_citations
                            
                    output_dict["vertical"] = active_vertical
                    await websocket.send_json({
                        "type": "done",
                        "data": output_dict
                    })
                    
                    # Cache output
                    semantic_cache.set(tenant_id, vertical, query_text, embedding, output_dict)
                else:
                    await websocket.send_json({"token": answer_text})
                    await websocket.send_json({"done": True})
                    
                    # Cache output
                    semantic_cache.set(tenant_id, vertical, query_text, embedding, {"answer": answer_text})
                
                logger.info("WebSocket query complete using fallback generate.")
                return
            except Exception as exc:
                logger.error("Fallback non-streaming generate failed: %s", exc)
                raise exc

        # 9. Send completion done event
        if is_frontend:
            parsed_data = {}
            raw_for_parse = re.sub(r"^```(?:json)?\s*", "", complete_raw_text.strip(), flags=re.IGNORECASE)
            raw_for_parse = re.sub(r"\s*```$", "", raw_for_parse).strip()
            if raw_for_parse.startswith("{"):
                try:
                    parsed_data = parse_json_response(raw_for_parse)
                except Exception:
                    pass

            if "answer" in parsed_data:
                parsed_data["content"] = parsed_data["answer"]
            elif not parsed_data.get("content"):
                parsed_data["content"] = complete_filtered_text or complete_raw_text

            if "citations" in parsed_data:
                citations = parsed_data["citations"]
                if isinstance(citations, list):
                    formatted_citations = []
                    for cit in citations:
                        if isinstance(cit, dict):
                            formatted_citations.append(cit)
                        elif hasattr(cit, "model_dump"):
                            formatted_citations.append(cit.model_dump())
                        else:
                            formatted_citations.append(str(cit))
                    parsed_data["citations"] = formatted_citations

            parsed_data["vertical"] = active_vertical
            await websocket.send_json({
                "type": "done",
                "data": parsed_data
            })
            
            # Cache output
            semantic_cache.set(tenant_id, vertical, query_text, embedding, parsed_data)
        else:
            await websocket.send_json({"done": True})
            
            # Cache output
            semantic_cache.set(tenant_id, vertical, query_text, embedding, {"answer": complete_raw_text})

        logger.info("WebSocket query streaming complete for query: %r", query_text)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected by client.")
    except Exception as exc:
        logger.exception("WebSocket stream error occurred:")
        try:
            if is_frontend:
                await websocket.send_json({
                    "type": "error",
                    "data": f"Internal server error: {exc}"
                })
            else:
                await websocket.send_json({"error": f"Internal server error: {exc}"})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ─── Multi-Step Agent WebSocket ──────────────────────────────────────────────

@router.websocket("/ws/agent")
async def websocket_agent_endpoint(websocket: WebSocket):
    """
    WebSocket Agent orchestration endpoint.
    Accepts JSON input:
        {
            "query":     str,
            "tenant_id": str
        }
    Yields intermediate planning/execution status updates and streamed synthesis tokens.
    """
    await websocket.accept()
    logger.info("WebSocket agent query connection established.")

    try:
        # Receive payload
        raw_msg = await websocket.receive_text()
        try:
            payload = json.loads(raw_msg)
        except json.JSONDecodeError:
            await websocket.send_json({"error": "Invalid JSON format."})
            await websocket.close(code=1003)
            return

        query_text = payload.get("query")
        tenant_id  = payload.get("tenant_id")

        if not query_text or not tenant_id:
            await websocket.send_json({"error": "Missing required fields: query, tenant_id."})
            await websocket.close(code=1008)
            return

        # ── Guardrail check ──
        violation = check_guardrails(query_text)
        if violation:
            logger.warning("Safety Guardrail Violation for agent query: %s", violation)
            await websocket.send_json({"type": "status", "data": "Checking query guardrails..."})
            await websocket.send_json({"type": "token", "data": violation})
            await websocket.send_json({
                "type": "done",
                "data": {
                    "answer": violation,
                    "success": False
                }
            })
            await websocket.close()
            return

        # Singletons from app state
        app              = websocket.app
        cf_client        = app.state.cf_client
        store            = app.state.graph_store
        pipeline_factory = app.state.pipeline_factory
        reranker         = app.state.reranker
        semantic_cache   = app.state.semantic_cache

        # Check Semantic Cache
        try:
            embedding = await get_embedding(query_text)
            cached = semantic_cache.get(tenant_id, "agent", embedding)
            if cached:
                await websocket.send_json({"type": "status", "data": "🎯 Semantic Cache HIT! Loading response..."})
                ans = cached.get("answer", "")
                await websocket.send_json({"type": "token", "data": ans})
                await websocket.send_json({"type": "done", "data": cached})
                await websocket.close()
                return
        except Exception as e_cache:
            logger.warning("Cache fetch failed: %s", e_cache)

        # Callbacks defined for run_agent
        async def on_status(msg: str):
            try:
                await websocket.send_json({"type": "status", "data": msg})
            except Exception:
                pass

        async def on_token(token: str):
            try:
                await websocket.send_json({"type": "token", "data": token})
            except Exception:
                pass

        # Execute multi-step agent flow
        result = await run_agent(
            query=query_text,
            tenant_id=tenant_id,
            store=store,
            cf_client=cf_client,
            pipeline_factory=pipeline_factory,
            reranker=reranker,
            on_status=on_status,
            on_token=on_token,
        )

        # Cache response semantically
        if result.get("success", False) and "embedding" in locals():
            semantic_cache.set(tenant_id, "agent", query_text, embedding, result)

        await websocket.send_json({
            "type": "done",
            "data": result
        })

    except WebSocketDisconnect:
        logger.info("WebSocket agent connection disconnected.")
    except Exception as exc:
        logger.exception("WebSocket agent execution error:")
        try:
            await websocket.send_json({"type": "error", "data": f"Agent query error: {exc}"})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
