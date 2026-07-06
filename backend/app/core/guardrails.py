"""
Guardrails — prompt validation and safety checks.
"""
from __future__ import annotations

import re
from typing import Optional

_JAILBREAK_PATTERNS = [
    r"ignore\s+previous\s+instructions",
    r"system\s+prompt",
    r"leak\s+your\s+rules",
    r"reveal\s+your\s+prompt",
    r"act\s+as\s+a\s+jailbroken",
]

def check_guardrails(query: str) -> Optional[str]:
    """
    Check query for safety violations or prompt injections.
    Returns refusal string if violation detected, else None.
    """
    q_lower = query.lower()
    
    # 1. Jailbreak attempts
    for pattern in _JAILBREAK_PATTERNS:
        if re.search(pattern, q_lower):
            return "Safety Check: Blocked query (potential prompt injection attempt)."

    # 2. Content security terms
    toxic_terms = ["bypass authentication", "malware", "ddos execution", "brute force login"]
    for term in toxic_terms:
        if term in q_lower:
            return f"Safety Check: Request blocked due to inappropriate content request ('{term}')."
            
    return None
