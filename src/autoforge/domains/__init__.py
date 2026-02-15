"""
Domain Registry — pluggable domain prompts and audit rules.
Each domain module exports `SYSTEM_PROMPT` and `audit(proposal) -> AuditResult`.
"""

from __future__ import annotations

from typing import Any

from ..models import AuditResult

# Import domain modules
from . import ad_optimization, customer_support, music_production, sales

_REGISTRY: dict[str, Any] = {
    "ad_optimization": ad_optimization,
    "music_production": music_production,
    "sales": sales,
    "customer_support": customer_support,
}

# Default prompt for unknown domains
_DEFAULT_PROMPT = (
    "あなたは分析エキスパートです。"
    "データに基づいた具体的な提案をJSON形式で生成してください。"
    '出力形式: {"recommendations": [{"type": str, "action": str, '
    '"reason": str, "expected_impact": str, "priority": "high|medium|low", '
    '"specific_values": {}}], "summary": str, "risk_assessment": str}'
)


def get_domain_prompt(domain: str) -> str:
    """Get system prompt for the specified domain."""
    mod = _REGISTRY.get(domain)
    if mod:
        return mod.SYSTEM_PROMPT
    return _DEFAULT_PROMPT


def audit_proposal(proposal: dict[str, Any], domain: str) -> AuditResult:
    """Run domain-specific audit rules."""
    errors: list[str] = []
    warnings: list[str] = []

    recommendations = proposal.get("recommendations", [])
    if not recommendations:
        return AuditResult(is_valid=False, errors=["提案が空です"])

    mod = _REGISTRY.get(domain)
    if mod and hasattr(mod, "audit"):
        return mod.audit(proposal)

    # Unknown domain — pass with no domain-specific checks
    return AuditResult(is_valid=True, errors=errors, warnings=warnings)


def list_domains() -> list[dict[str, str]]:
    """List all available domains with descriptions."""
    result = []
    for name, mod in _REGISTRY.items():
        desc = getattr(mod, "DESCRIPTION", name)
        result.append({"id": name, "description": desc})
    return result
