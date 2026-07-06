"""
Pydantic v2 Output Schemas — one typed model per vertical.

Every generator must return one of these models (not raw dicts).
Enables automatic validation, serialization, and OpenAPI documentation.

Hierarchy:
    VerticalOutput          ← base for all verticals
    ├── RiskOutput          ← law + startup
    ├── ComplianceOutput    ← compliance
    ├── FriendlyOutput      ← hr
    └── AcademicOutput      ← university
"""
from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator


# ─── Shared Enums ────────────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    HIGH   = "HIGH"
    MEDIUM = "MEDIUM"
    LOW    = "LOW"


class ConfidenceLevel(str, Enum):
    HIGH   = "HIGH"
    MEDIUM = "MEDIUM"
    LOW    = "LOW"


class ComplianceStatus(str, Enum):
    COMPLIANT     = "COMPLIANT"
    NON_COMPLIANT = "NON-COMPLIANT"
    UNCLEAR       = "UNCLEAR"


# ─── Shared Sub-Models ───────────────────────────────────────────────────────

class Citation(BaseModel):
    """A reference to a specific clause, article, or page in a document."""
    clause:  Optional[str] = None
    article: Optional[str] = None
    page:    Optional[int] = None


class AcademicCitation(BaseModel):
    """A reference to a specific paper, section, and author."""
    author:  str
    year:    str
    section: str


class ChunkResult(BaseModel):
    """
    A single retrieved chunk from the Neo4j graph.
    Produced by all retrievers and consumed by the reranker → context manager → generator.
    """
    id:            str
    text:          str
    enriched_text: Optional[str]  = None   # OCR / visual description overlay
    page:          Optional[int]  = None
    doc_id:        Optional[str]  = None
    doc_name:      Optional[str]  = None
    chunk_type:    Optional[str]  = None   # clause / article / topic / term / section
    clause_ref:    Optional[str]  = None   # law vertical
    article_ref:   Optional[str]  = None   # compliance vertical
    section:       Optional[str]  = None   # university vertical
    employee_type: Optional[str]  = None   # hr vertical
    defined_term:  Optional[str]  = None   # startup vertical
    superseded:    Optional[bool] = False
    score:         float          = 0.0    # vector similarity score
    rerank_score:  Optional[float] = None  # CrossEncoder score (overrides score)

    @property
    def best_score(self) -> float:
        """Returns rerank_score if available, else raw vector score."""
        return self.rerank_score if self.rerank_score is not None else self.score


# ─── Base Output ─────────────────────────────────────────────────────────────

class VerticalOutput(BaseModel):
    """Base class for all vertical output schemas. Never instantiate directly."""
    answer:      str
    confidence:  ConfidenceLevel = ConfidenceLevel.LOW
    chunks_used: List[str]       = Field(default_factory=list)
    not_found:   bool            = False

    model_config = {"use_enum_values": True}


# ─── Law / Startup Vertical ──────────────────────────────────────────────────

class RiskOutput(VerticalOutput):
    """Output schema for law and startup verticals."""
    citations:       List[Citation]    = Field(default_factory=list)
    risk_level:      RiskLevel         = RiskLevel.LOW
    red_flags:       List[str]         = Field(default_factory=list)
    # Startup-specific extras (optional for law)
    plain_english:   Optional[str]     = None
    founder_risk:    Optional[RiskLevel] = None
    market_standard: Optional[str]    = None
    related_terms:   List[str]         = Field(default_factory=list)


# ─── Compliance Vertical ─────────────────────────────────────────────────────

class ComplianceOutput(VerticalOutput):
    """Output schema for the compliance vertical."""
    regulation_id:     Optional[str]      = None
    section:           Optional[str]      = None
    compliance_status: ComplianceStatus   = ComplianceStatus.UNCLEAR
    version_warning:   bool               = False
    citations:         List[Citation]     = Field(default_factory=list)


# ─── HR Vertical ─────────────────────────────────────────────────────────────

class FriendlyOutput(VerticalOutput):
    """Output schema for the HR vertical."""
    policy_section:    Optional[str] = None
    applies_to:        List[str]     = Field(default_factory=list)
    related_policies:  List[str]     = Field(default_factory=list)


# ─── University Vertical ─────────────────────────────────────────────────────

class AcademicOutput(VerticalOutput):
    """Output schema for the university / research paper vertical."""
    paper_title:      Optional[str]         = None
    authors:          List[str]             = Field(default_factory=list)
    abstract_summary: Optional[str]         = None
    citations:        List[AcademicCitation] = Field(default_factory=list)
    contradictions:   List[str]             = Field(default_factory=list)
    related_papers:   List[str]             = Field(default_factory=list)

    @field_validator("authors", "contradictions", "related_papers", mode="before")
    @classmethod
    def coerce_null_to_list(cls, v: Any) -> List[str]:
        """If the LLM returns the string 'null' or None, return an empty list."""
        if v is None or v == "null" or v == "None":
            return []
        if isinstance(v, list):
            return v
        return []
