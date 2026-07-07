#!/usr/bin/env python3
"""
post_llm script for adherence-report-zh skill.

Reads {"payload": {...}, "llm_result": {...}} from stdin.
Renders a patient-facing adherence HTML report (Chinese, Baidu Maps).
Writes JSON to stdout with structured_output.html.
"""

from __future__ import annotations

import json
import os
import re
import sys
from html import escape
from datetime import datetime
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "report.html"
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

_STATUS_MAP = {
    "stable": ("bg-emerald-100 text-emerald-800", "✅", "状态良好"),
    "at_risk": ("bg-amber-100 text-amber-800", "⚠️", "需要关注"),
}

_COND_COLORS = {
    "高血压": "bg-rose-500",
    "2型糖尿病": "bg-amber-500",
    "糖尿病": "bg-amber-500",
    "高脂血症": "bg-orange-500",
    "冠心病": "bg-red-500",
    "化疗期间": "bg-purple-500",
    "Hypertension": "bg-rose-500",
    "Type 2 diabetes": "bg-amber-500",
    "Diabetes": "bg-amber-500",
    "Hyperlipidemia": "bg-orange-500",
    "Coronary artery disease": "bg-red-500",
}

_RISK_TAG_COLORS = {
    "心率": "bg-rose-50 text-rose-700 border-rose-200",
    "血压": "bg-rose-50 text-rose-700 border-rose-200",
    "血糖": "bg-amber-50 text-amber-700 border-amber-200",
    "活动": "bg-sky-50 text-sky-700 border-sky-200",
    "食欲": "bg-orange-50 text-orange-700 border-orange-200",
    "偏低": "bg-amber-50 text-amber-700 border-amber-200",
    "偏高": "bg-rose-50 text-rose-700 border-rose-200",
    "下降": "bg-orange-50 text-orange-700 border-orange-200",
    "漏服": "bg-rose-50 text-rose-700 border-rose-200",
    "heart rate": "bg-rose-50 text-rose-700 border-rose-200",
    "blood pressure": "bg-rose-50 text-rose-700 border-rose-200",
    "glucose": "bg-amber-50 text-amber-700 border-amber-200",
    "activity": "bg-sky-50 text-sky-700 border-sky-200",
    "appetite": "bg-orange-50 text-orange-700 border-orange-200",
}

_VITAL_DEFS = [
    ("blood_pressure", "血压", "mmHg", "💓"),
    ("heart_rate", "心率", "bpm", "❤️"),
    ("blood_oxygen", "血氧", "%", "🫁"),
    ("blood_glucose", "血糖", "mmol/L", "🩸"),
    ("steps_today", "今日步数", "步", "🚶"),
]

_REC_ICONS = ["💊", "🚶", "🫀", "🩸", "🧈", "🥗", "🧘", "💤"]
_CATEGORY_ICONS = {"medication": "💊", "diet": "🥗", "exercise": "🏃", "monitoring": "📋", "lifestyle": "🏠"}

_ADHERENCE_DIMENSIONS = [
    ("medication", "💊", "用药"),
    ("appetite", "🍽️", "食欲与饮食"),
    ("exercise", "🏃", "运动与活动"),
    ("monitoring", "📋", "健康监测"),
]

_FIELD_LABELS = {
    "issues": "问题",
    "adjustments": "调整建议",
    "cause_if_known": "可能原因",
    "suggestions": "建议",
    "barriers": "障碍",
    "plan": "计划",
    "gaps": "缺口",
}

_GOOD_STATUS_KEYWORDS = (
    "good", "on track", "compliant", "met", "adequate", "consistent",
    "良好", "达标", "按时", "充足", "稳定", "正常", "较好",
)


# ─── Escalation Rules ───────────────────────────────────────────────
# Keep the same renderer-level escalation behavior as the English skill,
# with Chinese keywords and patient-facing copy.
_ESCALATION_RULES = [
    {
        "keywords": ["headache", "head pain", "migraine", "头痛", "偏头痛"],
        "threshold": 3,
        "level": "escalated",
        "title": "反复头痛，需要进一步关注",
        "message": (
            "近期记录中您提到头痛 {count} 次。因为这个症状反复出现，"
            "系统会将它标记为需要更密切观察，并提醒照护团队关注。"
        ),
        "recommendation": "每次出现时，请记录时间、严重程度（1-10 分）以及可能诱因。",
    },
    {
        "keywords": ["dizzy", "dizziness", "lightheaded", "vertigo", "头晕", "眩晕", "发晕"],
        "threshold": 3,
        "level": "escalated",
        "title": "反复头晕，需要进一步关注",
        "message": (
            "近期记录中头晕相关描述出现 {count} 次。"
            "这种模式可能与血压波动或药物副作用有关。"
        ),
        "recommendation": "头晕时先坐下或躺下，并记录是否发生在起身后或服药后。",
    },
    {
        "keywords": ["chest pain", "chest tightness", "chest discomfort", "胸痛", "胸闷", "胸部不适"],
        "threshold": 2,
        "level": "critical",
        "title": "反复胸部不适，需要尽快处理",
        "message": "胸部相关不适近期出现 {count} 次，这需要及时医学评估。",
        "recommendation": "如果现在正在胸痛或胸闷，请立即拨打 120 或联系急救服务。",
    },
    {
        "keywords": ["fall", "fell down", "lost balance", "跌倒", "摔倒", "失去平衡"],
        "threshold": 2,
        "level": "escalated",
        "title": "多次跌倒风险提醒",
        "message": "近期记录中出现 {count} 次跌倒或失衡相关事件，受伤风险会升高。",
        "recommendation": "请尽量扶稳后再行走，清理家中容易绊倒的物品。",
    },
]


def _check_escalations(key_events: list[dict]) -> list[dict]:
    """Scan key_events for recurring symptoms that trigger escalation rules."""
    if not key_events:
        return []

    triggered = []
    event_texts = [
        ev.get("description", "").lower() for ev in key_events
        if ev.get("type") in ("symptom", "alert", "complaint")
    ]

    for rule in _ESCALATION_RULES:
        count = sum(
            1 for text in event_texts
            if any(kw.lower() in text for kw in rule["keywords"])
        )
        if count >= rule["threshold"]:
            triggered.append({
                "level": rule["level"],
                "title": rule["title"],
                "message": rule["message"].format(count=count),
                "recommendation": rule["recommendation"],
                "count": count,
                "threshold": rule["threshold"],
            })
    return triggered


_AI_MSG_STYLES = {
    "good_news": {"icon": "🎉", "color": "bg-emerald-50 border-emerald-200", "title_color": "text-emerald-800"},
    "attention": {"icon": "⚠️", "color": "bg-amber-50 border-amber-200", "title_color": "text-amber-800"},
    "plan": {"icon": "📝", "color": "bg-blue-50 border-blue-200", "title_color": "text-blue-800"},
    "encouragement": {"icon": "💪", "color": "bg-purple-50 border-purple-200", "title_color": "text-purple-800"},
}


def _render_ai_message(so: dict) -> str:
    """Render AI message as always-visible sub-cards when structured sections are available."""
    sections = so.get("assistant_message_sections") or []

    if sections:
        html = ""
        for sec in sections:
            sec_type = sec.get("type", "")
            title = sec.get("title", "")
            content = sec.get("content", "")
            style = _AI_MSG_STYLES.get(
                sec_type,
                {"icon": "💬", "color": "bg-slate-50 border-slate-200", "title_color": "text-slate-800"},
            )

            html += (
                f'<div class="sub-card sub-card-static {style["color"]}">'
                f'<div class="sub-card-header" style="padding:12px 14px 8px">'
                f'<span class="sub-card-icon" style="font-size:1.2em">{style["icon"]}</span>'
                f'<div class="flex-1 min-w-0">'
                f'<div class="sub-card-value {style["title_color"]}" style="font-size:0.95em">{escape(title)}</div>'
                f'</div>'
                f'</div>'
                f'<div class="sub-card-body">'
                f'<div class="text-sm text-slate-700 leading-relaxed">{escape(content)}</div>'
                f'</div></div>'
            )
        return html

    plain = so.get("assistant_message_patient") or ""
    if not plain:
        return ""
    preview = escape(plain[:70]) + ("..." if len(plain) > 70 else "")
    return (
        f'<div class="sub-card sub-card-static bg-slate-50 border-slate-200">'
        f'<div class="sub-card-header" style="padding:12px 14px 8px">'
        f'<span class="sub-card-icon" style="font-size:1.2em">💬</span>'
        f'<div class="flex-1 min-w-0">'
        f'<div class="sub-card-value" style="font-size:0.9em;font-weight:600;color:#334155">{preview}</div>'
        f'</div>'
        f'</div>'
        f'<div class="sub-card-body">'
        f'<div class="text-sm text-slate-700 leading-relaxed">{escape(plain)}</div>'
        f'</div></div>'
    )


def _render_escalation_banner(escalations: list[dict]) -> str:
    """Render prominent warning banners for triggered escalation rules."""
    if not escalations:
        return ""

    html = ""
    for esc in escalations:
        if esc["level"] == "critical":
            banner_cls = "bg-gradient-to-r from-rose-50 to-red-50 border-rose-300"
            icon = "🚨"
            title_cls = "text-rose-800"
            badge_cls = "bg-rose-600 text-white"
            badge_text = "紧急"
        else:
            banner_cls = "bg-gradient-to-r from-amber-50 to-orange-50 border-amber-300"
            icon = "⚠️"
            title_cls = "text-amber-800"
            badge_cls = "bg-amber-500 text-white"
            badge_text = "需关注"

        html += (
            f'<div class="rounded-xl border-2 {banner_cls} p-5 mb-3">'
            f'<div class="flex items-center gap-2 mb-2">'
            f'<span class="text-xl">{icon}</span>'
            f'<span class="text-sm font-bold {title_cls} flex-1">{escape(esc["title"])}</span>'
            f'<span class="px-2 py-0.5 rounded-full text-[10px] font-bold {badge_cls}">{badge_text}</span>'
            f'</div>'
            f'<p class="text-sm text-slate-700 leading-relaxed mb-3">{escape(esc["message"])}</p>'
            f'<div class="flex items-start gap-2 bg-white/70 rounded-lg p-3 border border-slate-200">'
            f'<span class="text-sm mt-0.5">💡</span>'
            f'<div class="text-xs text-slate-600 leading-relaxed">'
            f'<span class="font-semibold">建议：</span>{escape(esc["recommendation"])}'
            f'</div></div>'
            f'</div>'
        )
    return html


def _load_env() -> None:
    if _ENV_PATH.is_file():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def _extract_numbers(value: object) -> list[float]:
    if value is None:
        return []
    return [float(part) for part in re.findall(r"\d+(?:\.\d+)?", str(value))]


def _render_vitals(summary: dict) -> str:
    if not summary:
        return ""

    metrics = [
        ("blood_pressure", "血压", "🩺", "90-120 / 60-80 mmHg"),
        ("heart_rate", "心率", "🫀", "60-100 bpm"),
        ("blood_oxygen", "血氧", "🫁", "95-100%"),
        ("blood_glucose", "血糖", "🧪", "3.9-7.8 mmol/L"),
        ("steps_today", "今日步数", "👟", "建议 6000-10000 步/日"),
    ]

    cards = []
    for key, label, icon, normal_range in metrics:
        raw_value = summary.get(key)
        if raw_value in (None, ""):
            continue

        status = "good"
        note = "您的数据整体平稳，继续保持当前的健康习惯。"
        numbers = _extract_numbers(raw_value)

        if key == "blood_pressure" and len(numbers) >= 2:
            systolic, diastolic = numbers[0], numbers[1]
            if systolic >= 140 or diastolic >= 90:
                status = "alert"
                note = "您的血压偏高，建议减少盐分摄入、规律监测，并按医嘱复诊。"
            elif systolic > 120 or diastolic > 80:
                status = "caution"
                note = "您的血压略高，近期注意休息、少盐饮食，并持续观察。"
            elif systolic < 90 or diastolic < 60:
                status = "caution"
                note = "您的血压偏低，如伴头晕乏力，请及时联系医生。"
            else:
                note = "您的血压在正常范围内，非常健康，继续保持。"
        elif key == "heart_rate" and numbers:
            value = numbers[0]
            if value < 50 or value > 110:
                status = "alert"
                note = "您的心率波动较明显，若伴胸闷、心悸或不适，请尽快联系医生。"
            elif value < 60 or value > 100:
                status = "caution"
                note = "您的心率略偏离常见范围，建议结合休息、情绪和近期活动继续观察。"
            else:
                note = "您的心率处于常见健康范围，当前状态不错。"
        elif key == "blood_oxygen" and numbers:
            value = numbers[0]
            if value < 93:
                status = "alert"
                note = "您的血氧偏低，如有气短、胸闷或乏力，请尽快联系医生。"
            elif value < 95:
                status = "caution"
                note = "您的血氧略低，建议减少剧烈活动并持续监测。"
            else:
                note = "您的血氧在正常范围内，呼吸状态较稳定。"
        elif key == "blood_glucose" and numbers:
            value = numbers[0]
            if value < 3.9 or value > 11:
                status = "alert"
                note = "您的血糖偏离较明显，建议尽快复测，并按医嘱调整饮食或用药。"
            elif value > 7.8:
                status = "caution"
                note = "您的血糖略高，近期可优先选择清淡、低糖、规律分餐。"
            else:
                note = "您的血糖在参考范围内，继续保持规律饮食与监测。"
        elif key == "steps_today" and numbers:
            value = numbers[0]
            if value < 3000:
                status = "caution"
                note = "今天活动量偏少，若身体允许，可分次增加轻度步行。"
            elif value < 6000:
                status = "caution"
                note = "今天活动量还有提升空间，循序渐进会更容易坚持。"
            else:
                note = "今天的活动量不错，继续维持规律运动节奏。"

        cards.append(
            f'<div class="hero-vital-card {status}">'
            f'<div class="hero-vital-top">'
            f'<div><div class="hero-vital-label">{label}</div><div class="hero-vital-value">{escape(str(raw_value))}</div></div>'
            f'<div class="hero-vital-icon">{icon}</div>'
            f'</div>'
            f'<div class="hero-vital-range">参考范围 {escape(normal_range)}</div>'
            f'<div class="hero-vital-note">{escape(note)}</div>'
            f'</div>'
        )

    if not cards:
        return ""

    return (
        '<section class="hero-vitals">'
        '<div class="flex items-center justify-between gap-3 mb-3">'
        '<div>'
        '<div class="text-sm font-bold text-slate-900">您最新的健康情况</div>'
        '<div class="text-xs text-slate-500 mt-1">先看看这里，就能快速知道今天身体的大致状态。</div>'
        '</div>'
        '<div class="text-xl">📊</div>'
        '</div>'
        f'<div class="hero-vitals-grid">{"".join(cards)}</div>'
        '</section>'
    )


def _render_condition_badges(conditions: list[str]) -> str:
    parts = []
    for c in conditions:
        color = _COND_COLORS.get(c, "bg-slate-500")
        parts.append(
            f'<span class="condition-chip inline-block {color} text-white px-3 py-1 '
            f'rounded-full text-xs font-semibold">{escape(c)}</span>'
        )
    return "\n".join(parts)


def _render_risk_tags(tags: list[str]) -> str:
    if not tags:
        return (
            '<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
            'border bg-emerald-50 text-emerald-700 border-emerald-200">暂无重大风险</span>'
        )
    parts = []
    for tag in tags:
        cls = "bg-slate-50 text-slate-600 border-slate-200"
        tag_lower = tag.lower()
        for kw, c in _RISK_TAG_COLORS.items():
            if kw.lower() in tag_lower or kw in tag:
                cls = c
                break
        parts.append(
            f'<span class="inline-block px-3 py-1 rounded-full text-xs '
            f'font-medium border {cls}">{escape(tag)}</span>'
        )
    return "\n".join(parts)


def _render_recommendations(recs: list) -> str:
    if not recs:
        return '<div class="text-sm text-slate-400">暂无具体建议</div>'
    parts = []
    for i, r in enumerate(recs):
        if isinstance(r, dict):
            text = r.get("text", "")
            reason = r.get("reason", "")
            category = r.get("category", "")
            icon = _CATEGORY_ICONS.get(category, _REC_ICONS[i % len(_REC_ICONS)])
        else:
            text = str(r)
            reason = ""
            icon = _REC_ICONS[i % len(_REC_ICONS)]
        safe_text = escape(text, quote=True)
        feedback_key = escape(f"-1-rec-{text}", quote=True)
        reason_html = ""
        if reason:
            reason_html = (
                f'<div class="text-xs text-emerald-700 mt-1.5 leading-relaxed italic '
                f'bg-emerald-50 rounded px-2 py-1 border-l-2 border-emerald-300">'
                f'💬 {escape(reason)}</div>'
            )
        parts.append(
            f'<div class="bg-emerald-50 rounded-lg p-3 border border-emerald-100 meal-card">'
            f'<div class="flex items-start gap-3">'
            f'<span class="text-base mt-0.5">{icon}</span>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="text-sm text-slate-700 leading-relaxed font-medium">{escape(text)}</div>'
            f'{reason_html}</div>'
            f'<div class="flex flex-col gap-1 flex-shrink-0">'
            f'<button class="feedback-btn feedback-action feedback-action-positive like" title="喜欢" '
            f'data-day-idx="-1" data-meal-type="rec" data-item-name="{safe_text}" '
            f'data-feedback-key="{feedback_key}" data-feedback-type="like" aria-pressed="false" '
            f'onclick="saveLikeFromButton(this)">'
            f"<span class=\"feedback-action-dot\">✓</span>适合我</button>"
            f'<button class="feedback-btn feedback-action feedback-action-negative" title="不适合" '
            f'data-day-idx="-1" data-meal-type="rec" data-item-name="{safe_text}" '
            f'data-feedback-key="{feedback_key}" data-feedback-type="dislike" aria-pressed="false" '
            f'onclick="showFeedbackModalFromButton(this)">'
            f"<span class=\"feedback-action-dot\">−</span>不适合</button>"
            f'</div></div></div>'
        )
    return "\n".join(parts)


def _render_reasoning(reasoning: str) -> str:
    if not reasoning:
        return ""
    return (
        '<div class="mt-4 pt-3 border-t border-slate-100">'
        '<div class="text-[11px] text-slate-400 uppercase tracking-wide font-medium mb-1.5">'
        "评估依据</div>"
        f'<div class="text-xs text-slate-600 bg-slate-50 rounded-lg p-3 leading-relaxed">{escape(reasoning)}</div>'
        '</div>'
    )


def _field_label(key: str) -> str:
    return _FIELD_LABELS.get(key, key.replace("_", " "))


def _render_adherence_dimension(icon: str, title: str, dim: dict) -> str:
    status = dim.get("status") or ""
    detail_keys = [k for k in dim if k != "status"]
    if not status and not detail_keys:
        return ""

    is_good = any(kw in status.lower() or kw in status for kw in _GOOD_STATUS_KEYWORDS)
    status_cls = (
        "bg-emerald-50 text-emerald-700 border-emerald-200"
        if is_good
        else "bg-amber-50 text-amber-700 border-amber-200"
    )

    html = (
        f'<div class="bg-slate-50 rounded-lg p-4 border border-slate-100">'
        f'<div class="flex items-center gap-2 mb-2">'
        f'<span class="text-base">{icon}</span>'
        f'<span class="text-sm font-semibold text-slate-800">{title}</span>'
        f'</div>'
    )
    if status:
        html += (
            f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
            f'border {status_cls} mb-2">{escape(status)}</span>'
        )
    for key in detail_keys:
        val = dim[key]
        if val:
            label = _field_label(key)
            html += (
                f'<div class="text-xs text-slate-600 mt-1">'
                f'<span class="font-medium text-slate-500">{label}：</span> {escape(str(val))}'
                f'</div>'
            )
    html += '</div>'
    return html


def _render_adherence(adh: dict) -> str:
    """Render adherence details (used inside card-details toggle)."""
    if not adh:
        return ""

    period = adh.get("period") or ""
    cards = []
    for key, icon, title in _ADHERENCE_DIMENSIONS:
        dim = adh.get(key)
        if isinstance(dim, dict):
            card = _render_adherence_dimension(icon, title, dim)
            if card:
                cards.append(card)

    if not cards and not period:
        return ""

    inner = ""
    if period:
        inner += (
            f'<div class="text-xs text-slate-500 font-medium uppercase tracking-wide mb-3">'
            f'统计周期：{escape(period)}</div>'
        )
    if cards:
        inner += f'<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">{"".join(cards)}</div>'
    return inner


def _render_memory_overview(memory: dict) -> str:
    """Render profile + recent trends as always-visible top overview cards."""
    if not memory:
        return ""

    profile = memory.get("patient_long_term_profile") or ""
    dynamics = memory.get("recent_health_dynamics") or ""

    blocks = []

    if profile:
        blocks.append(
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">👤</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">长期资料</div>'
            '<div class="sub-card-value">先了解您的基础情况</div>'
            '</div>'
            '</div>'
            f'<div class="sub-card-body"><div class="text-sm text-slate-700 leading-relaxed">{escape(profile)}</div></div>'
            '</div>'
        )

    if dynamics:
        blocks.append(
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">📈</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">近期趋势</div>'
            '<div class="sub-card-value">这段时间身体有什么变化</div>'
            '</div>'
            '</div>'
            f'<div class="sub-card-body"><div class="text-sm text-slate-700 leading-relaxed">{escape(dynamics)}</div></div>'
            '</div>'
        )

    return "".join(blocks)


def _render_key_events(memory: dict) -> str:
    """Render key events as a compact timeline list."""
    if not memory:
        return ""

    events = memory.get("key_events") or []
    if not events:
        return ""

    event_icons = {"surgery": "🩺", "symptom": "⚠️", "alert": "🚨", "medication": "💊", "visit": "🏥"}
    events_body = '<div class="space-y-2">'
    for ev in events:
        ev_icon = event_icons.get(ev.get("type", ""), "📌")
        ev_date = ev.get("date", "")
        ev_desc = ev.get("description", "")
        ev_type = ev.get("type", "")
        type_cls = {
            "surgery": "bg-purple-50 text-purple-700 border-purple-200",
            "alert": "bg-rose-50 text-rose-700 border-rose-200",
            "symptom": "bg-amber-50 text-amber-700 border-amber-200",
            "medication": "bg-blue-50 text-blue-700 border-blue-200",
        }.get(ev_type, "bg-slate-50 text-slate-600 border-slate-200")
        events_body += (
            f'<div class="flex items-start gap-3 rounded-lg p-2.5 border {type_cls}">'
            f'<span class="text-base mt-0.5">{ev_icon}</span>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="text-sm font-semibold">{escape(ev_desc)}</div>'
            f'<div class="text-xs text-slate-400 mt-0.5">{escape(ev_date)}</div>'
            f'</div></div>'
        )
    events_body += '</div>'
    return events_body


def _render_memory(memory: dict) -> str:
    """Backward-compatible combined memory rendering."""
    return _render_memory_overview(memory) + _render_key_events(memory)


def _stringify_compact(value: object) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value[:4]:
            text = _stringify_compact(item)
            if text:
                parts.append(text)
        return "；".join(parts)
    if isinstance(value, dict):
        parts = []
        for key, val in value.items():
            text = _stringify_compact(val)
            if text:
                parts.append(f"{_field_label(key)}：{text}")
        return "；".join(parts)
    return str(value)


def _extract_medications(profile: str) -> list[str]:
    if not profile:
        return []

    segment = ""
    patterns = [
        r"Medications?\s*:\s*([^\.]+)",
        r"Current medications?\s*:\s*([^\.]+)",
        r"用药[:：]\s*([^。]+)",
        r"正在服用[:：]\s*([^。]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, profile, flags=re.IGNORECASE)
        if match:
            segment = match.group(1).strip()
            break

    if not segment:
        return []

    seen = set()
    meds = []
    for raw in re.split(r"[;,，；]\s*", segment):
        item = raw.strip(" .。")
        if not item:
            continue
        norm = item.lower()
        if norm in seen:
            continue
        seen.add(norm)
        meds.append(item)
    return meds[:5]


def _render_personalized_context(so: dict, payload: dict, memory: dict) -> str:
    evidence_items = so.get("personalized_evidence") or []
    cards: list[str] = []

    if evidence_items:
        category_meta = {
            "history": ("🧾", "病史重点"),
            "surgery": ("🩺", "手术与恢复"),
            "medication": ("💊", "当前用药"),
            "lab": ("🧪", "最近检查"),
            "symptom": ("⚠️", "近期症状"),
            "monitoring": ("📈", "监测变化"),
        }
        for item in evidence_items[:4]:
            if not isinstance(item, dict):
                continue
            category = item.get("category") or ""
            icon, label = category_meta.get(category, ("🎯", "个性化依据"))
            title = item.get("title") or label
            evidence = item.get("evidence") or ""
            why_it_matters = item.get("why_it_matters") or item.get("implication") or ""
            body = ""
            if evidence:
                body += f'<div class="text-sm text-slate-700 leading-relaxed">{escape(evidence)}</div>'
            if why_it_matters:
                body += (
                    '<div class="mt-3 text-xs text-slate-600 bg-slate-50 rounded-xl px-3 py-2 leading-relaxed border border-slate-200">'
                    f'所以这里会更强调：{escape(why_it_matters)}</div>'
                )
            if body:
                cards.append(
                    '<div class="sub-card sub-card-static">'
                    '<div class="sub-card-header">'
                    f'<span class="sub-card-icon">{icon}</span>'
                    '<div class="flex-1 min-w-0">'
                    f'<div class="sub-card-label">{escape(label)}</div>'
                    f'<div class="sub-card-value">{escape(title)}</div>'
                    '</div>'
                    '</div>'
                    f'<div class="sub-card-body">{body}</div>'
                    '</div>'
                )
        return "".join(cards)

    conditions = so.get("conditions") or []
    key_events = memory.get("key_events") or []
    profile = memory.get("patient_long_term_profile") or ""
    recent_dynamics = memory.get("recent_health_dynamics") or ""
    meds = _extract_medications(profile)
    latest_summary = so.get("latest_health_summary") or {}
    signals = payload.get("signals") or {}
    adherence = so.get("adherence_analysis") or {}

    surgery_event = next(
        (
            ev for ev in key_events
            if ev.get("type") == "surgery"
            or "手术" in str(ev.get("description", ""))
            or "surgery" in str(ev.get("description", "")).lower()
        ),
        None,
    )

    history_chips = []
    if conditions:
        history_chips.extend(conditions[:3])
    if surgery_event:
        history_chips.append(f'{surgery_event.get("date", "")} {surgery_event.get("description", "")}'.strip())
    elif "术后" in profile or "post-surgery" in profile.lower():
        history_chips.append("当前处于术后恢复阶段")

    if history_chips:
        implication_parts = []
        if surgery_event or "术后" in profile or "post-surgery" in profile.lower():
            implication_parts.append("恢复期会更强调蛋白质、容易入口的食物和循序渐进活动")
        if any(c in {"高血压", "Hypertension"} for c in conditions):
            implication_parts.append("饮食会特别强调少盐")
        if any(c in {"2型糖尿病", "糖尿病", "Type 2 diabetes", "Diabetes"} for c in conditions):
            implication_parts.append("也会提醒规律分餐和少精制糖")

        cards.append(
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">🧾</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">病史重点</div>'
            '<div class="sub-card-value">这次建议会先围绕您的基础病和恢复阶段</div>'
            '</div>'
            '</div>'
            '<div class="sub-card-body">'
            f'<div class="flex flex-wrap gap-2 mb-3">{"".join(f"<span class=\"context-chip\">{escape(chip)}</span>" for chip in history_chips[:4])}</div>'
            + (
                '<div class="text-xs text-slate-600 bg-slate-50 rounded-xl px-3 py-2 leading-relaxed border border-slate-200">'
                f'所以这里会更强调：{escape("；".join(implication_parts))}</div>'
                if implication_parts else ""
            )
            + '</div></div>'
        )

    med_issue = _stringify_compact((adherence.get("medication") or {}).get("issues"))
    med_adjustment = _stringify_compact((adherence.get("medication") or {}).get("adjustments"))
    if not med_issue:
        med_issue = next(
            (str(ev.get("description", "")).strip() for ev in key_events if "服用" in str(ev.get("description", "")) or "药" in str(ev.get("description", ""))),
            ""
        )

    if meds or med_issue:
        med_body = ""
        if meds:
            med_body += f'<div class="flex flex-wrap gap-2 mb-3">{"".join(f"<span class=\"context-chip\">{escape(med)}</span>" for med in meds)}</div>'
        if med_issue:
            med_body += f'<div class="text-sm text-slate-700 leading-relaxed">目前记录里提到：{escape(med_issue)}</div>'
        if med_adjustment:
            med_body += (
                '<div class="mt-3 text-xs text-slate-600 bg-slate-50 rounded-xl px-3 py-2 leading-relaxed border border-slate-200">'
                f'所以这里会更强调：{escape(med_adjustment)}</div>'
            )
        elif "恶心" in med_issue or "nausea" in med_issue.lower():
            med_body += (
                '<div class="mt-3 text-xs text-slate-600 bg-slate-50 rounded-xl px-3 py-2 leading-relaxed border border-slate-200">'
                '所以这里会更强调：少量多餐、温热软一点的食物，以及把不适和医生继续对上。</div>'
            )

        cards.append(
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">💊</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">当前用药</div>'
            '<div class="sub-card-value">用药情况和身体反应会直接影响饮食建议</div>'
            '</div>'
            '</div>'
            f'<div class="sub-card-body">{med_body}</div>'
            '</div>'
        )

    metric_bits = []
    metric_labels = {
        "blood_pressure": "血压",
        "heart_rate": "心率",
        "blood_oxygen": "血氧",
        "blood_glucose": "血糖",
        "steps_today": "步数",
    }
    for key in ("blood_pressure", "blood_glucose", "steps_today", "heart_rate", "blood_oxygen"):
        value = latest_summary.get(key)
        if value not in (None, ""):
            metric_bits.append(f'{metric_labels.get(key, key)} {value}')

    monitoring_gap = _stringify_compact((adherence.get("monitoring") or {}).get("gaps"))
    signal_bits = [str(item).strip() for item in (signals.get("anomalies") or []) if str(item).strip()]
    recent_focus = []
    if metric_bits:
        recent_focus.append("最近记录：" + "，".join(metric_bits[:3]))
    if signal_bits:
        recent_focus.append("设备提示：" + "、".join(signal_bits[:2]))
    if monitoring_gap:
        recent_focus.append("监测提醒：" + monitoring_gap)
    elif recent_dynamics:
        recent_focus.append(_stringify_compact(recent_dynamics)[:120] + ("..." if len(_stringify_compact(recent_dynamics)) > 120 else ""))

    if recent_focus:
        implication = []
        if any("血糖" in bit for bit in metric_bits):
            implication.append("饮食会更强调规律分餐")
        if any("步数" in bit for bit in metric_bits) or any("Activity" in bit or "活动" in bit for bit in signal_bits):
            implication.append("活动建议会更温和、循序渐进")
        if monitoring_gap:
            implication.append("也会提醒把监测补齐")

        cards.append(
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">📈</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">最近指标</div>'
            '<div class="sub-card-value">不是泛泛建议，而是结合您最近几天的真实记录</div>'
            '</div>'
            '</div>'
            '<div class="sub-card-body">'
            + "".join(f'<div class="text-sm text-slate-700 leading-relaxed mb-2">{escape(line)}</div>' for line in recent_focus[:3])
            + (
                '<div class="text-xs text-slate-600 bg-slate-50 rounded-xl px-3 py-2 leading-relaxed border border-slate-200">'
                f'所以这里会更强调：{escape("；".join(implication))}</div>'
                if implication else ""
            )
            + '</div></div>'
        )

    extra_notes = []
    for key, label in (
        ("clinical_notes", "临床备注"),
        ("doctor_notes", "医生备注"),
        ("case_history", "病例重点"),
        ("latest_labs", "最近检查"),
    ):
        text = _stringify_compact(memory.get(key) or payload.get(key))
        if text:
            extra_notes.append((label, text))
    for label, text in extra_notes[:1]:
        cards.append(
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">🧠</span>'
            '<div class="flex-1 min-w-0">'
            f'<div class="sub-card-label">{escape(label)}</div>'
            '<div class="sub-card-value">如果后面接入更深的病例，这里会直接引用</div>'
            '</div>'
            '</div>'
            f'<div class="sub-card-body"><div class="text-sm text-slate-700 leading-relaxed">{escape(text)}</div></div>'
            '</div>'
        )

    return "".join(cards)


_CONDITION_CONTEXTS = {
    "feeling_unwell": {
        "show_sections": {"header", "escalation", "ai_message", "guidance", "vitals", "meal_plan", "guardrail"},
        "tone_override": "gentle_patient",
        "header_greeting": "我们在这里陪着您",
        "guidance_emphasis": "rest",
    },
    "post_chemotherapy": {
        "show_sections": {"header", "escalation", "ai_message", "guidance", "vitals", "recommendations", "nutrition", "meal_plan", "cuisine", "diet_tips", "submit", "guardrail"},
        "tone_override": "gentle_patient",
        "header_greeting": "您已经做得很好",
        "guidance_emphasis": "nutrition",
    },
    "post_surgery_recovering": {
        "show_sections": {"header", "escalation", "ai_message", "memory", "guidance", "vitals", "adherence", "recommendations", "nutrition", "diet_table", "cuisine", "meal_plan", "diet_tips", "map", "submit", "guardrail"},
        "tone_override": None,
        "header_greeting": "您好！",
        "guidance_emphasis": None,
    },
    "chronic_pain_flare": {
        "show_sections": {"header", "escalation", "ai_message", "guidance", "vitals", "recommendations", "meal_plan", "guardrail"},
        "tone_override": "gentle_patient",
        "header_greeting": "今天辛苦了",
        "guidance_emphasis": "rest",
    },
    "low_mood_isolated": {
        "show_sections": {"header", "ai_message", "guidance", "vitals", "recommendations", "nutrition", "meal_plan", "cuisine", "map", "diet_tips", "submit", "guardrail"},
        "tone_override": "warm_encouraging",
        "header_greeting": "您不是一个人",
        "guidance_emphasis": "exercise",
    },
    "cognitive_decline": {
        "show_sections": {"header", "ai_message", "guidance", "vitals", "meal_plan", "guardrail"},
        "tone_override": "gentle_patient",
        "header_greeting": "今天请记住这些",
        "guidance_emphasis": "monitoring",
    },
    "caregiver_absent": {
        "show_sections": {"header", "escalation", "ai_message", "guidance", "vitals", "recommendations", "meal_plan", "map", "guardrail"},
        "tone_override": "warm_encouraging",
        "header_greeting": "您的日常关心",
        "guidance_emphasis": None,
    },
    "medication_adjustment": {
        "show_sections": {"header", "ai_message", "guidance", "vitals", "recommendations", "nutrition", "meal_plan", "diet_tips", "submit", "guardrail"},
        "tone_override": "authority_based",
        "header_greeting": "照护团队的重要提醒",
        "guidance_emphasis": "monitoring",
    },
    "high_fall_risk": {
        "show_sections": {"header", "escalation", "ai_message", "guidance", "vitals", "recommendations", "meal_plan", "map", "guardrail"},
        "tone_override": "warm_encouraging",
        "header_greeting": "今天先把安全放第一",
        "guidance_emphasis": "exercise",
    },
    "stable_routine": {
        "show_sections": {"header", "escalation", "ai_message", "memory", "guidance", "vitals", "adherence", "risk_tags", "recommendations", "reasoning", "nutrition", "diet_table", "cuisine", "meal_plan", "diet_tips", "map", "submit", "guardrail"},
        "tone_override": None,
        "header_greeting": "您好！",
        "guidance_emphasis": None,
    },
}

_FULL_SECTIONS = _CONDITION_CONTEXTS["stable_routine"]["show_sections"]


_TONE_STYLES = {
    "warm_encouraging": {
        "icon": "💚",
        "title": "为什么这对您重要",
        "border_color": "border-emerald-200",
        "header_color": "text-emerald-800",
        "summary_bg": "bg-emerald-50 border-l-4 border-emerald-400",
        "tip_why_color": "text-emerald-700",
    },
    "direct_practical": {
        "icon": "📋",
        "title": "健康要点",
        "border_color": "border-blue-200",
        "header_color": "text-blue-800",
        "summary_bg": "bg-blue-50 border-l-4 border-blue-400",
        "tip_why_color": "text-blue-700",
    },
    "authority_based": {
        "icon": "👨\u200d⚕️",
        "title": "照护团队建议",
        "border_color": "border-indigo-200",
        "header_color": "text-indigo-800",
        "summary_bg": "bg-indigo-50 border-l-4 border-indigo-400",
        "tip_why_color": "text-indigo-700",
    },
    "gentle_patient": {
        "icon": "🌸",
        "title": "给您的温和提醒",
        "border_color": "border-rose-200",
        "header_color": "text-rose-800",
        "summary_bg": "bg-rose-50 border-l-4 border-rose-300",
        "tip_why_color": "text-rose-700",
    },
}


def _render_health_guidance(guidance: dict, conditions: list[str], tone_profile: dict = None) -> str:
    """Render health guidance as always-visible sub-cards with distinct topics."""
    if not guidance and not conditions:
        return ""

    summary = ""
    tips = []
    if isinstance(guidance, dict):
        summary = guidance.get("summary") or ""
        tips = guidance.get("tips") or []
    elif isinstance(guidance, str):
        summary = guidance

    if not summary and not tips and not conditions:
        return ""

    tone_type = (tone_profile or {}).get("style") or "warm_encouraging"
    style = _TONE_STYLES.get(tone_type, _TONE_STYLES["warm_encouraging"])
    patient_name = (tone_profile or {}).get("preferred_name") or ""

    html = ""
    if patient_name:
        html += (
            f'<div class="text-xs text-slate-500 mb-2">'
            f'为 <span class="font-semibold">{escape(patient_name)}</span> 个性化整理</div>'
        )
    if summary:
        html += (
            f'<div class="leading-relaxed mb-3 {style["summary_bg"]} '
            f'rounded-lg p-4" style="font-size:0.95em">'
            f'{escape(summary)}</div>'
        )

    guidance_icons = {"protein": "🥩", "low_salt": "🧂", "low_oil": "🫒",
                      "hydration": "💧", "fiber": "🌾", "exercise": "🚶",
                      "rest": "😴", "monitoring": "📋"}

    for tip in tips:
        if isinstance(tip, dict):
            icon = guidance_icons.get(tip.get("category", ""), "💡")
            text = tip.get("text", "")
            why = tip.get("why", "")
        else:
            icon = "💡"
            text = str(tip)
            why = ""

        body_html = ""
        if why:
            body_html = (
                f'<div class="text-sm {style["tip_why_color"]} leading-relaxed italic">'
                f'→ {escape(why)}</div>'
            )

        html += (
            f'<div class="sub-card sub-card-static">'
            f'<div class="sub-card-header">'
            f'<span class="sub-card-icon">{icon}</span>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="sub-card-value" style="font-size:0.95em">{escape(text)}</div>'
            f'</div>'
            f'</div>'
        )
        if body_html:
            html += f'<div class="sub-card-body">{body_html}</div>'
        html += '</div>'

    return html


def _render_diet_table(diet_table: list[dict]) -> str:
    if not diet_table:
        return ""
    rows = ""
    for item in diet_table:
        rows += (
            f'<tr>'
            f'<td class="px-4 py-3 font-medium text-slate-800">{escape(item.get("condition", ""))}</td>'
            f'<td class="px-4 py-3 text-slate-600">{escape(item.get("principle", ""))}</td>'
            f'<td class="px-4 py-3 text-emerald-700">{escape(item.get("recommend", ""))}</td>'
            f'<td class="px-4 py-3 text-rose-600">{escape(item.get("avoid", ""))}</td>'
            f'</tr>'
        )
    return (
        '<div class="overflow-x-auto rounded-xl border border-slate-200 bg-white">'
        '<table class="w-full text-sm">'
        '<thead><tr class="bg-slate-50">'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">疾病</th>'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">原则</th>'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">推荐</th>'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">避免</th>'
        '</tr></thead>'
        f'<tbody class="divide-y divide-slate-100">{rows}</tbody>'
        '</table></div>'
    )


def _render_diet_tips(tips: list[dict]) -> str:
    """Render each diet tip as an always-visible sub-card."""
    if not tips:
        return ""

    html = ""
    for tip in tips:
        title = tip.get("title", "")
        detail = tip.get("detail", "")
        icon = tip.get("icon", "💡")
        safe_title = escape(title).replace("'", "&#39;")

        body_html = ""
        if detail:
            body_html = (
                f'<div class="text-sm text-slate-600 leading-relaxed mb-2">{escape(detail)}</div>'
                f'<div class="feedback-actions" style="flex-direction:row;flex-wrap:wrap">'
                f'<button class="feedback-btn like" title="有帮助" '
                f"onclick=\"saveLike(-1,'tip','{safe_title}')\">适合我</button>"
                f'<button class="feedback-btn feedback-skip" title="不适合我" '
                f"onclick=\"showFeedbackModal(-1,'tip','{safe_title}')\">不适合</button>"
                f'</div>'
            )

        html += (
            f'<div class="sub-card sub-card-static">'
            f'<div class="sub-card-header">'
            f'<span class="sub-card-icon">{icon}</span>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="sub-card-value" style="font-size:0.92em">{escape(title)}</div>'
            f'</div>'
            f'</div>'
        )
        if body_html:
            html += f'<div class="sub-card-body">{body_html}</div>'
        html += '</div>'

    return html


def _render_map_section(
    ai_msg_hospital: str,
    ai_msg_park: str,
    patient_lat: float,
    patient_lon: float,
) -> str:
    lat = patient_lat if patient_lat else 39.9042
    lon = patient_lon if patient_lon else 116.4074

    hosp_js = json.dumps(ai_msg_hospital, ensure_ascii=False)
    park_js = json.dumps(ai_msg_park, ensure_ascii=False)

    css = (
        "<style>"
        "#bmap{width:100%;height:100%}"
        "#locate-btn{position:absolute;bottom:12px;right:12px;z-index:999;width:38px;height:38px;"
        "border-radius:50%;border:none;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,0.2);"
        "cursor:pointer;font-size:1.1em;display:flex;align-items:center;justify-content:center}"
        "#locate-btn:active{transform:scale(0.92)}"
        ".map-toggle{display:flex;margin-top:10px;background:#f1f5f9;border-radius:10px;padding:3px}"
        ".map-toggle button{flex:1;padding:8px 0;border:none;background:transparent;border-radius:8px;"
        "font-size:0.85em;font-weight:600;color:#94a3b8;cursor:pointer;transition:all 0.25s}"
        ".map-toggle button.active{background:linear-gradient(135deg,#42a5f5,#1e88e5);color:#fff;"
        "box-shadow:0 2px 8px rgba(30,136,229,0.3)}"
        ".map-toggle button.active.park-mode{background:linear-gradient(135deg,#66bb6a,#43a047);"
        "box-shadow:0 2px 8px rgba(67,160,71,0.3)}"
        ".map-place{display:flex;align-items:center;gap:10px;background:#f8fafc;border-radius:10px;"
        "padding:12px;margin-top:8px;cursor:pointer;border:2px solid transparent;transition:all 0.15s}"
        ".map-place:active{transform:scale(0.98)}"
        ".map-place.focused{border-color:#1e88e5;box-shadow:0 2px 10px rgba(30,136,229,0.15)}"
        ".map-place.focused.park-mode{border-color:#43a047;box-shadow:0 2px 10px rgba(67,160,71,0.15)}"
        ".map-place-icon{width:34px;height:34px;border-radius:8px;display:flex;align-items:center;"
        "justify-content:center;font-size:1em;flex-shrink:0}"
        ".map-place-icon.hospital{background:#e3f2fd}"
        ".map-place-icon.park{background:#e8f5e9}"
        ".map-place-nav{flex-shrink:0;width:30px;height:30px;border-radius:50%;border:none;"
        "background:#1e88e5;color:#fff;font-size:0.9em;cursor:pointer;display:flex;align-items:center;"
        "justify-content:center;box-shadow:0 2px 6px rgba(30,136,229,0.35)}"
        ".map-place-nav.park-mode{background:#43a047;box-shadow:0 2px 6px rgba(67,160,71,0.35)}"
        ".map-place-nav:active{transform:scale(0.9)}"
        ".map-dist{font-size:0.75em;font-weight:700;padding:3px 8px;border-radius:16px;"
        "white-space:nowrap;flex-shrink:0}"
        ".map-dist.hospital{background:#e3f2fd;color:#1565c0}"
        ".map-dist.park{background:#e8f5e9;color:#2e7d32}"
        "</style>"
    )

    html = (
        '<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5 mb-3">'
        '<div class="flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">'
        '<span class="text-lg">📍</span>'
        '<h2 class="text-sm font-bold text-slate-800">附近推荐</h2>'
        "</div>"
        '<p class="text-sm text-slate-600 mb-3" id="ai-map-text">' + ai_msg_hospital + "</p>"
        '<div class="rounded-2xl overflow-hidden border border-slate-200 relative" style="height:240px">'
        '<div id="bmap"></div>'
        '<button id="locate-btn" title="回到我的位置">📍</button>'
        "</div>"
        '<div class="map-toggle">'
        '<button class="active" id="btn-hospital" onclick="switchMapMode(\'hospital\')">🏥 附近医院</button>'
        '<button id="btn-park" onclick="switchMapMode(\'park\')">🌳 附近公园</button>'
        "</div>"
        '<div id="map-cards"></div>'
        "</div>"
    )

    js_template = r"""<script>
(function() {
  var bmap = new BMap.Map("bmap");
  bmap.enableScrollWheelZoom(true);
  var userPoint = new BMap.Point(__FALLBACK_LON__, __FALLBACK_LAT__);
  var mapMode = 'hospital';
  var mapMarkers = [];
  var mapCards = [];
  var mapRoute = null;
  var userOverlays = [];
  var AI_MAP_TEXT = { hospital: __HOSP_MSG__, park: __PARK_MSG__ };

  document.getElementById('locate-btn').addEventListener('click', function() {
    if (userPoint) { bmap.panTo(userPoint); bmap.setZoom(15); }
  });

  var USER_ICON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28">'
    + '<circle cx="14" cy="14" r="13" fill="#4285f4" fill-opacity="0.2" stroke="#4285f4" stroke-width="1"/>'
    + '<circle cx="14" cy="14" r="7" fill="#4285f4" stroke="#fff" stroke-width="2.5"/>'
    + '</svg>';
  var USER_ICON = new BMap.Icon(
    'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(USER_ICON_SVG),
    new BMap.Size(28, 28),
    { anchor: new BMap.Size(14, 14) }
  );

  function addUserOverlays() {
    userOverlays.forEach(function(o) { bmap.removeOverlay(o); });
    userOverlays = [];
    var marker = new BMap.Marker(userPoint, { icon: USER_ICON });
    bmap.addOverlay(marker);
    userOverlays.push(marker);
    var label = new BMap.Label('\u60a8\u5728\u8fd9\u91cc', {
      position: userPoint,
      offset: new BMap.Size(16, -8)
    });
    label.setStyle({
      background:'#4285f4',color:'#fff',border:'none',
      borderRadius:'6px',padding:'2px 8px',
      fontSize:'12px',fontWeight:'600',
      boxShadow:'0 1px 4px rgba(0,0,0,0.25)',whiteSpace:'nowrap'
    });
    bmap.addOverlay(label);
    userOverlays.push(label);
  }

  function clearRoute() {
    if (mapRoute) { mapRoute.clearResults(); mapRoute = null; }
  }
  function clearResultMarkers() {
    clearRoute();
    mapMarkers.forEach(function(m) { bmap.removeOverlay(m); });
    mapMarkers = [];
    mapCards = [];
  }

  bmap.centerAndZoom(userPoint, 15);
  addUserOverlays();
  doMapSearch('hospital');

  window.switchMapMode = function(mode) {
    if (mode === mapMode) return;
    mapMode = mode;
    document.getElementById('btn-hospital').className = mode === 'hospital' ? 'active' : '';
    document.getElementById('btn-park').className = mode === 'park' ? 'active park-mode' : '';
    document.getElementById('ai-map-text').textContent = AI_MAP_TEXT[mode];
    clearResultMarkers();
    document.getElementById('map-cards').innerHTML = '<div style="text-align:center;color:#bbb;padding:16px;font-size:0.85em">\u641c\u7d22\u4e2d\u2026</div>';
    doMapSearch(mode);
  };

  function doMapSearch(mode) {
    if (!userPoint) return;
    var keyword = mode === 'hospital' ? '\u533b\u9662' : '\u516c\u56ed';
    var local = new BMap.LocalSearch(bmap, {
      renderOptions: { autoViewport: false },
      onSearchComplete: function(results) {
        clearResultMarkers();
        var container = document.getElementById('map-cards');
        container.innerHTML = '';
        if (!results || local.getStatus() !== BMAP_STATUS_SUCCESS || results.getCurrentNumPois() === 0) {
          container.innerHTML = '<div style="text-align:center;color:#bbb;padding:16px;font-size:0.85em">\u9644\u8fd1\u6682\u65e0\u76f8\u5173\u5730\u70b9</div>';
          return;
        }
        var count = results.getCurrentNumPois();
        for (var i = 0; i < count; i++) {
          (function(idx) {
            var poi = results.getPoi(idx);
            var dist = bmap.getDistance(userPoint, poi.point);
            var distText = dist >= 1000 ? (dist/1000).toFixed(1)+' km' : Math.round(dist)+' m';
            var marker = new BMap.Marker(poi.point);
            bmap.addOverlay(marker);
            mapMarkers.push(marker);
            marker.addEventListener('click', function() { focusMapCard(idx, poi); });
            var card = document.createElement('div');
            card.className = 'map-place';
            card.innerHTML = '<div class="map-place-icon '+mode+'">'+(mode==='hospital'?'\ud83c\udfe5':'\ud83c\udf33')+'</div>'
              +'<div style="flex:1;min-width:0"><div style="font-size:0.9em;font-weight:600;color:#222;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+poi.title+'</div>'
              +'<div style="font-size:0.75em;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+(poi.address||'\u6682\u65e0\u5730\u5740')+'</div></div>'
              +'<div class="map-dist '+mode+'">'+distText+'</div>'
              +'<button class="map-place-nav'+(mode==='park'?' park-mode':'')+'" title="\u5bfc\u822a">\u27a4</button>';
            card.addEventListener('click', function(e) {
              if (e.target.classList.contains('map-place-nav')) return;
              focusMapCard(idx, poi);
            });
            card.querySelector('.map-place-nav').addEventListener('click', function(e) {
              e.stopPropagation();
              navigateMapTo(poi);
            });
            container.appendChild(card);
            mapCards.push(card);
          })(i);
        }
      }
    });
    local.searchNearby(keyword, userPoint, 4000);
  }

  function focusMapCard(idx, poi) {
    mapCards.forEach(function(c) { c.classList.remove('focused','park-mode'); });
    mapCards[idx].classList.add('focused');
    if (mapMode === 'park') mapCards[idx].classList.add('park-mode');
    mapCards[idx].scrollIntoView({ behavior:'smooth', block:'nearest' });
    bmap.panTo(poi.point);
    mapMarkers[idx].openInfoWindow(
      new BMap.InfoWindow('<b>'+poi.title+'</b><br><span style="color:#888;font-size:12px">'+(poi.address||'')+'</span>')
    );
    clearRoute();
    var routeColor = mapMode === 'hospital' ? '#1e88e5' : '#43a047';
    var walking = new BMap.WalkingRoute(bmap, {
      renderOptions: { map: bmap, autoViewport: false },
      onSearchComplete: function(results) {
        if (walking.getStatus() !== BMAP_STATUS_SUCCESS) return;
        var plan = results.getPlan(0);
        for (var s = 0; s < plan.getNumRoutes(); s++) {
          var route = plan.getRoute(s);
          var path = route.getPolyline();
          if (path) { path.setStrokeColor(routeColor); path.setStrokeWeight(5); path.setStrokeOpacity(0.85); }
        }
        addUserOverlays();
      }
    });
    walking.search(userPoint, poi.point);
    mapRoute = walking;
  }

  function navigateMapTo(poi) {
    var destLat = poi.point.lat;
    var destLng = poi.point.lng;
    var destName = encodeURIComponent(poi.title);
    var isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
    var appUrl = 'baidumap://map/direction?destination=latlng:'+destLat+','+destLng+'|name:'+destName+'&mode=walking&coord_type=bd09ll&src=webapp';
    var webUrl = 'https://api.map.baidu.com/marker?location='+destLat+','+destLng+'&title='+destName+'&output=html&coord_type=bd09ll&src=webapp';
    if (isMobile) {
      window.location.href = appUrl;
      setTimeout(function() { window.location.href = webUrl; }, 2000);
    } else {
      window.open(webUrl, '_blank');
    }
  }
})();
</script>"""

    js = js_template.replace("__HOSP_MSG__", hosp_js).replace("__PARK_MSG__", park_js)
    js = js.replace("__FALLBACK_LON__", str(lon)).replace("__FALLBACK_LAT__", str(lat))
    return css + "\n" + html + "\n" + js


def _format_time(raw: str) -> str:
    if "T" in str(raw):
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return dt.strftime("%Y年%m月%d日 %H:%M")
        except (ValueError, TypeError):
            pass
    elif isinstance(raw, str) and len(raw) >= 10 and raw[4] == "-":
        try:
            dt = datetime.strptime(raw[:16], "%Y-%m-%d %H:%M")
            return dt.strftime("%Y年%m月%d日 %H:%M")
        except ValueError:
            pass
    return str(raw)


def main() -> None:
    _load_env()

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to parse input: {exc}", file=sys.stderr)
        sys.exit(1)

    payload = data.get("payload") or {}
    llm = data.get("llm_result") or {}
    so = llm.get("structured_output") or {}
    memory = payload.get("memory") or {}
    try:
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Template not found: {_TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)

    tone_profile = memory.get("tone_profile") or {}
    condition_ctx_name = tone_profile.get("condition_context") or "stable_routine"
    ctx = _CONDITION_CONTEXTS.get(condition_ctx_name, _CONDITION_CONTEXTS["stable_routine"])
    visible = ctx["show_sections"]

    if ctx["tone_override"]:
        tone_profile = {**tone_profile, "style": ctx["tone_override"]}

    key_events = memory.get("key_events") or []
    escalations = _check_escalations(key_events)

    status = so.get("patient_status") or "stable"
    if any(e["level"] == "critical" for e in escalations):
        status = "at_risk"
    elif escalations and status == "stable":
        status = "at_risk"
    if status not in _STATUS_MAP:
        status = "stable"
    badge_class, status_icon, status_text = _STATUS_MAP[status]

    meta = payload.get("meta") or {}
    current_time = _format_time(
        meta.get("current_time") or datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    conditions = so.get("conditions") or []
    location = payload.get("location") or {}
    loc = location.get("current") or {}
    patient_lat = loc.get("lat", 0)
    patient_lon = loc.get("lon", 0)

    if any(
        kw.lower() in t.lower() or kw in t
        for t in so.get("risk_tags", [])
        for kw in ("活动", "偏低", "activity", "low", "sedentary")
    ):
        ai_map_msg = "您近期活动量偏低，天气不错时可以去附近公园散散步。"
        ai_map_msg_park = ai_map_msg
    else:
        ai_map_msg = "已为您查询附近医疗网点，如有不适请及时就医。"
        ai_map_msg_park = "天气好时去附近公园走走，有助于身心放松。"

    baidu_map_ak = os.environ.get("BAIDU_MAP_AK", "").strip() or "6zXfgKZZiCdrL3MZBH7DGpjemq5IRxRC"
    maps_script = ""
    if "map" in visible:
        maps_script = (
            '<script type="text/javascript" '
            f'src="https://api.map.baidu.com/api?v=3.0&ak={escape(baidu_map_ak, quote=True)}"></script>'
        )
    map_section = _render_map_section(ai_map_msg, ai_map_msg_park, patient_lat, patient_lon)

    meal_json = json.dumps(so.get("weekly_meal_plan") or [], ensure_ascii=False)

    patient_id = meta.get("user_id") or payload.get("user_id") or payload.get("patient_id") or "unknown"

    preferred_name = (tone_profile or {}).get("preferred_name") or ""
    base_greeting = ctx.get("header_greeting") or "您好！"
    if preferred_name:
        base_trimmed = base_greeting.rstrip("！!。,.， ")
        header_greeting = f"{base_trimmed}，{preferred_name}"
    else:
        header_greeting = base_greeting
    layout_class = ""

    def _module_subsection(title: str, description: str, content: str) -> str:
        if not content or not content.strip():
            return ""
        description_html = (
            f'<div class="module-subsection-copy">{escape(description)}</div>'
            if description else ""
        )
        return (
            '<div class="module-subsection">'
            '<div class="module-subsection-head">'
            f'<div class="module-subsection-title">{escape(title)}</div>'
            '</div>'
            f'{description_html}'
            f'{content}'
            '</div>'
        )

    def _section_card(section_key: str, icon: str, bg_color: str, title: str, summary: str, content: str, expanded: bool = False) -> str:
        if not content or not content.strip():
            return ""
        expanded_class = " expanded" if expanded else ""
        return (
            f'<div class="section-card{expanded_class}" data-section="{section_key}">'
            f'<div class="section-card-header">'
            f'<div class="section-card-icon" style="background:{bg_color}">{icon}</div>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="section-card-title">{escape(title)}</div>'
            f'<div class="section-card-summary">{escape(summary)}</div>'
            f'</div>'
            f'<div class="section-card-arrow">&#9662;</div>'
            f'</div>'
            f'<div class="section-card-body">{content}</div>'
            f'</div>'
        )

    def _vitals_subcards() -> str:
        vd = so.get("latest_health_summary") or {}
        icons = {"blood_pressure": "🩸", "heart_rate": "💓", "blood_oxygen": "🫁",
                 "blood_glucose": "🍬", "steps_today": "👟"}
        labels = {"blood_pressure": "血压", "heart_rate": "心率",
                  "blood_oxygen": "血氧", "blood_glucose": "血糖",
                  "steps_today": "步数"}
        html = ""
        for k in ("blood_pressure", "heart_rate", "blood_oxygen", "blood_glucose", "steps_today"):
            val = vd.get(k, "")
            if val:
                html += (
                    f'<div class="sub-card">'
                    f'<div class="sub-card-header">'
                    f'<span class="sub-card-icon">{icons.get(k, "📊")}</span>'
                    f'<div class="flex-1 min-w-0">'
                    f'<div class="sub-card-label">{labels.get(k, k)}</div>'
                    f'<div class="sub-card-value">{escape(str(val))}</div>'
                    f'</div></div></div>'
                )
        return html if html else '<p class="text-slate-500">暂无数据</p>'

    def _adherence_subcards() -> str:
        adh = so.get("adherence_analysis") or {}
        icons = {"medication": "💊", "appetite": "🍽️", "exercise": "🏃", "monitoring": "📋"}
        labels = {"medication": "用药", "appetite": "食欲与饮食",
                  "exercise": "运动与活动", "monitoring": "健康监测"}
        html = ""
        for k in ("medication", "appetite", "exercise", "monitoring"):
            dim = adh.get(k)
            if not isinstance(dim, dict) or not dim.get("status"):
                continue
            status_text_local = dim["status"]
            is_good = any(w in status_text_local.lower() or w in status_text_local for w in _GOOD_STATUS_KEYWORDS)
            color = "text-emerald-700" if is_good else "text-amber-700"

            detail_parts = []
            for dk in [x for x in dim if x != "status"]:
                val = dim[dk]
                if val:
                    label = _field_label(dk)
                    detail_parts.append(
                        f'<div class="text-sm text-slate-600 mb-1">'
                        f'<span class="font-medium text-slate-500">{label}：</span> {escape(str(val))}</div>'
                    )
            body_html = "".join(detail_parts)

            html += (
                f'<div class="sub-card">'
                f'<div class="sub-card-header">'
                f'<span class="sub-card-icon">{icons.get(k, "📋")}</span>'
                f'<div class="flex-1 min-w-0">'
                f'<div class="sub-card-label">{labels.get(k, k)}</div>'
                f'<div class="sub-card-value {color}">{escape(status_text_local)}</div>'
                f'</div>'
                f'<span class="sub-card-arrow">▶</span>'
                f'</div>'
            )
            if body_html:
                html += f'<div class="sub-card-body">{body_html}</div>'
            html += '</div>'
        return html

    def _recs_subcards() -> str:
        recs = so.get("recommendations") or []
        if not recs:
            return ""
        html = ""
        if "risk_tags" in visible:
            tags = _render_risk_tags(so.get("risk_tags") or [])
            if tags:
                html += f'<div class="flex flex-wrap gap-2 mb-3">{tags}</div>'
        for r in recs:
            if isinstance(r, dict):
                text = r.get("text", "")
                reason = r.get("reason", "")
                category = r.get("category", "")
                icon = _CATEGORY_ICONS.get(category, "💡")
            else:
                text = str(r)
                reason = ""
                icon = "💡"
            safe_text = escape(text).replace("'", "&#39;")

            body_parts = []
            if reason:
                body_parts.append(
                    f'<div class="text-sm text-emerald-700 leading-relaxed italic mb-2">'
                    f'💬 {escape(reason)}</div>'
                )
            body_parts.append(
                f'<div class="feedback-actions" style="flex-direction:row;flex-wrap:wrap">'
                f'<button class="feedback-btn like" title="有帮助" '
                f"onclick=\"saveLike(-1,'rec','{safe_text}')\">适合我</button>"
                f'<button class="feedback-btn feedback-skip" title="不适合我" '
                f"onclick=\"showFeedbackModal(-1,'rec','{safe_text}')\">不适合</button>"
                f'</div>'
            )
            body_html = "".join(body_parts)

            html += (
                f'<div class="sub-card">'
                f'<div class="sub-card-header">'
                f'<span class="sub-card-icon">{icon}</span>'
                f'<div class="flex-1 min-w-0">'
                f'<div class="sub-card-value" style="font-size:0.92em">{escape(text)}</div>'
                f'</div>'
                f'<span class="sub-card-arrow">▶</span>'
                f'</div>'
                f'<div class="sub-card-body">{body_html}</div>'
                f'</div>'
            )
        reasoning = so.get("reasoning") or ""
        if reasoning and "reasoning" in visible:
            html += (
                f'<div class="text-xs text-slate-500 mt-3 bg-slate-50 rounded-lg p-3 leading-relaxed">'
                f'💭 {escape(reasoning)}</div>'
            )
        return html

    card_defs = [
        ("guidance", "💚", "#d1fae5", "健康指导",
         lambda: _render_health_guidance(so.get("health_guidance") or {}, conditions, tone_profile=tone_profile)),
        ("memory", "🧠", "#e0e7ff", "健康记录",
         lambda: _render_memory(memory)),
        ("vitals", "📊", "#fef3c7", "最新健康数据",
         lambda: _vitals_subcards()),
        ("adherence", "📋", "#f3e8ff", "依从性概览",
         lambda: _adherence_subcards()),
        ("recommendations", "💡", "#dcfce7", "健康建议",
         lambda: _recs_subcards()),
        ("nutrition", "🥗", "#ecfdf5", "营养建议",
         lambda: (
             '<p style="font-size:0.95em;line-height:1.7;color:#334155;padding:8px 0">'
             + escape(so.get("nutrition_advice") or "保持均衡饮食，多吃新鲜蔬菜，注意适量饮水。")
             + '</p>'
         )),
        ("diet_table", "📑", "#fff7ed", "疾病饮食对照",
         lambda: _render_diet_table(so.get("diet_table") or [])),
        ("cuisine", "🍜", "#fdf2f8", "口味偏好",
         lambda: (
             '<p class="text-sm text-slate-500 mb-3">选择您喜欢的菜系，'
             "后续食谱会尽量参考您的口味。</p>"
             '<div class="flex flex-wrap gap-2 mb-3" id="cuisineChips"></div>'
             '<div class="flex items-center gap-2">'
             '<input id="customCuisineInput" type="text" placeholder="添加其他菜系..." '
             'class="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2 '
             'focus:outline-none focus:border-emerald-400 focus:ring-1 focus:ring-emerald-200">'
             '<button onclick="addCustomCuisine()" class="px-3 py-2 rounded-lg bg-emerald-50 '
             'border border-emerald-200 text-emerald-700 text-sm font-medium hover:bg-emerald-100">'
             '+ 添加</button></div>'
         )),
        ("meal_plan", "📅", "#eff6ff", "一周餐食灵感",
         lambda: (
             '<div class="flex gap-2 mb-4 overflow-x-auto pb-2" id="dayTabs"></div>'
             '<div id="mealContent"></div>'
         )),
        ("diet_tips", "✨", "#f0fdf4", "饮食小贴士",
         lambda: _render_diet_tips(so.get("diet_tips") or [])),
        ("map", "🏥", "#f0f9ff", "附近医疗与公园",
         lambda: map_section),
        ("submit", "✓", "#ecfdf5", "提交偏好",
         lambda: (
             '<button id="exportFeedbackBtn" onclick="exportFeedbackJSON()" style="display:none" '
             'class="w-full px-6 py-3 rounded-full text-sm font-bold bg-emerald-600 text-white shadow-md '
             'hover:bg-emerald-700 active:scale-95 transition-all">'
             '✓ 提交我的偏好</button>'
             '<p class="text-xs text-slate-400 mt-2 text-center" id="submitHint" style="display:none">'
             '您的选择会用于下次生成更合适的建议</p>'
         )),
    ]

    vitals_data = so.get("latest_health_summary") or {}
    bp_preview = vitals_data.get("blood_pressure", "")
    hr_preview = vitals_data.get("heart_rate", "")
    vitals_preview = f"血压 {bp_preview}，心率 {hr_preview}" if bp_preview else "血压、心率、血糖等最新数据"

    guidance_data = so.get("health_guidance") or {}
    guidance_summary = guidance_data.get("summary", "") if isinstance(guidance_data, dict) else ""
    guidance_preview = (guidance_summary or "结合您的疾病和近期情况生成的个性化建议")[:80]
    if len(guidance_summary) > 80:
        guidance_preview += "..."

    card_summaries = {
        "guidance": guidance_preview,
        "memory": "您的长期资料、近期趋势和关键事件",
        "vitals": vitals_preview,
        "adherence": "近期用药、饮食、运动和监测情况",
        "recommendations": "适合当前情况的可执行建议",
        "nutrition": "吃什么，以及为什么这样吃",
        "diet_table": "不同疾病对应的饮食原则",
        "cuisine": "告诉我们您喜欢的口味",
        "meal_plan": "早餐、午餐和晚餐灵感",
        "diet_tips": "更容易坚持的饮食提醒",
        "map": "附近医院和公园",
        "submit": "保存您的反馈和偏好",
    }

    cards_html_parts = []
    for section_key, icon, bg_color, title, render_fn in card_defs:
        if section_key not in visible:
            continue
        content = render_fn()
        if not content or not content.strip():
            continue

        summary = card_summaries.get(section_key, "")
        cards_html_parts.append(
            f'<div class="section-card" data-section="{section_key}">'
            f'<div class="section-card-header">'
            f'<div class="section-card-icon" style="background:{bg_color}">{icon}</div>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="section-card-title">{title}</div>'
            f'<div class="section-card-summary">{summary}</div>'
            f'</div>'
            f'<div class="section-card-arrow">&#9662;</div>'
            f'</div>'
            f'<div class="section-card-body">{content}</div>'
            f'</div>'
        )

    cards_html = "\n".join(cards_html_parts)

    nutrition_text = (
        '<div class="rounded-xl bg-emerald-50 border border-emerald-100 px-4 py-4 '
        'text-[0.95em] leading-7 text-slate-700">'
        + escape(so.get("nutrition_advice") or "保持均衡饮食，多吃新鲜蔬菜，注意适量饮水。")
        + '</div>'
    )
    cuisine_html = (
        '<p class="text-sm text-slate-500 mb-3">选择您喜欢的菜系，后续餐食灵感会尽量参考您的口味。</p>'
        '<div class="flex flex-wrap gap-2 mb-3" id="cuisineChips"></div>'
        '<div class="flex items-center gap-2">'
        '<input id="customCuisineInput" type="text" placeholder="添加其他菜系..." '
        'class="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2 '
        'focus:outline-none focus:border-emerald-400 focus:ring-1 focus:ring-emerald-200">'
        '<button onclick="addCustomCuisine()" class="px-3 py-2 rounded-lg bg-emerald-50 '
        'border border-emerald-200 text-emerald-700 text-sm font-medium hover:bg-emerald-100">'
        '+ 添加</button></div>'
    )
    meal_plan_html = (
        '<div class="flex gap-2 mb-4 overflow-x-auto pb-2" id="dayTabs"></div>'
        '<div id="mealContent"></div>'
    )
    submit_cta_html = (
        '<div id="submitCtaShell" class="submit-cta-shell">'
        '<button id="exportFeedbackBtn" onclick="exportFeedbackJSON()" '
        'class="submit-cta-button" disabled>✓ 先选择偏好再提交</button>'
        '<p class="submit-cta-hint" id="submitHint">'
        '请先在上面选择口味或标记适合/不适合</p>'
        '</div>'
    ) if "submit" in visible else ""

    hero_vitals_block = _render_vitals(so.get("latest_health_summary") or {}) if "vitals" in visible else ""
    hero_vitals_html = f'<div class="px-3 pt-3">{hero_vitals_block}</div>' if hero_vitals_block else ""
    memory_overview_html = _render_memory_overview(memory) if "memory" in visible else ""
    top_overview_html = (
        '<div class="px-3 pt-3">'
        '<div class="top-overview-panel rounded-[28px] p-3 shadow-sm">'
        '<div class="flex items-center gap-2 mb-2 px-1">'
        '<span class="top-overview-kicker text-base">🗂️</span>'
        '<span class="text-xs font-bold text-slate-600 uppercase tracking-wide">长期情况</span>'
        '</div>'
        f'{memory_overview_html}'
        '</div>'
        '</div>'
    ) if memory_overview_html else ""

    regrouped_cards = []

    guidance_bundle_html = "".join([
        _module_subsection("为什么这些建议和您有关", "先把您的病史、当前用药和最近指标放在前面，后面的建议会更容易看懂。", _render_personalized_context(so, payload, memory)) if ("guidance" in visible or "recommendations" in visible) else "",
        _module_subsection("健康指导", "结合您最近的感受，整理出现在最值得留意的重点。", _render_health_guidance(so.get("health_guidance") or {}, conditions, tone_profile=tone_profile)) if "guidance" in visible else "",
        _module_subsection("健康建议", "这些是现在更适合您去做的小步骤。", _recs_subcards()) if "recommendations" in visible else "",
    ])
    if guidance_bundle_html:
        regrouped_cards.append(
            _section_card(
                "guidance_bundle",
                "💚",
                "#d1fae5",
                "现在怎么做",
                "把重点提醒和建议放在一起，更容易看懂。",
                guidance_bundle_html,
            )
        )

    adherence_body_parts = []
    if "adherence" in visible:
        adherence_html = _adherence_subcards()
        if adherence_html.strip():
            adherence_body_parts.append(
                _module_subsection("执行情况", "看看最近用药、饮食、活动和监测情况。", adherence_html)
            )
    key_events_html = _render_key_events(memory) if "memory" in visible else ""
    if key_events_html.strip():
        adherence_body_parts.append(
            _module_subsection("关键事件", "把最近的重要记录放在一起，前后变化会更好理解。", key_events_html)
        )
    adherence_bundle_html = "".join(adherence_body_parts)
    if adherence_bundle_html:
        regrouped_cards.append(
            _section_card(
                "adherence",
                "📋",
                "#f3e8ff",
                "最近情况",
                "把最近做得怎么样和关键事件放在一起看。",
                adherence_bundle_html,
            )
        )

    nutrition_bundle_html = "".join([
        _module_subsection("营养建议", "先看这段时间吃什么会更适合您。", nutrition_text) if "nutrition" in visible else "",
        _module_subsection("疾病饮食对照", "哪些食物更适合，哪些先少吃一点。", _render_diet_table(so.get("diet_table") or [])) if "diet_table" in visible else "",
        _module_subsection("饮食小贴士", "都是些更容易用得上的小提醒。", _render_diet_tips(so.get("diet_tips") or [])) if "diet_tips" in visible else "",
    ])
    if nutrition_bundle_html:
        regrouped_cards.append(
            _section_card(
                "nutrition_bundle",
                "🥗",
                "#ecfdf5",
                "吃什么更合适",
                "把吃法、对照和小提醒放在一起，更好参考。",
                nutrition_bundle_html,
            )
        )

    meal_bundle_html = "".join([
        _module_subsection("口味偏好", "选一些您平时更愿意吃的口味，后面的建议会更贴近您。", cuisine_html) if "cuisine" in visible else "",
        _module_subsection("一周餐食灵感", "给您一些这周更容易照着吃的早、中、晚餐想法。", meal_plan_html) if "meal_plan" in visible else "",
    ])
    if meal_bundle_html:
        regrouped_cards.append(
            _section_card(
                "meal_bundle",
                "🍽️",
                "#eff6ff",
                "吃饭灵感",
                "喜欢吃什么、这一周怎么吃，都放在这里。",
                meal_bundle_html,
            )
        )

    if "map" in visible and map_section.strip():
        regrouped_cards.append(_section_card("map", "🏥", "#f0f9ff", "附近地点", "附近医院和公园，都可以在这里看。", map_section))

    cards_html = "\n".join(part for part in regrouped_cards if part)

    report_title = "依从性报告"
    html = template.format(
        report_title=report_title,
        header_greeting=header_greeting,
        layout_class=layout_class,
        patient_id=patient_id,
        current_time=current_time,
        status_badge_class=badge_class,
        status_icon=status_icon,
        status_text=status_text,
        condition_badges=_render_condition_badges(conditions),
        hero_vitals_html=hero_vitals_html,
        top_overview_html=top_overview_html,
        escalation_html=_render_escalation_banner(escalations) if "escalation" in visible else "",
        ai_message_html=_render_ai_message(so),
        cards_html=cards_html,
        submit_cta_html=submit_cta_html,
        meal_data_json=meal_json,
        maps_script=maps_script,
        guardrail=escape(
            so.get("guardrail")
            or "本报告由 AI 健康助手生成，仅供参考，不构成医疗建议。如有不适，请及时联系医生或拨打 120。"
        ),
    )

    escalation_records = []
    for esc in escalations:
        escalation_records.append({
            "level": esc["level"],
            "title": esc["title"],
            "message": esc["message"],
            "count": esc["count"],
            "threshold": esc["threshold"],
            "detected_at": meta.get("current_time") or datetime.now().isoformat(),
        })

    result = {
        "structured_output": {
            "title": report_title,
            "category": "adherence",
            "html": html,
            "detail": so,
            "escalations": escalation_records,
        },
    }

    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
