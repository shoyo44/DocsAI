"""
Document Classifier Agent  — v3
================================

Two-phase classification agent for uploaded documents.

Phase 1 — Summarisation
    Extracts raw text, asks the LLM for a structured summary in JSON.

Phase 2 — Classification
    Uses the summary + a text excerpt to select the correct vertical,
    confidence level, and produce a human-readable AI suggestion.

Key design decisions for Llama-3.3-70b-instruct reliability
------------------------------------------------------------
* System prompt is SHORT and purely declarative (role + output format).
* The JSON SCHEMA is shown in the USER turn, right before the document
  text, so the model sees it immediately before generating its response.
* No angle-bracket placeholders (Llama copies them literally).
* Suffix "Respond with ONLY the JSON:" forces the model to start directly.
* Keyword-based fallback ensures we always return a usable vertical even
  when the LLM fails entirely.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("docqa.classifier_agent")

# ── Supported verticals ───────────────────────────────────────────────────────
VERTICALS: Dict[str, str] = {
    "law":        "Legal contracts, NDAs, terms of service, court orders, clauses",
    "university": "Academic research papers, journal articles, theses, studies",
    "startup":    "Pitch decks, venture capital docs, term sheets, investment agreements",
    "compliance": "Compliance policies, regulatory standards, audit reports, ISO/GDPR docs",
    "hr":         "Employee handbooks, HR policies, job descriptions, onboarding docs",
}

# ── Extraction limits ─────────────────────────────────────────────────────────
_MAX_PAGES      = 4
_MAX_PER_PAGE   = 1500   # chars per page
_MAX_SNIPPET    = 4500   # total chars sent to LLM

# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────
#
# NOTE: System prompt is kept minimal.  The schema + data appear in the USER
#       turn so Llama's attention is on the schema just before generating.

_SYS_SUMMARISE = (
    "You are a document analysis assistant. "
    "Read the document text the user provides and fill in the JSON schema shown. "
    "Reply with ONLY the completed JSON — no prose, no markdown fences."
)

_SYS_CLASSIFY = (
    "You are a document routing assistant for DocsAI. "
    "Read the document information the user provides and fill in the JSON schema shown. "
    "Reply with ONLY the completed JSON — no prose, no markdown fences."
)

# ── User-turn templates ───────────────────────────────────────────────────────

_SUMMARISE_USER = """\
Filename: {filename}

Document text (first {pages} page(s)):
---
{text}
---

Fill in this JSON using only the information above:
{{
  "document_type": "e.g. Research Paper, Legal Contract, HR Policy, Pitch Deck, Compliance Report",
  "main_topics": ["topic 1", "topic 2", "topic 3"],
  "key_entities": ["entity 1", "entity 2"],
  "intended_audience": "e.g. Employees, Investors, Researchers, Legal team",
  "language_style": "Formal, Technical, Legal, Academic, or Casual"
}}

Respond with ONLY the JSON:"""

_CLASSIFY_USER = """\
Filename: {filename}

Document summary:
{summary}

Short excerpt from the document:
---
{excerpt}
---

Choose the single best vertical from these options:
  law        = Legal contracts, NDAs, clauses, court documents
  university = Academic papers, research articles, theses
  startup    = Pitch decks, VC term sheets, startup investment docs
  compliance = Compliance policies, regulatory standards, audit reports
  hr         = Employee handbooks, HR policies, job descriptions

Fill in this JSON:
{{
  "vertical": "law or university or startup or compliance or hr",
  "confidence": "HIGH or MEDIUM or LOW",
  "ai_suggestion": "2 sentences: which vertical was chosen and why, and what the user should do if wrong",
  "alternative_vertical": "second best vertical or null",
  "classification_notes": "one sentence about any ambiguity"
}}

Respond with ONLY the JSON:"""


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ClassificationResult:
    """Full output of the DocumentClassifierAgent."""
    summary: dict                    = field(default_factory=dict)
    vertical: str                    = "university"
    confidence: str                  = "LOW"
    ai_suggestion: str               = ""
    alternative_vertical: Optional[str] = None
    classification_notes: str        = ""
    pages_read: int                  = 0
    chars_extracted: int             = 0
    error: Optional[str]             = None

    def to_api_response(self) -> dict:
        return {
            "vertical":              self.vertical,
            "confidence":            self.confidence,
            "ai_suggestion":         self.ai_suggestion,
            "alternative_vertical":  self.alternative_vertical,
            "classification_notes":  self.classification_notes,
            "summary": {
                "document_type":      self.summary.get("document_type", ""),
                "main_topics":        self.summary.get("main_topics", []),
                "key_entities":       self.summary.get("key_entities", []),
                "intended_audience":  self.summary.get("intended_audience", ""),
                "language_style":     self.summary.get("language_style", ""),
                "excerpt_highlights": self.summary.get("excerpt_highlights", []),
            },
            "meta": {
                "pages_read": self.pages_read,
                "chars_used": self.chars_extracted,
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# Robust JSON parser — 5-layer fallback strategy
# ─────────────────────────────────────────────────────────────────────────────

def _parse_llm_json(raw: str, label: str) -> dict:
    """
    Parse an LLM response that should be JSON but may contain:
      • Markdown fences (```json ... ```)
      • Preamble or postamble text
      • Truncated output (cut off mid-object)
      • Single-quoted strings

    Returns a dict (possibly empty) — NEVER raises.
    """
    if not raw:
        return {}

    text = raw.strip()

    # Layer 1 — strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?```\s*$", "", text).strip()

    # Layer 2 — direct JSON parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Layer 3 — extract first complete {...} block
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}", text, re.DOTALL)
    if not match:
        # Broader search for any {...} span
        match = re.search(r"\{.*\}", text, re.DOTALL)

    if match:
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            pass

        # Layer 4 — auto-close truncated object
        extra_open_brackets = candidate.count("[") - candidate.count("]")
        extra_open_braces   = candidate.count("{") - candidate.count("}")
        # Only add closers when positive (don't add when already balanced/over-closed)
        closers = (
            "]" * max(0, extra_open_brackets)
            + "}" * max(0, extra_open_braces)
        )
        if closers:
            try:
                return json.loads(candidate + closers)
            except (json.JSONDecodeError, ValueError):
                pass

    # Layer 5 — field-by-field regex extraction
    logger.warning("[%s] JSON parse failed; extracting fields via regex", label)
    result: dict = {}

    # String fields
    for key in ("document_type", "intended_audience", "language_style",
                "vertical", "confidence", "ai_suggestion",
                "alternative_vertical", "classification_notes"):
        m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', text)
        if m:
            result[key] = m.group(1).strip()

    # Array fields
    for key in ("main_topics", "key_entities", "excerpt_highlights"):
        m = re.search(rf'"{key}"\s*:\s*\[([^\]]*)\]', text)
        if m:
            items = re.findall(r'"([^"]*)"', m.group(1))
            if items:
                result[key] = [i.strip() for i in items if i.strip()]

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Keyword-based fallback classifier
# ─────────────────────────────────────────────────────────────────────────────

_KW_RULES: List[tuple] = [
    ("compliance", ["gdpr", "iso", "audit", "regulation", "regulatory", "compliance",
                    "sox", "hipaa", "pci", "nist", "standard", "framework", "policy",
                    "data protection", "certif"]),
    ("law",        ["contract", "agreement", "clause", "liability", "indemnif", "nda",
                    "non-disclosure", "termination", "jurisdiction", "governing law",
                    "party", "parties", "whereas", "heretofore", "warranty", "breach",
                    "represent", "covenant"]),
    ("hr",         ["employee", "handbook", "leave", "vacation", "benefits",
                    "onboarding", "performance review", "human resource",
                    "salary", "compensation", "payroll", "recruitment", "workforce"]),
    ("startup",    ["pitch", "investor", "seed", "series a", "term sheet", "valuation",
                    "venture", "equity", "cap table", "runway", "funding", "startup",
                    "pre-money", "post-money", "convertible"]),
    ("university", ["abstract", "methodology", "hypothesis", "peer-reviewed", "citation",
                    "research", "study", "journal", "conference", "arxiv", "doi",
                    "keywords", "references", "bibliography", "findings", "experiment"]),
]


def _keyword_fallback(text: str) -> tuple[str, str]:
    """Score text against keyword rules. Returns (vertical, confidence_level)."""
    lower = text.lower()
    scores: dict[str, int] = {v: 0 for v in VERTICALS}
    for vertical, keywords in _KW_RULES:
        for kw in keywords:
            if kw in lower:
                scores[vertical] += 1

    best  = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())

    if total == 0:
        return "university", "LOW"

    ratio = scores[best] / total
    confidence = "HIGH" if ratio > 0.55 else ("MEDIUM" if ratio > 0.30 else "LOW")
    return best, confidence


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────

class DocumentClassifierAgent:
    """
    Two-phase document classification agent.

    Parameters
    ----------
    cf_client : Any
        CloudflareAI client with async ``chat(system_prompt, user_message, ...)`` method.
    max_pages : int
        Max leading pages to read from PDF. Default: 4.
    """

    def __init__(self, cf_client: Any, max_pages: int = _MAX_PAGES) -> None:
        self._cf        = cf_client
        self._max_pages = max_pages

    # ── Text extraction ───────────────────────────────────────────────────────

    def _extract_text(self, file_path: str) -> tuple[str, int]:
        """Return (snippet, pages_read). Never raises."""
        ext    = os.path.splitext(file_path)[1].lower()
        parts: List[str] = []
        pages  = 0

        if ext == ".pdf":
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(file_path)
                for i in range(min(self._max_pages, len(doc))):
                    t = doc[i].get_text("text").strip()
                    if t:
                        parts.append(t[:_MAX_PER_PAGE])
                        pages += 1
                doc.close()
            except Exception as e:
                logger.warning("PDF text extraction failed: %s", e)

        elif ext == ".docx":
            try:
                import docx as _docx
                d = _docx.Document(file_path)
                t = "\n".join(p.text for p in d.paragraphs if p.text.strip())
                parts.append(t[:_MAX_SNIPPET])
                pages = 1
            except Exception as e:
                logger.warning("DOCX extraction failed: %s", e)

        elif ext in (".txt", ".csv"):
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    parts.append(f.read(_MAX_SNIPPET))
                pages = 1
            except Exception as e:
                logger.warning("Plain text read failed: %s", e)

        elif ext in (".png", ".jpg", ".jpeg"):
            parts.append("[IMAGE — no readable text layer]")

        snippet = "\n\n".join(parts)[:_MAX_SNIPPET]
        return snippet, pages

    # ── LLM helper ───────────────────────────────────────────────────────────

    async def _llm(
        self,
        system: str,
        user:   str,
        max_tokens: int = 512,
        temperature: float = 0.05,
    ) -> str:
        """Call cf_client.chat and always return a string (never None)."""
        try:
            raw = await self._cf.chat(
                system_prompt=system,
                user_message=user,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return str(raw) if raw is not None else ""
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            raise

    # ── Phase 1 ───────────────────────────────────────────────────────────────

    async def _summarise(self, snippet: str, filename: str, pages: int) -> dict:
        user_msg = _SUMMARISE_USER.format(
            filename=filename,
            pages=pages,
            text=snippet,
        )
        logger.info("Phase 1 — summarising '%s' (%d chars, %d page(s))",
                    filename, len(snippet), pages)
        raw = await self._llm(_SYS_SUMMARISE, user_msg, max_tokens=450, temperature=0.05)
        logger.info("Phase 1 raw (%d chars): %.200s", len(raw), raw)
        parsed = _parse_llm_json(raw, "summarise")
        logger.info("Phase 1 parsed: %s", parsed)
        return parsed

    # ── Phase 2 ───────────────────────────────────────────────────────────────

    async def _classify(self, snippet: str, summary: dict, filename: str) -> dict:
        summary_str = (
            json.dumps(summary, indent=2)
            if summary
            else f"(summary unavailable — filename: {filename})"
        )
        user_msg = _CLASSIFY_USER.format(
            filename=filename,
            summary=summary_str,
            excerpt=snippet[:600],
        )
        logger.info("Phase 2 — classifying '%s'", filename)
        raw = await self._llm(_SYS_CLASSIFY, user_msg, max_tokens=320, temperature=0.0)
        logger.info("Phase 2 raw (%d chars): %.200s", len(raw), raw)
        parsed = _parse_llm_json(raw, "classify")
        logger.info("Phase 2 parsed: %s", parsed)
        return parsed

    # ── Main entry ────────────────────────────────────────────────────────────

    async def run(self, file_path: str, filename: str) -> ClassificationResult:
        """
        Run text extraction → summarisation → classification.
        Always returns a ClassificationResult — never raises.
        """
        result = ClassificationResult()

        # ── Extract ───────────────────────────────────────────────────────────
        try:
            snippet, pages = self._extract_text(file_path)
            result.pages_read      = pages
            result.chars_extracted = len(snippet)
        except Exception as e:
            result.error         = str(e)
            result.ai_suggestion = (
                "DocsAI could not read this file. "
                "Please select the document type manually."
            )
            return result

        # No text → filename-based keyword fallback
        if not snippet.strip():
            v, c = _keyword_fallback(filename.lower())
            result.vertical   = v
            result.confidence = c
            result.ai_suggestion = (
                "No readable text was found in this document (possibly a scanned image). "
                f"Based on the filename, it looks like a {v} document. "
                "Please verify and use 'Change type' if needed."
            )
            return result

        # ── Phase 1: Summarise ────────────────────────────────────────────────
        summary: dict = {}
        try:
            summary = await self._summarise(snippet, filename, pages)
            result.summary = summary
        except Exception as e:
            logger.error("Phase 1 failed: %s", e)
            # Continue — Phase 2 still runs with empty summary + raw snippet

        # ── Phase 2: Classify ─────────────────────────────────────────────────
        try:
            clf = await self._classify(snippet, summary, filename)

            detected = str(clf.get("vertical", "")).lower().strip()
            if detected not in VERTICALS:
                logger.warning("LLM returned invalid vertical '%s' — using keyword fallback", detected)
                detected, conf = _keyword_fallback(snippet)
                result.vertical              = detected
                result.confidence            = conf
                result.classification_notes  = "Keyword fallback used — LLM did not return a valid vertical."
                result.ai_suggestion         = (
                    f"The AI suggested this document belongs to the '{detected}' vertical "
                    f"based on keyword analysis ({conf.lower()} confidence). "
                    "Use 'Change type' below if this looks incorrect."
                )
            else:
                conf_raw = str(clf.get("confidence", "MEDIUM")).upper().strip()
                result.vertical              = detected
                result.confidence            = conf_raw if conf_raw in ("HIGH", "MEDIUM", "LOW") else "MEDIUM"
                result.ai_suggestion         = str(clf.get("ai_suggestion", "")).strip()
                result.classification_notes  = str(clf.get("classification_notes", "")).strip()

                alt = clf.get("alternative_vertical") or None
                if alt and str(alt).lower() in VERTICALS and str(alt).lower() != detected:
                    result.alternative_vertical = str(alt).lower()

                # Build fallback suggestion if LLM returned empty string
                if not result.ai_suggestion:
                    result.ai_suggestion = (
                        f"This document was classified as '{detected}' "
                        f"with {result.confidence.lower()} confidence. "
                        "Use 'Change type' below if this doesn't look right."
                    )

            logger.info("Classification done — vertical=%s confidence=%s",
                        result.vertical, result.confidence)

        except Exception as e:
            logger.error("Phase 2 failed: %s", e)
            # Ultimate fallback
            detected, conf     = _keyword_fallback(snippet)
            result.vertical    = detected
            result.confidence  = conf
            result.error       = str(e)
            result.ai_suggestion = (
                f"Classification encountered an error. "
                f"Keyword analysis suggests '{detected}' ({conf.lower()} confidence). "
                "Please verify and use 'Change type' if needed."
            )

        return result


# ─────────────────────────────────────────────────────────────────────────────
# CLI — python -m app.features.document_classifier_agent <file>
# ─────────────────────────────────────────────────────────────────────────────

async def _cli_main(file_path: str) -> None:
    from dotenv import load_dotenv
    load_dotenv()
    for candidate in [".env", "../.env", "../../.env"]:
        full = os.path.join(os.path.dirname(__file__), candidate)
        if os.path.exists(full):
            load_dotenv(full)
            break

    from app.core.cloudflare_ai import CloudflareAI
    cf = CloudflareAI(
        account_id=os.environ["CF_ACCOUNT_ID"],
        api_token=os.environ["CF_API_TOKEN"],
    )

    agent    = DocumentClassifierAgent(cf_client=cf)
    filename = os.path.basename(file_path)

    print(f"\n{'='*60}")
    print(f"  DocsAI Document Classifier Agent  v3")
    print(f"  File: {filename}")
    print(f"{'='*60}\n")

    result = await agent.run(file_path=file_path, filename=filename)

    print("── PHASE 1: DOCUMENT SUMMARY ─────────────────────────────────")
    if result.summary:
        print(json.dumps(result.summary, indent=2))
    else:
        print("  (no summary generated)")

    print("\n── PHASE 2: CLASSIFICATION ───────────────────────────────────")
    print(f"  Vertical    : {result.vertical.upper()}")
    print(f"  Confidence  : {result.confidence}")
    if result.alternative_vertical:
        print(f"  Alternative : {result.alternative_vertical}")
    print(f"\n  AI Suggestion:\n  {result.ai_suggestion}")
    if result.classification_notes:
        print(f"\n  Notes: {result.classification_notes}")
    if result.error:
        print(f"\n  ⚠ Error: {result.error}")

    print(f"\n── META ──────────────────────────────────────────────────────")
    print(f"  Pages read     : {result.pages_read}")
    print(f"  Chars extracted: {result.chars_extracted}")
    print(f"{'='*60}\n")

    await cf.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if len(sys.argv) < 2:
        print("Usage: python -m app.features.document_classifier_agent <path/to/file>")
        sys.exit(1)
    fp = sys.argv[1]
    if not os.path.exists(fp):
        print(f"Error: File not found — {fp}")
        sys.exit(1)
    asyncio.run(_cli_main(fp))
