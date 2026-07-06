"""
Vertical Configuration Registry.

Each vertical defines its own chunking strategy, retrieval depth,
scoring thresholds, token budget, and LLM system prompt.

To add a new vertical: add a new key to VERTICAL_CONFIGS and wire
it up in factory.py.
"""
from __future__ import annotations
from typing import Any, Dict

VERTICAL_CONFIGS: Dict[str, Dict[str, Any]] = {

    # ── Law ───────────────────────────────────────────────────────────────────
    "law": {
        "chunk_size":    400,
        "chunk_overlap": 80,
        "top_k":         15,
        "token_budget":  4096,
        "score_floor":   0.40,
        "system_prompt": (
            "You are a senior legal assistant. Answer ONLY from retrieved clauses. "
            "Always cite the clause number and page. "
            "Assign every answer a risk level: HIGH / MEDIUM / LOW. "
            "Never interpret beyond what is explicitly written in the document."
        ),
        "output_schema": "RiskOutput",
    },

    # ── Compliance ────────────────────────────────────────────────────────────
    "compliance": {
        "chunk_size":       500,
        "chunk_overlap":    100,
        "top_k":            10,
        "token_budget":     4096,
        "score_floor":      0.45,
        "version_awareness": True,
        "system_prompt": (
            "You are a compliance officer. Map every answer to a specific regulation ID and section. "
            "State clearly: COMPLIANT / NON-COMPLIANT / UNCLEAR. "
            "Flag if the document version may be outdated compared to current regulation."
        ),
        "output_schema": "ComplianceOutput",
    },

    # ── HR ────────────────────────────────────────────────────────────────────
    "hr": {
        "chunk_size":    500,
        "chunk_overlap": 100,
        "top_k":         8,
        "token_budget":  3000,
        "score_floor":   0.35,
        "role_filtering": True,
        "system_prompt": (
            "Answer as a friendly, helpful HR assistant. Be clear and jargon-free. "
            "Always cite the exact policy section. "
            "If the answer differs by employee type (full-time vs contractor), say so explicitly."
        ),
        "output_schema": "FriendlyOutput",
    },

    # ── Startup ───────────────────────────────────────────────────────────────
    "startup": {
        "chunk_size":    400,
        "chunk_overlap": 80,
        "top_k":         15,
        "token_budget":  4096,
        "score_floor":   0.40,
        "system_prompt": (
            "Explain contract terms in plain English — no legalese. "
            "Explicitly flag any founder-unfriendly terms. "
            "Compare with market standard where known."
        ),
        "output_schema": "RiskOutput",
    },

    # ── University ────────────────────────────────────────────────────────────
    "university": {
        "chunk_size":              500,
        "chunk_overlap":           100,
        "top_k":                   25,
        "token_budget":            5500,
        "score_floor":             0.38,
        "contradiction_detection": True,
        "system_prompt": (
            "You are a specialized Academic Research Assistant. "
            "Answer questions about research papers with high precision and academic rigor. "
            "ALWAYS populate 'paper_title', 'authors', and 'abstract_summary' when identifying a paper. "
            "Look for title and authors in [VISUAL DESCRIPTION] chunks from Page 1. "
            "Use 'citations' to link every claim to its source author, year, and section. "
            "If you find chart/figure descriptions, use that data to support your findings."
        ),
        "output_schema": "AcademicOutput",
    },
}

# Convenience: quick lookup for valid vertical names
SUPPORTED_VERTICALS = list(VERTICAL_CONFIGS.keys())
