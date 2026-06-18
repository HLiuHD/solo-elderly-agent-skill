#!/usr/bin/env python3
"""
post_llm script for adherence-report-en skill.

Reads {"payload": {...}, "llm_result": {...}} from stdin.
Renders a patient-facing adherence HTML report from a template + LLM structured data.
Writes JSON to stdout with structured_output.html.
"""

from __future__ import annotations

import json
import os
import sys
from html import escape
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "report.html"
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

_STATUS_MAP = {
    "stable": ("bg-emerald-100 text-emerald-800", "✅", "Doing well"),
    "at_risk": ("bg-amber-100 text-amber-800", "⚠️", "Needs attention"),
}

_COND_COLORS = {
    "Hypertension": "bg-rose-500",
    "Type 2 diabetes": "bg-amber-500",
    "Diabetes": "bg-amber-500",
    "Hyperlipidemia": "bg-orange-500",
    "Coronary artery disease": "bg-red-500",
    "During chemotherapy": "bg-purple-500",
}

_RISK_TAG_COLORS = {
    "heart rate": "bg-rose-50 text-rose-700 border-rose-200",
    "blood pressure": "bg-rose-50 text-rose-700 border-rose-200",
    "glucose": "bg-amber-50 text-amber-700 border-amber-200",
    "activity": "bg-sky-50 text-sky-700 border-sky-200",
    "appetite": "bg-orange-50 text-orange-700 border-orange-200",
    "low": "bg-amber-50 text-amber-700 border-amber-200",
    "high": "bg-rose-50 text-rose-700 border-rose-200",
    "decreased": "bg-orange-50 text-orange-700 border-orange-200",
    "missed": "bg-rose-50 text-rose-700 border-rose-200",
}

_VITAL_DEFS = [
    ("blood_pressure", "Blood pressure", "mmHg", "💓"),
    ("heart_rate", "Heart rate", "bpm", "❤️"),
    ("blood_oxygen", "Blood oxygen", "%", "🫁"),
    ("blood_glucose", "Blood glucose", "mmol/L", "🩸"),
    ("steps_today", "Steps today", "steps", "🚶"),
]

_REC_ICONS = ["💊", "🚶", "🫀", "🩸", "🧈", "🥗", "🧘", "💤"]

_ADHERENCE_DIMENSIONS = [
    ("medication", "💊", "Medication"),
    ("appetite", "🍽️", "Appetite & diet"),
    ("exercise", "🏃", "Exercise & activity"),
    ("monitoring", "📋", "Health monitoring"),
]

# ─── Escalation Rules ───────────────────────────────────────────────
# When a symptom keyword appears >= THRESHOLD times in key_events,
# the report escalates from "stable"/"at_risk" display to a warning banner.
_ESCALATION_RULES = [
    {
        "keywords": ["headache", "head pain", "migraine"],
        "threshold": 3,
        "level": "escalated",
        "title": "Recurring headache — escalated to attention",
        "message": (
            "You have reported headaches {count} times in recent records. "
            "Because this symptom keeps coming back, we are flagging this for "
            "closer monitoring and your doctor will be notified."
        ),
        "recommendation": "Please note the time, severity (1-10), and any triggers each time it happens.",
    },
    {
        "keywords": ["dizzy", "dizziness", "lightheaded", "vertigo"],
        "threshold": 3,
        "level": "escalated",
        "title": "Recurring dizziness — escalated to attention",
        "message": (
            "Dizziness has been reported {count} times recently. "
            "This pattern may indicate blood pressure fluctuation or medication side effects."
        ),
        "recommendation": "Sit or lie down when dizzy. Note whether it happens after standing up or taking medication.",
    },
    {
        "keywords": ["chest pain", "chest tightness", "chest discomfort"],
        "threshold": 2,
        "level": "critical",
        "title": "Recurring chest symptoms — urgent",
        "message": (
            "Chest-related symptoms reported {count} times. "
            "This requires immediate medical attention."
        ),
        "recommendation": "If you experience chest pain right now, call 911 immediately.",
    },
    {
        "keywords": ["fall", "fell down", "lost balance"],
        "threshold": 2,
        "level": "escalated",
        "title": "Multiple falls detected",
        "message": (
            "You have had {count} fall-related events. "
            "This increases injury risk and your care team will review your mobility."
        ),
        "recommendation": "Avoid walking without support. Remove tripping hazards at home.",
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
            if any(kw in text for kw in rule["keywords"])
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
    """Render AI message as sub-cards if structured sections are available."""
    sections = so.get("assistant_message_sections") or []

    if sections:
        html = ""
        for sec in sections:
            sec_type = sec.get("type", "")
            title = sec.get("title", "")
            content = sec.get("content", "")
            style = _AI_MSG_STYLES.get(sec_type, {"icon": "💬", "color": "bg-slate-50 border-slate-200", "title_color": "text-slate-800"})

            html += (
                f'<div class="sub-card" style="border-color:transparent">'
                f'<div class="sub-card-header" style="padding:12px 14px">'
                f'<span class="sub-card-icon" style="font-size:1.2em">{style["icon"]}</span>'
                f'<div class="flex-1 min-w-0">'
                f'<div class="sub-card-value {style["title_color"]}" style="font-size:0.95em">{escape(title)}</div>'
                f'</div>'
                f'<span class="sub-card-arrow">▶</span>'
                f'</div>'
                f'<div class="sub-card-body">'
                f'<div class="text-sm text-slate-700 leading-relaxed">{escape(content)}</div>'
                f'</div></div>'
            )
        return html

    # Fallback: plain text (backward compatibility)
    plain = so.get("assistant_message_patient") or ""
    if not plain:
        return ""
    preview = escape(plain[:70]) + ("..." if len(plain) > 70 else "")
    return (
        f'<div class="sub-card" style="border-color:transparent">'
        f'<div class="sub-card-header" style="padding:12px 14px">'
        f'<span class="sub-card-icon" style="font-size:1.2em">💬</span>'
        f'<div class="flex-1 min-w-0">'
        f'<div class="sub-card-value" style="font-size:0.9em;font-weight:600;color:#334155">{preview}</div>'
        f'</div>'
        f'<span class="sub-card-arrow">▶</span>'
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
            badge_text = "URGENT"
        else:
            banner_cls = "bg-gradient-to-r from-amber-50 to-orange-50 border-amber-300"
            icon = "⚠️"
            title_cls = "text-amber-800"
            badge_cls = "bg-amber-500 text-white"
            badge_text = "ESCALATED"

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
            f'<span class="font-semibold">What to do:</span> {escape(esc["recommendation"])}'
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


def _render_vitals(summary: dict) -> str:
    parts = []
    for key, label, unit, icon in _VITAL_DEFS:
        val = summary.get(key)
        if val is not None and val != "":
            parts.append(
                f'<div class="bg-slate-50 rounded-lg p-3 text-center border border-slate-100">'
                f'<div class="text-lg mb-0.5">{icon}</div>'
                f'<div class="text-[11px] text-slate-500 font-medium mb-1">{label}</div>'
                f'<div class="text-xl font-bold text-slate-800">{escape(str(val))}</div>'
                f'<div class="text-[10px] text-slate-400">{unit}</div>'
                f'</div>'
            )
        else:
            parts.append(
                f'<div class="bg-slate-50 rounded-lg p-3 text-center border border-slate-100">'
                f'<div class="text-lg mb-0.5">{icon}</div>'
                f'<div class="text-[11px] text-slate-500 font-medium mb-1">{label}</div>'
                f'<div class="text-base text-slate-300">--</div>'
                f'</div>'
            )
    return "\n".join(parts)


def _render_condition_badges(conditions: list[str]) -> str:
    parts = []
    for c in conditions:
        color = _COND_COLORS.get(c, "bg-slate-500")
        parts.append(
            f'<span class="inline-block {color} text-white px-3 py-1 '
            f'rounded-full text-xs font-semibold">{escape(c)}</span>'
        )
    return "\n".join(parts)


def _render_risk_tags(tags: list[str]) -> str:
    if not tags:
        return (
            '<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
            'border bg-emerald-50 text-emerald-700 border-emerald-200">No major risks flagged</span>'
        )
    parts = []
    for tag in tags:
        cls = "bg-slate-50 text-slate-600 border-slate-200"
        tag_lower = tag.lower()
        for kw, c in _RISK_TAG_COLORS.items():
            if kw in tag_lower:
                cls = c
                break
        parts.append(
            f'<span class="inline-block px-3 py-1 rounded-full text-xs '
            f'font-medium border {cls}">{escape(tag)}</span>'
        )
    return "\n".join(parts)


_CATEGORY_ICONS = {
    "medication": "💊",
    "diet": "🥗",
    "exercise": "🏃",
    "monitoring": "📋",
    "lifestyle": "🏠",
}


def _render_recommendations(recs: list) -> str:
    if not recs:
        return '<div class="text-sm text-slate-400">No specific recommendations yet</div>'
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
            category = ""
            icon = _REC_ICONS[i % len(_REC_ICONS)]

        safe_text = escape(text).replace("'", "&#39;")
        reason_html = ""
        if reason:
            reason_html = (
                f'<div class="text-xs text-emerald-700 mt-1.5 leading-relaxed italic '
                f'bg-emerald-50 rounded px-2 py-1 border-l-2 border-emerald-300">'
                f'💬 {escape(reason)}</div>'
            )

        parts.append(
            f'<div class="bg-emerald-50 rounded-lg p-3 '
            f'border border-emerald-100 meal-card">'
            f'<div class="flex items-start gap-3">'
            f'<span class="text-base mt-0.5">{icon}</span>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="text-sm text-slate-700 leading-relaxed font-medium">{escape(text)}</div>'
            f'{reason_html}</div>'
            f'<div class="flex flex-col gap-1 flex-shrink-0">'
            f'<button class="feedback-btn like" title="Helpful" '
            f"onclick=\"saveLike(-1,'rec','{safe_text}')\">👍</button>"
            f'<button class="feedback-btn" title="Not helpful" '
            f"onclick=\"showFeedbackModal(-1,'rec','{safe_text}')\">👎</button>"
            f'</div></div></div>'
        )
    return "\n".join(parts)


def _render_reasoning(reasoning: str) -> str:
    if not reasoning:
        return ""
    return (
        '<div class="mt-4 pt-3 border-t border-slate-100">'
        '<div class="text-[11px] text-slate-400 uppercase tracking-wide font-medium mb-1.5">'
        "How we assessed this</div>"
        f'<div class="text-xs text-slate-600 bg-slate-50 rounded-lg p-3 leading-relaxed">{escape(reasoning)}</div>'
        '</div>'
    )


def _render_adherence_dimension(icon: str, title: str, dim: dict) -> str:
    status = dim.get("status") or ""
    detail_keys = [k for k in dim if k != "status"]
    if not status and not detail_keys:
        return ""

    is_good = any(
        kw in status.lower()
        for kw in ("good", "on track", "compliant", "met", "adequate", "consistent")
    )
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
            label = key.replace("_", " ").capitalize()
            html += (
                f'<div class="text-xs text-slate-600 mt-1">'
                f'<span class="font-medium text-slate-500">{label}:</span> {escape(str(val))}'
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
            f'Period: {escape(period)}</div>'
        )
    if cards:
        inner += f'<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">{"".join(cards)}</div>'
    return inner


def _render_memory(memory: dict) -> str:
    """Render health history as sub-cards: profile, trends, events — each tappable."""
    if not memory:
        return ""

    profile = memory.get("patient_long_term_profile") or ""
    dynamics = memory.get("recent_health_dynamics") or ""
    events = memory.get("key_events") or []

    if not profile and not dynamics and not events:
        return ""

    html = ""

    if profile:
        html += (
            '<div class="sub-card">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">👤</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">Profile</div>'
            f'<div class="sub-card-value">{escape(profile[:60])}...</div>'
            '</div>'
            '<span class="sub-card-arrow">▶</span>'
            '</div>'
            f'<div class="sub-card-body"><div class="text-sm text-slate-700 leading-relaxed">{escape(profile)}</div></div>'
            '</div>'
        )

    if dynamics:
        html += (
            '<div class="sub-card">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">📈</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">Recent trends</div>'
            f'<div class="sub-card-value">{escape(dynamics[:60])}...</div>'
            '</div>'
            '<span class="sub-card-arrow">▶</span>'
            '</div>'
            f'<div class="sub-card-body"><div class="text-sm text-slate-700 leading-relaxed">{escape(dynamics)}</div></div>'
            '</div>'
        )

    if events:
        _EVENT_ICONS = {"surgery": "🔪", "symptom": "⚠️", "alert": "🚨", "medication": "💊", "visit": "🏥"}
        events_body = '<div class="space-y-2">'
        for ev in events:
            ev_icon = _EVENT_ICONS.get(ev.get("type", ""), "📌")
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

        html += (
            '<div class="sub-card">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">📋</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">Key events</div>'
            f'<div class="sub-card-value">{len(events)} recorded events</div>'
            '</div>'
            '<span class="sub-card-arrow">▶</span>'
            '</div>'
            f'<div class="sub-card-body">{events_body}</div>'
            '</div>'
        )

    return html


def _render_doctor_notes(doctor_feedback: dict) -> str:
    if not doctor_feedback:
        return ""

    doctor_name = doctor_feedback.get("doctor_name") or "Your doctor"
    timestamp = doctor_feedback.get("timestamp") or ""
    message = doctor_feedback.get("message") or ""
    med_changes = doctor_feedback.get("medication_changes") or []

    if not message and not med_changes:
        return ""

    time_display = ""
    if timestamp:
        time_display = _format_time(timestamp)

    html = (
        '<div class="bg-white rounded-xl shadow-sm border border-blue-100 p-5 mb-3">'
        '<div class="flex items-center gap-2 mb-3 pb-3 border-b border-blue-50">'
        '<span class="text-lg">👨\u200d⚕️</span>'
        '<div class="flex-1">'
        f'<h2 class="text-sm font-bold text-slate-800">{escape(doctor_name)}\'s notes</h2>'
    )
    if time_display:
        html += f'<div class="text-[10px] text-slate-400">{escape(time_display)}</div>'
    html += '</div></div>'

    if message:
        html += (
            '<div class="text-sm text-slate-700 bg-blue-50 rounded-lg p-3 leading-relaxed '
            f'border border-blue-100 mb-3" style="border-left:3px solid #3b82f6">{escape(message)}</div>'
        )

    if med_changes:
        html += (
            '<div class="mt-2">'
            '<div class="text-[11px] text-slate-400 uppercase tracking-wide font-medium mb-2">Medication changes</div>'
        )
        for change in med_changes:
            action = change.get("action", "").capitalize()
            from_med = change.get("from", "")
            to_med = change.get("to", "")
            html += (
                '<div class="flex items-start gap-2 bg-amber-50 rounded-lg p-3 border border-amber-100">'
                f'<span class="text-sm mt-0.5">💊</span>'
                '<div class="text-xs text-slate-700 leading-relaxed">'
                f'<span class="font-semibold text-amber-700">{escape(action)}:</span> '
            )
            if from_med:
                html += f'<span class="line-through text-slate-400">{escape(from_med)}</span> → '
            if to_med:
                html += f'<span class="font-medium text-emerald-700">{escape(to_med)}</span>'
            html += '</div></div>'
        html += '</div>'

    html += '</div>'
    return html


_CONDITION_CONTEXTS = {
    "feeling_unwell": {
        "show_sections": {"header", "escalation", "ai_message", "guidance", "vitals", "meal_plan", "guardrail"},
        "tone_override": "gentle_patient",
        "header_greeting": "We're here for you",
        "guidance_emphasis": "rest",
    },
    "post_chemotherapy": {
        "show_sections": {"header", "escalation", "ai_message", "doctor_notes", "guidance", "vitals", "recommendations", "nutrition", "meal_plan", "cuisine", "diet_tips", "submit", "guardrail"},
        "tone_override": "gentle_patient",
        "header_greeting": "You're doing so well",
        "guidance_emphasis": "nutrition",
    },
    "post_surgery_recovering": {
        "show_sections": {"header", "escalation", "ai_message", "memory", "doctor_notes", "guidance", "vitals", "adherence", "recommendations", "nutrition", "diet_table", "cuisine", "meal_plan", "diet_tips", "map", "submit", "guardrail"},
        "tone_override": None,
        "header_greeting": "Hello!",
        "guidance_emphasis": None,
    },
    "chronic_pain_flare": {
        "show_sections": {"header", "escalation", "ai_message", "guidance", "vitals", "recommendations", "meal_plan", "guardrail"},
        "tone_override": "gentle_patient",
        "header_greeting": "We know today is tough",
        "guidance_emphasis": "rest",
    },
    "low_mood_isolated": {
        "show_sections": {"header", "ai_message", "guidance", "vitals", "recommendations", "nutrition", "meal_plan", "cuisine", "map", "diet_tips", "submit", "guardrail"},
        "tone_override": "warm_encouraging",
        "header_greeting": "You're not alone",
        "guidance_emphasis": "exercise",
    },
    "cognitive_decline": {
        "show_sections": {"header", "ai_message", "guidance", "vitals", "meal_plan", "guardrail"},
        "tone_override": "gentle_patient",
        "header_greeting": "Here's what to remember today",
        "guidance_emphasis": "monitoring",
    },
    "caregiver_absent": {
        "show_sections": {"header", "escalation", "ai_message", "guidance", "vitals", "recommendations", "meal_plan", "map", "guardrail"},
        "tone_override": "warm_encouraging",
        "header_greeting": "Your daily check-in",
        "guidance_emphasis": None,
    },
    "medication_adjustment": {
        "show_sections": {"header", "ai_message", "doctor_notes", "guidance", "vitals", "recommendations", "nutrition", "meal_plan", "diet_tips", "submit", "guardrail"},
        "tone_override": "authority_based",
        "header_greeting": "Important update from your care team",
        "guidance_emphasis": "monitoring",
    },
    "high_fall_risk": {
        "show_sections": {"header", "escalation", "ai_message", "guidance", "vitals", "recommendations", "meal_plan", "map", "guardrail"},
        "tone_override": "warm_encouraging",
        "header_greeting": "Let's keep you safe today",
        "guidance_emphasis": "exercise",
    },
    "stable_routine": {
        "show_sections": {"header", "escalation", "ai_message", "memory", "doctor_notes", "guidance", "vitals", "adherence", "risk_tags", "recommendations", "reasoning", "nutrition", "diet_table", "cuisine", "meal_plan", "diet_tips", "map", "submit", "guardrail"},
        "tone_override": None,
        "header_greeting": "Hello!",
        "guidance_emphasis": None,
    },
}

_FULL_SECTIONS = _CONDITION_CONTEXTS["stable_routine"]["show_sections"]


_TONE_STYLES = {
    "warm_encouraging": {
        "icon": "💚",
        "title": "Why this matters for you",
        "border_color": "border-emerald-200",
        "header_color": "text-emerald-800",
        "summary_bg": "bg-emerald-50 border-l-4 border-emerald-400",
        "tip_why_color": "text-emerald-700",
    },
    "direct_practical": {
        "icon": "📋",
        "title": "Key points for your health",
        "border_color": "border-blue-200",
        "header_color": "text-blue-800",
        "summary_bg": "bg-blue-50 border-l-4 border-blue-400",
        "tip_why_color": "text-blue-700",
    },
    "authority_based": {
        "icon": "👨\u200d⚕️",
        "title": "Your care team recommends",
        "border_color": "border-indigo-200",
        "header_color": "text-indigo-800",
        "summary_bg": "bg-indigo-50 border-l-4 border-indigo-400",
        "tip_why_color": "text-indigo-700",
    },
    "gentle_patient": {
        "icon": "🌸",
        "title": "A gentle reminder for you",
        "border_color": "border-rose-200",
        "header_color": "text-rose-800",
        "summary_bg": "bg-rose-50 border-l-4 border-rose-300",
        "tip_why_color": "text-rose-700",
    },
}


def _render_health_guidance(guidance: dict, conditions: list[str], tone_profile: dict = None) -> str:
    """Render health guidance as sub-cards: summary always visible, each tip is tappable."""
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
            f'Personalized for <span class="font-semibold">{escape(patient_name)}</span></div>'
        )
    if summary:
        html += (
            f'<div class="leading-relaxed mb-3 {style["summary_bg"]} '
            f'rounded-lg p-4" style="font-size:0.95em">'
            f'{escape(summary)}</div>'
        )

    _GUIDANCE_ICONS = {"protein": "🥩", "low_salt": "🧂", "low_oil": "🫒",
                       "hydration": "💧", "fiber": "🌾", "exercise": "🚶",
                       "rest": "😴", "monitoring": "📋"}

    for tip in tips:
        if isinstance(tip, dict):
            icon = _GUIDANCE_ICONS.get(tip.get("category", ""), "💡")
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
            f'<div class="sub-card">'
            f'<div class="sub-card-header">'
            f'<span class="sub-card-icon">{icon}</span>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="sub-card-value" style="font-size:0.95em">{escape(text)}</div>'
            f'</div>'
            f'<span class="sub-card-arrow">▶</span>'
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
        '<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5 mb-3">'
        '<div class="flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">'
        '<span class="text-lg">📋</span>'
        '<h2 class="text-sm font-bold text-slate-800">Diet by condition</h2>'
        '</div>'
        '<div class="overflow-x-auto">'
        '<table class="w-full text-sm">'
        '<thead><tr class="bg-slate-50">'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">Condition</th>'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">Principle</th>'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">Favor</th>'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">Limit</th>'
        '</tr></thead>'
        f'<tbody class="divide-y divide-slate-100">{rows}</tbody>'
        '</table></div></div>'
    )


def _render_diet_tips(tips: list[dict]) -> str:
    """Render each diet tip as a tappable sub-card: title visible, detail on tap."""
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
                f'<div class="flex gap-2">'
                f'<button class="feedback-btn like" style="opacity:1" title="Helpful" '
                f"onclick=\"saveLike(-1,'tip','{safe_title}')\">👍</button>"
                f'<button class="feedback-btn" style="opacity:1" title="Not helpful" '
                f"onclick=\"showFeedbackModal(-1,'tip','{safe_title}')\">👎</button>"
                f'</div>'
            )

        html += (
            f'<div class="sub-card">'
            f'<div class="sub-card-header">'
            f'<span class="sub-card-icon">{icon}</span>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="sub-card-value" style="font-size:0.92em">{escape(title)}</div>'
            f'</div>'
            f'<span class="sub-card-arrow">▶</span>'
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
    google_maps_api_key: str = "",
) -> str:
    lat = patient_lat if patient_lat else 42.2766632
    lon = patient_lon if patient_lon else -71.8079906

    if not google_maps_api_key:
        search_hospitals = f"https://www.google.com/maps/search/hospitals/@{lat},{lon},14z"
        search_parks = f"https://www.google.com/maps/search/parks/@{lat},{lon},14z"
        return (
            '<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5 mb-3">'
            '<div class="flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">'
            '<span class="text-lg">📍</span>'
            '<h2 class="text-sm font-bold text-slate-800">Nearby picks</h2>'
            "</div>"
            f'<p class="text-sm text-slate-600 mb-3">{escape(ai_msg_hospital)}</p>'
            '<div class="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 mb-3">'
            "Set GOOGLE_MAPS_API_KEY to render the interactive map."
            "</div>"
            '<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">'
            f'<a class="block rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm font-semibold text-slate-700 hover:bg-slate-100 text-center" href="{search_hospitals}" target="_blank" rel="noopener">🏥 Nearby hospitals</a>'
            f'<a class="block rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm font-semibold text-slate-700 hover:bg-slate-100 text-center" href="{search_parks}" target="_blank" rel="noopener">🌳 Nearby parks</a>'
            "</div></div>"
        )

    hosp_js = json.dumps(ai_msg_hospital, ensure_ascii=False)
    park_js = json.dumps(ai_msg_park, ensure_ascii=False)
    lat_js = json.dumps(float(lat))
    lon_js = json.dumps(float(lon))

    css = (
        "<style>"
        "#gmap{width:100%;height:100%}"
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
        '<h2 class="text-sm font-bold text-slate-800">Nearby picks</h2>'
        "</div>"
        '<p class="text-sm text-slate-600 mb-3" id="ai-map-text">' + ai_msg_hospital + "</p>"
        '<div class="rounded-2xl overflow-hidden border border-slate-200 relative" style="height:240px">'
        '<div id="gmap"></div>'
        '<button id="locate-btn" title="Center on my location">📍</button>'
        "</div>"
        '<div class="map-toggle">'
        '<button class="active" id="btn-hospital" onclick="switchMapMode(\'hospital\')">🏥 Hospitals</button>'
        '<button id="btn-park" onclick="switchMapMode(\'park\')">🌳 Parks</button>'
        "</div>"
        '<div id="map-cards"></div>'
        "</div>"
    )

    js_template = r"""<script>
(function() {
  var map = null;
  var userPoint = { lat: __FALLBACK_LAT__, lng: __FALLBACK_LON__ };
  var mapMode = 'hospital';
  var mapMarkers = [];
  var mapCards = [];
  var directionsRenderer = null;
  var directionsService = null;
  var infoWindow = null;
  var placesService = null;
  var AI_MAP_TEXT = { hospital: __HOSP_MSG__, park: __PARK_MSG__ };

  window.initPatientReportMap = function() {
    map = new google.maps.Map(document.getElementById("gmap"), {
      center: userPoint, zoom: 14,
      mapTypeControl: false, streetViewControl: false, fullscreenControl: false
    });
    infoWindow = new google.maps.InfoWindow();
    directionsService = new google.maps.DirectionsService();
    directionsRenderer = new google.maps.DirectionsRenderer({
      map: map, suppressMarkers: true, preserveViewport: true,
      polylineOptions: { strokeColor: '#1e88e5', strokeOpacity: 0.85, strokeWeight: 5 }
    });
    placesService = new google.maps.places.PlacesService(map);
    new google.maps.Marker({
      map: map, position: userPoint, title: "You are here",
      label: { text: "You", color: "#ffffff", fontWeight: "700" },
      icon: { path: google.maps.SymbolPath.CIRCLE, scale: 9,
        fillColor: "#4285f4", fillOpacity: 1, strokeColor: "#ffffff", strokeWeight: 3 }
    });
    document.getElementById('locate-btn').addEventListener('click', function() {
      map.panTo(userPoint); map.setZoom(15);
    });
    doMapSearch('hospital');
  };

  function clearResultMarkers() {
    if (directionsRenderer) directionsRenderer.setDirections({ routes: [] });
    mapMarkers.forEach(function(m) { m.setMap(null); });
    mapMarkers = []; mapCards = [];
  }

  window.switchMapMode = function(mode) {
    if (mode === mapMode) return;
    mapMode = mode;
    document.getElementById('btn-hospital').className = mode === 'hospital' ? 'active' : '';
    document.getElementById('btn-park').className = mode === 'park' ? 'active park-mode' : '';
    document.getElementById('ai-map-text').textContent = AI_MAP_TEXT[mode];
    clearResultMarkers();
    document.getElementById('map-cards').innerHTML = '<div style="text-align:center;color:#bbb;padding:16px;font-size:0.85em">Searching…</div>';
    doMapSearch(mode);
  };

  function doMapSearch(mode) {
    if (!placesService) return;
    var container = document.getElementById('map-cards');
    placesService.nearbySearch({ location: userPoint, radius: 5000, type: mode === 'hospital' ? 'hospital' : 'park' },
      function(results, status) {
        clearResultMarkers(); container.innerHTML = '';
        if (status !== google.maps.places.PlacesServiceStatus.OK || !results || results.length === 0) {
          container.innerHTML = '<div style="text-align:center;color:#bbb;padding:16px;font-size:0.85em">No nearby places found</div>';
          return;
        }
        var bounds = new google.maps.LatLngBounds(); bounds.extend(userPoint);
        results.slice(0, 6).forEach(function(place, idx) {
          if (!place.geometry || !place.geometry.location) return;
          var point = place.geometry.location; bounds.extend(point);
          var dist = google.maps.geometry.spherical.computeDistanceBetween(
            new google.maps.LatLng(userPoint.lat, userPoint.lng), point);
          var distText = dist >= 1000 ? (dist/1000).toFixed(1)+' km' : Math.round(dist)+' m';
          var marker = new google.maps.Marker({ map: map, position: point, title: place.name });
          mapMarkers.push(marker);
          marker.addListener('click', function() { focusMapCard(idx, place); });
          var card = document.createElement('div'); card.className = 'map-place';
          card.innerHTML = '<div class="map-place-icon '+mode+'">'+(mode==='hospital'?'\ud83c\udfe5':'\ud83c\udf33')+'</div>'
            +'<div style="flex:1;min-width:0"><div style="font-size:0.9em;font-weight:600;color:#222;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+escapeHtml(place.name||'Unknown')+'</div>'
            +'<div style="font-size:0.75em;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+escapeHtml(place.vicinity||'No address')+'</div></div>'
            +'<div class="map-dist '+mode+'">'+distText+'</div>'
            +'<button class="map-place-nav'+(mode==='park'?' park-mode':'')+'" title="Directions">\u27a4</button>';
          card.addEventListener('click', function(e) { if(!e.target.classList.contains('map-place-nav')) focusMapCard(idx, place); });
          card.querySelector('.map-place-nav').addEventListener('click', function(e) { e.stopPropagation(); navigateMapTo(place); });
          container.appendChild(card); mapCards.push(card);
        });
        if (!bounds.isEmpty()) map.fitBounds(bounds, 64);
      });
  }

  function focusMapCard(idx, place) {
    mapCards.forEach(function(c) { c.classList.remove('focused','park-mode'); });
    mapCards[idx].classList.add('focused');
    if (mapMode === 'park') mapCards[idx].classList.add('park-mode');
    mapCards[idx].scrollIntoView({ behavior:'smooth', block:'nearest' });
    map.panTo(place.geometry.location);
    infoWindow.setContent('<b>'+escapeHtml(place.name||'')+'</b><br><span style="color:#888;font-size:12px">'+escapeHtml(place.vicinity||'')+'</span>');
    infoWindow.open(map, mapMarkers[idx]);
    var routeColor = mapMode === 'hospital' ? '#1e88e5' : '#43a047';
    directionsRenderer.setOptions({ polylineOptions: { strokeColor: routeColor, strokeOpacity: 0.85, strokeWeight: 5 } });
    directionsService.route({
      origin: userPoint, destination: place.geometry.location, travelMode: google.maps.TravelMode.WALKING
    }, function(response, status) { if (status === 'OK') directionsRenderer.setDirections(response); });
  }

  function navigateMapTo(place) {
    var dest = place.geometry.location;
    window.open('https://www.google.com/maps/dir/?api=1&origin='+encodeURIComponent(userPoint.lat+','+userPoint.lng)
      +'&destination='+encodeURIComponent(dest.lat()+','+dest.lng())
      +'&destination_place_id='+encodeURIComponent(place.place_id||'')+'&travelmode=walking', '_blank');
  }

  function escapeHtml(v) {
    return String(v||'').replace(/[&<>"']/g, function(c) {
      return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]; });
  }

  window.addEventListener('error', function(e) {
    if (String(e.message||'').toLowerCase().indexOf('google') >= 0) {
      var c = document.getElementById('map-cards');
      if (c) c.innerHTML = '<div style="text-align:center;color:#b45309;padding:16px;font-size:0.85em">Google Maps failed to load.</div>';
    }
  });
})();
</script>"""

    js = js_template.replace("__HOSP_MSG__", hosp_js).replace("__PARK_MSG__", park_js)
    js = js.replace("__FALLBACK_LON__", lon_js).replace("__FALLBACK_LAT__", lat_js)
    return css + "\n" + html + "\n" + js


def _format_time(raw: str) -> str:
    if "T" in str(raw):
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return dt.strftime("%b %d, %Y %H:%M")
        except (ValueError, TypeError):
            pass
    elif isinstance(raw, str) and len(raw) >= 10 and raw[4] == "-":
        try:
            dt = datetime.strptime(raw[:16], "%Y-%m-%d %H:%M")
            return dt.strftime("%b %d, %Y %H:%M")
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
    doctor_feedback = payload.get("doctor_feedback") or {}

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

    # Check for symptom escalation based on memory events
    key_events = memory.get("key_events") or []
    escalations = _check_escalations(key_events)

    status = so.get("patient_status") or "stable"
    # Override status if critical escalation is triggered
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
        kw in t.lower()
        for t in so.get("risk_tags", [])
        for kw in ("activity", "low", "sedentary")
    ):
        ai_map_msg = "Your recent activity looks a bit low. On a nice day, a gentle walk in a nearby park can help."
        ai_map_msg_park = ai_map_msg
    else:
        ai_map_msg = "Nearby care locations are shown if you ever need them."
        ai_map_msg_park = "On pleasant days, a light walk in a nearby park can support mood and mobility."

    google_maps_api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    maps_script = ""
    if google_maps_api_key:
        maps_script = (
            '<script defer '
            'src="https://maps.googleapis.com/maps/api/js'
            f'?key={quote_plus(google_maps_api_key)}'
            '&libraries=places,geometry'
            '&language=en'
            '&callback=initPatientReportMap"></script>'
        )

    map_section = _render_map_section(
        ai_map_msg, ai_map_msg_park,
        patient_lat, patient_lon, google_maps_api_key,
    )

    meal_json = json.dumps(so.get("weekly_meal_plan") or [], ensure_ascii=False)

    patient_id = meta.get("user_id") or "unknown"
    memory_api_url = os.environ.get("MEMORY_API_URL", "").strip()
    memory_api_token = os.environ.get("MEMORY_API_TOKEN", "").strip()

    header_greeting = ctx.get("header_greeting") or "Hello!"

    # Always use card/accordion layout — patient taps to expand what they need
    use_cards = True
    layout_class = ""

    # Build each section's content
    sections = []

    def _vitals_subcards() -> str:
        vd = so.get("latest_health_summary") or {}
        _icons = {"blood_pressure": "🩸", "heart_rate": "💓", "blood_oxygen": "🫁",
                  "blood_glucose": "🍬", "steps_today": "👟"}
        _labels = {"blood_pressure": "Blood Pressure", "heart_rate": "Heart Rate",
                   "blood_oxygen": "Blood Oxygen", "blood_glucose": "Glucose",
                   "steps_today": "Steps"}
        html = ""
        for k in ("blood_pressure", "heart_rate", "blood_oxygen", "blood_glucose", "steps_today"):
            val = vd.get(k, "")
            if val:
                html += (
                    f'<div class="sub-card">'
                    f'<div class="sub-card-header">'
                    f'<span class="sub-card-icon">{_icons.get(k, "📊")}</span>'
                    f'<div class="flex-1 min-w-0">'
                    f'<div class="sub-card-label">{_labels.get(k, k)}</div>'
                    f'<div class="sub-card-value">{escape(str(val))}</div>'
                    f'</div></div></div>'
                )
        return html if html else '<p class="text-slate-500">No data available</p>'

    def _adherence_subcards() -> str:
        adh = so.get("adherence_analysis") or {}
        _icons = {"medication": "💊", "appetite": "🍽️", "exercise": "🏃", "monitoring": "📋"}
        _labels = {"medication": "Medication", "appetite": "Appetite & diet",
                   "exercise": "Exercise & activity", "monitoring": "Health monitoring"}
        html = ""
        for k in ("medication", "appetite", "exercise", "monitoring"):
            dim = adh.get(k)
            if not isinstance(dim, dict) or not dim.get("status"):
                continue
            status = dim["status"]
            is_good = any(w in status.lower() for w in ("good", "on track", "compliant", "adequate"))
            color = "text-emerald-700" if is_good else "text-amber-700"

            detail_parts = []
            for dk in [x for x in dim if x != "status"]:
                val = dim[dk]
                if val:
                    label = dk.replace("_", " ").capitalize()
                    detail_parts.append(
                        f'<div class="text-sm text-slate-600 mb-1">'
                        f'<span class="font-medium text-slate-500">{label}:</span> {escape(str(val))}</div>'
                    )
            body_html = "".join(detail_parts)

            html += (
                f'<div class="sub-card">'
                f'<div class="sub-card-header">'
                f'<span class="sub-card-icon">{_icons.get(k, "📋")}</span>'
                f'<div class="flex-1 min-w-0">'
                f'<div class="sub-card-label">{_labels.get(k, k)}</div>'
                f'<div class="sub-card-value {color}">{escape(status)}</div>'
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
        for i, r in enumerate(recs):
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

            body_html = ""
            body_parts = []
            if reason:
                body_parts.append(
                    f'<div class="text-sm text-emerald-700 leading-relaxed italic mb-2">'
                    f'💬 {escape(reason)}</div>'
                )
            body_parts.append(
                f'<div class="flex gap-2">'
                f'<button class="feedback-btn like" style="opacity:1" title="Helpful" '
                f"onclick=\"saveLike(-1,'rec','{safe_text}')\">👍</button>"
                f'<button class="feedback-btn" style="opacity:1" title="Not helpful" '
                f"onclick=\"showFeedbackModal(-1,'rec','{safe_text}')\">👎</button>"
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

    _CARD_DEFS = [
        ("guidance", "💚", "#d1fae5", "Health Guidance",
         lambda: _render_health_guidance(so.get("health_guidance") or {}, conditions, tone_profile=tone_profile)),
        ("memory", "🧠", "#e0e7ff", "Health History",
         lambda: _render_memory(memory)),
        ("doctor_notes", "👨\u200d⚕️", "#dbeafe", "Doctor's Notes",
         lambda: _render_doctor_notes(doctor_feedback)),
        ("vitals", "📊", "#fef3c7", "Latest Health Data",
         lambda: _vitals_subcards()),
        ("adherence", "📋", "#f3e8ff", "Adherence Overview",
         lambda: _adherence_subcards()),
        ("recommendations", "💡", "#dcfce7", "Suggestions",
         lambda: _recs_subcards()),
        ("nutrition", "🥗", "#ecfdf5", "Nutrition Advice",
         lambda: (
             '<p style="font-size:0.95em;line-height:1.7;color:#334155;padding:8px 0">'
             + escape(so.get("nutrition_advice") or "Aim for balanced meals with plenty of vegetables and adequate hydration.")
             + '</p>'
         )),
        ("diet_table", "📑", "#fff7ed", "Diet by Condition",
         lambda: _render_diet_table(so.get("diet_table") or [])),
        ("cuisine", "🍜", "#fdf2f8", "Cuisine Preferences",
         lambda: (
             '<p class="text-sm text-slate-500 mb-3">Select cuisines you enjoy — '
             "we'll tailor future meal plans to your taste.</p>"
             '<div class="flex flex-wrap gap-2 mb-3" id="cuisineChips"></div>'
             '<div class="flex items-center gap-2">'
             '<input id="customCuisineInput" type="text" placeholder="Add another cuisine..." '
             'class="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2 '
             'focus:outline-none focus:border-emerald-400 focus:ring-1 focus:ring-emerald-200">'
             '<button onclick="addCustomCuisine()" class="px-3 py-2 rounded-lg bg-emerald-50 '
             'border border-emerald-200 text-emerald-700 text-sm font-medium hover:bg-emerald-100">'
             '+ Add</button></div>'
         )),
        ("meal_plan", "📅", "#eff6ff", "Weekly Meal Ideas",
         lambda: (
             '<div class="flex gap-2 mb-4 overflow-x-auto pb-2" id="dayTabs"></div>'
             '<div id="mealContent"></div>'
         )),
        ("diet_tips", "✨", "#f0fdf4", "Diet Tips",
         lambda: _render_diet_tips(so.get("diet_tips") or [])),
        ("map", "🏥", "#f0f9ff", "Nearby Care & Parks",
         lambda: map_section),
        ("submit", "✓", "#ecfdf5", "Submit Preferences",
         lambda: (
             '<button id="exportFeedbackBtn" onclick="exportFeedbackJSON()" style="display:none" '
             'class="w-full px-6 py-3 rounded-full text-sm font-bold bg-emerald-600 text-white shadow-md '
             'hover:bg-emerald-700 active:scale-95 transition-all">'
             '✓ Submit my preferences</button>'
             '<p class="text-xs text-slate-400 mt-2 text-center" id="submitHint" style="display:none">'
             'Your choices will be remembered for next time</p>'
         )),
    ]

    # Dynamic summaries — pull brief data from payload for card previews
    vitals_data = so.get("latest_health_summary") or {}
    bp_preview = vitals_data.get("blood_pressure", "")
    hr_preview = vitals_data.get("heart_rate", "")
    vitals_preview = f"BP {bp_preview}, HR {hr_preview}" if bp_preview else "Blood pressure, heart rate, glucose, and more"

    doctor_name = doctor_feedback.get("doctor_name", "your doctor")
    doctor_preview = f"Latest notes from {doctor_name}"

    guidance_data = so.get("health_guidance") or {}
    guidance_preview = (guidance_data.get("summary") or "Personalized tips based on your conditions")[:80]
    if len(guidance_data.get("summary", "")) > 80:
        guidance_preview += "..."

    _CARD_SUMMARIES = {
        "guidance": guidance_preview,
        "memory": "Your health history and past events",
        "doctor_notes": doctor_preview,
        "vitals": vitals_preview,
        "adherence": "How you've been doing with medication, diet, and exercise",
        "recommendations": "Actionable suggestions for your health",
        "nutrition": "What to eat and why",
        "diet_table": "Foods to prefer and avoid for each condition",
        "cuisine": "Tell us what cuisines you enjoy",
        "meal_plan": "Breakfast, lunch, and dinner ideas for the week",
        "diet_tips": "Quick tips for healthier eating",
        "map": "Hospitals and parks near you",
        "submit": "Save your feedback and preferences",
    }

    cards_html_parts = []
    for section_key, icon, bg_color, title, render_fn in _CARD_DEFS:
        if section_key not in visible:
            continue
        content = render_fn()
        if not content or not content.strip():
            continue

        summary = _CARD_SUMMARIES.get(section_key, "")

        card = (
            f'<div class="section-card" data-section="{section_key}">'
            f'<div class="section-card-header">'
            f'<div class="section-card-icon" style="background:{bg_color}">{icon}</div>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="section-card-title">{title}</div>'
            f'<div class="section-card-summary">{summary}</div>'
            f'</div>'
            f'<div class="section-card-arrow">▼</div>'
            f'</div>'
            f'<div class="section-card-body">{content}</div>'
            f'</div>'
        )
        cards_html_parts.append(card)

    cards_html = "\n".join(cards_html_parts)

    html = template.format(
        report_title="Adherence report",
        header_greeting=header_greeting,
        layout_class=layout_class,
        patient_id=patient_id,
        memory_api_url=memory_api_url,
        memory_api_token=memory_api_token,
        current_time=current_time,
        status_badge_class=badge_class,
        status_icon=status_icon,
        status_text=status_text,
        condition_badges=_render_condition_badges(conditions),
        escalation_html=_render_escalation_banner(escalations) if "escalation" in visible else "",
        ai_message_html=_render_ai_message(so),
        cards_html=cards_html,
        meal_data_json=meal_json,
        maps_script=maps_script if "map" in visible else "",
        guardrail=escape(
            so.get("guardrail")
            or (
                "This report was generated by an AI health assistant for information only. "
                "It is not medical advice. If you feel unwell, contact a clinician or emergency services."
            )
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
            "html": html,
            "detail": so,
            "escalations": escalation_records,
        },
    }

    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
