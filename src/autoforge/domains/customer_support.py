"""Customer Support domain — prompts and audit rules for CS automation."""

from __future__ import annotations

from typing import Any

from ..models import AuditResult

DESCRIPTION = "カスタマーサポートAI — 応答テンプレ生成・エスカレーション判定"

SYSTEM_PROMPT = """あなたはカスタマーサポートの品質管理エキスパートです。
顧客の問い合わせ内容とナレッジベースの過去対応実績を分析し、最適な応答戦略を提案してください。

ルール:
1. 顧客の感情（怒り、不安、急ぎ）を検知して対応トーンを調整する
2. 解決すべき問題を明確に分類する（技術/請求/一般/クレーム）
3. 過去の類似ケースの解決パターンを参照する
4. エスカレーション判定を含める
5. 再発防止策を可能なら提案する

出力形式（JSON）:
{
  "recommendations": [
    {
      "type": "response_template|escalation|knowledge_article|follow_up|process_improvement",
      "action": "具体的なアクション",
      "reason": "根拠",
      "expected_impact": "想定効果（解決時間、CSAT）",
      "priority": "high|medium|low",
      "specific_values": {
        "estimated_resolution_minutes": 0,
        "escalation_level": 0,
        "csat_target": 0.0,
        "category": "technical|billing|general|complaint"
      }
    }
  ],
  "ticket_analysis": {
    "category": "technical|billing|general|complaint",
    "sentiment": "angry|anxious|neutral|positive",
    "urgency": "high|medium|low",
    "similar_past_tickets": 0
  },
  "summary": "対応方針の要約",
  "risk_assessment": "リスク評価"
}"""


def audit(proposal: dict[str, Any]) -> AuditResult:
    """Validate customer-support proposals with CS quality rules.

    Rules:
    - `escalation_level` must be in range `0..3`.
    - `csat_target` must be between `0.0` and `5.0`.
    - `estimated_resolution_minutes` must be non-negative.
    - `ticket_analysis` should be present (warning if missing).
    - High urgency/angry sentiment should include `escalation` recommendation.
    """
    errors: list[str] = []
    warnings: list[str] = []
    recommendations = proposal.get("recommendations", [])

    if not recommendations:
        return AuditResult(is_valid=False, errors=["提案が空です"])

    # Rule 1: Escalation level should be 0-3
    for r in recommendations:
        vals = r.get("specific_values", {})
        level = vals.get("escalation_level")
        if level is not None and (level < 0 or level > 3):
            errors.append(f"エスカレーションレベル {level} は範囲外です（0-3）")

    # Rule 2: CSAT target should be realistic (0.0-5.0)
    for r in recommendations:
        vals = r.get("specific_values", {})
        csat = vals.get("csat_target")
        if csat is not None and (csat < 0.0 or csat > 5.0):
            errors.append(f"CSAT目標 {csat} は範囲外です（0.0-5.0）")

    # Rule 3: Resolution time should be positive
    for r in recommendations:
        vals = r.get("specific_values", {})
        resolution = vals.get("estimated_resolution_minutes")
        if resolution is not None and resolution < 0:
            errors.append("解決時間は正の値である必要があります")

    # Rule 4: Should include ticket_analysis
    if not proposal.get("ticket_analysis"):
        warnings.append("チケット分析（ticket_analysis）が含まれていません")

    # Rule 5: High urgency should have escalation recommendation
    ticket = proposal.get("ticket_analysis", {})
    if ticket.get("urgency") == "high" or ticket.get("sentiment") == "angry":
        has_escalation = any(r.get("type") == "escalation" for r in recommendations)
        if not has_escalation:
            warnings.append("緊急度が高いがエスカレーション提案がありません")

    return AuditResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)
