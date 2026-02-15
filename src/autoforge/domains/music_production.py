"""Music Production domain — prompts and audit rules."""

from __future__ import annotations

from typing import Any

from ..models import AuditResult

DESCRIPTION = "AI DAW プロデューサー（FL Studio Mobile 対応、マルチジャンル）"

SYSTEM_PROMPT = """あなたはプロの音楽プロデューサー兼サウンドデザイナーです。
FL Studio Mobile (FLM) のパラメータを熟知しており、ジャンル特有の制作手法に精通しています。

ナレッジベースの解析データを最優先で参照し、具体的なDAWパラメータ値で提案してください。

対応ジャンル: Psytrance, Techno, Acid, House, Drum & Bass, Ambient, Lo-Fi

出力形式（JSON）:
{
  "recommendations": [
    {
      "type": "synth_patch|drum_pattern|effect_chain|arrangement|mixing|sound_design",
      "action": "具体的なアクション",
      "reason": "根拠（ジャンル理論・KB知識）",
      "expected_impact": "想定効果（聴覚的変化）",
      "priority": "high|medium|low",
      "specific_values": {
        "bpm": 145,
        "key": "A minor",
        "synth": "3x Osc",
        "waveform": "saw",
        "filter_cutoff": 0.35,
        "filter_resonance": 0.6,
        "attack_ms": 5,
        "release_ms": 200,
        "reverb_size": 0.4,
        "delay_time_ms": 375,
        "sidechain_ratio": "4:1"
      }
    }
  ],
  "track_structure": {
    "bpm": 145,
    "key": "A minor",
    "time_signature": "4/4",
    "sections": [
      "intro_8bar", "buildup_16bar", "drop_16bar",
      "breakdown_8bar", "drop2_16bar", "outro_8bar"
    ],
    "total_bars": 72,
    "channels": ["kick", "bass", "lead", "pad", "hihat", "clap", "fx"]
  },
  "summary": "制作方針の要約",
  "genre_notes": "ジャンル固有の注意点"
}"""


def audit(proposal: dict[str, Any]) -> AuditResult:
    """ECK-lite audit for music production proposals."""
    errors: list[str] = []
    warnings: list[str] = []
    recommendations = proposal.get("recommendations", [])

    if not recommendations:
        return AuditResult(is_valid=False, errors=["提案が空です"])

    track = proposal.get("track_structure", {})
    bpm = track.get("bpm")

    # Rule 1: BPM sanity check
    if bpm is not None and (bpm < 30 or bpm > 300):
        errors.append(f"BPM {bpm} は範囲外です（30-300）")

    # Rule 2: Check specific_values on recommendations
    for r in recommendations:
        vals = r.get("specific_values", {})

        cutoff = vals.get("filter_cutoff")
        if cutoff is not None and not (0.0 <= cutoff <= 1.0):
            errors.append(f"filter_cutoff {cutoff} は 0.0-1.0 の範囲外です")

        reso = vals.get("filter_resonance")
        if reso is not None and not (0.0 <= reso <= 1.0):
            errors.append(f"filter_resonance {reso} は 0.0-1.0 の範囲外です")

        reverb = vals.get("reverb_size")
        if reverb is not None and not (0.0 <= reverb <= 1.0):
            warnings.append(f"reverb_size {reverb} は 0.0-1.0 の範囲外です")

    # Rule 3: Track structure should have sections
    sections = track.get("sections", [])
    if track and not sections:
        warnings.append("track_structure にセクション定義がありません")

    # Rule 4: Channel count sanity
    channels = track.get("channels", [])
    if len(channels) > 16:
        warnings.append(f"チャンネル数 {len(channels)} は FLM の制限を超える可能性があります")

    return AuditResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)
