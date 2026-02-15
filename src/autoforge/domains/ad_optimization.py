"""Ad Optimization domain — prompts and audit rules."""

from __future__ import annotations

from typing import Any

from ..models import AuditResult

DESCRIPTION = "広告運用の最適化提案（入札、KW、予算、ターゲティング）"

SYSTEM_PROMPT = """あなたは広告運用の上級コンサルタントです。
以下のルールに従って提案を生成してください：

1. 「守り」だけでなく「攻め」の提案を必ず含める（入札引き上げ、新KW追加等）
2. 具体的な数値（入札額、予算額、想定CPA）を含める
3. 季節・天候・地域の特性を考慮する
4. 過去の成功パターンがあれば必ず参照する

出力形式（JSON）:
{
  "recommendations": [
    {
      "type": "bid_adjustment|keyword_add|keyword_exclude|budget_change|targeting",
      "action": "具体的なアクション",
      "reason": "根拠",
      "expected_impact": "想定効果",
      "priority": "high|medium|low",
      "specific_values": {}
    }
  ],
  "summary": "全体の方針要約",
  "risk_assessment": "リスク評価"
}"""


def audit(proposal: dict[str, Any]) -> AuditResult:
    """ECK-lite audit for ad optimization proposals."""
    errors: list[str] = []
    warnings: list[str] = []
    recommendations = proposal.get("recommendations", [])

    if not recommendations:
        return AuditResult(is_valid=False, errors=["提案が空です"])

    # Rule 1: Must have at least one offensive recommendation
    has_offensive = any(
        r.get("type") in ("bid_adjustment", "keyword_add", "targeting", "budget_change")
        and "引き下げ" not in r.get("action", "")
        and "削減" not in r.get("action", "")
        for r in recommendations
    )
    if not has_offensive:
        warnings.append("全ての提案が守備的です。攻めの提案を追加してください。")

    # Rule 2: Check for specific values
    missing_values = [r for r in recommendations if not r.get("specific_values")]
    if missing_values:
        warnings.append(f"{len(missing_values)}件の提案に具体的な数値がありません")

    # Rule 3: Bid adjustments within reasonable range
    for r in recommendations:
        vals = r.get("specific_values", {})
        bid_change = vals.get("bid_change_percent")
        if bid_change is not None and abs(bid_change) > 50:
            errors.append(f"入札変更率が{bid_change}%は極端すぎます（上限±50%）")

    # Rule 4: Budget changes should be gradual
    for r in recommendations:
        vals = r.get("specific_values", {})
        budget_change = vals.get("budget_change_percent")
        if budget_change is not None and abs(budget_change) > 30:
            warnings.append(f"予算変更率{budget_change}%は急激です（推奨±30%以内）")

    return AuditResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)
