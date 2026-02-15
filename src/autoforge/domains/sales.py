"""Sales AI domain — prompts and audit rules for B2B/B2C sales proposals."""

from __future__ import annotations

from typing import Any

from ..models import AuditResult

DESCRIPTION = "営業AI — 商談分析・提案生成・フォローアップ戦略"

SYSTEM_PROMPT = """あなたはトップ営業コンサルタントです。
クライアントデータとナレッジベースの過去実績を分析し、具体的な営業戦略を提案してください。

ルール:
1. 顧客の課題を明確に特定した上で提案する
2. 具体的な数値目標（受注確率、想定売上、ROI）を含める
3. フォローアップのタイミングとアクションを明記する
4. 競合との差別化ポイントを必ず含める
5. 過去の成功パターンをナレッジベースから参照する

出力形式（JSON）:
{
  "recommendations": [
    {
      "type": "approach_strategy|pricing|follow_up|objection_handling|upsell|competitor_analysis",
      "action": "具体的なアクション",
      "reason": "根拠（顧客分析・KB知識）",
      "expected_impact": "想定効果（受注確率、売上）",
      "priority": "high|medium|low",
      "specific_values": {
        "estimated_deal_value": 0,
        "win_probability_percent": 0,
        "follow_up_days": 0,
        "discount_max_percent": 0
      }
    }
  ],
  "customer_analysis": {
    "pain_points": ["課題1", "課題2"],
    "decision_factors": ["要因1", "要因2"],
    "budget_estimate": "推定予算",
    "timeline": "導入時期"
  },
  "summary": "営業戦略の要約",
  "risk_assessment": "リスク評価"
}"""


def audit(proposal: dict[str, Any]) -> AuditResult:
    """Validate sales proposals with business safety checks.

    Rules:
    - `discount_max_percent` must be `<= 40`.
    - `win_probability_percent` must be between `0` and `100`.
    - `customer_analysis` should be included (warning if missing).
    - At least one `follow_up` recommendation is expected.
    - Missing `specific_values` is treated as warning.
    """
    errors: list[str] = []
    warnings: list[str] = []
    recommendations = proposal.get("recommendations", [])

    if not recommendations:
        return AuditResult(is_valid=False, errors=["提案が空です"])

    # Rule 1: Discount should not exceed 40%
    for r in recommendations:
        vals = r.get("specific_values", {})
        discount = vals.get("discount_max_percent")
        if discount is not None and discount > 40:
            errors.append(f"割引率 {discount}% は上限40%を超えています")

    # Rule 2: Win probability should be realistic (0-100)
    for r in recommendations:
        vals = r.get("specific_values", {})
        win_prob = vals.get("win_probability_percent")
        if win_prob is not None and (win_prob < 0 or win_prob > 100):
            errors.append(f"受注確率 {win_prob}% は範囲外です（0-100%）")

    # Rule 3: Must have customer_analysis
    if not proposal.get("customer_analysis"):
        warnings.append("顧客分析（customer_analysis）が含まれていません")

    # Rule 4: Follow-up timing should be specified
    has_follow_up = any(r.get("type") == "follow_up" for r in recommendations)
    if not has_follow_up:
        warnings.append("フォローアップ戦略が含まれていません")

    # Rule 5: Check for specific values
    missing_values = [r for r in recommendations if not r.get("specific_values")]
    if missing_values:
        warnings.append(f"{len(missing_values)}件の提案に具体的な数値がありません")

    return AuditResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)
