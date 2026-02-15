"""
Domain Registry — pluggable domain prompts and audit rules.
Each domain module exports `SYSTEM_PROMPT` and `audit(proposal) -> AuditResult`.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any
import importlib
import structlog

from ..models import AuditResult

logger = structlog.get_logger()

# Dynamically import domain modules. If a module fails to import we log a
# warning and continue; this allows the application to start even if a
# non-critical domain module has issues.
_REGISTRY: dict[str, ModuleType] = {}
_DOMAIN_MODULES = [
    "ad_optimization",
    "music_production",
    "sales",
    "customer_support",
]

for _name in _DOMAIN_MODULES:
    try:
        mod = importlib.import_module(f".{_name}", package=__package__)
        _REGISTRY[_name] = mod
    except Exception as e:
        logger.warning("domain_import_failed", domain=_name, error=str(e))

# Default prompt for unknown domains
_DEFAULT_PROMPT = (
    "あなたは分析エキスパートです。"
    "データに基づいた具体的な提案をJSON形式で生成してください。"
    '出力形式: {"recommendations": [{"type": str, "action": str, '
    '"reason": str, "expected_impact": str, "priority": "high|medium|low", '
    '"specific_values": {}},], "summary": str, "risk_assessment": str}'
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
