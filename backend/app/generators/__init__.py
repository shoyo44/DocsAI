"""
Vertical-specific LLM response generators.

Each implements BaseGenerator[T] and returns a validated Pydantic output model.
Wired to verticals in factory.py:
    law, startup  → RiskGenerator      → RiskOutput
    compliance    → ComplianceGenerator → ComplianceOutput
    hr            → FriendlyGenerator  → FriendlyOutput
    university    → AcademicGenerator  → AcademicOutput
"""
from app.generators.risk       import RiskGenerator
from app.generators.compliance import ComplianceGenerator
from app.generators.friendly   import FriendlyGenerator
from app.generators.academic   import AcademicGenerator

__all__ = [
    "RiskGenerator",
    "ComplianceGenerator",
    "FriendlyGenerator",
    "AcademicGenerator",
]
