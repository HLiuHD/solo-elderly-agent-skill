#!/usr/bin/env python3
"""
post_llm script for doctor-report skill.

Reads {"payload": {...}, "llm_result": {...}} from stdin.
Renders a doctor-facing triage HTML report from a template + LLM structured data.
Writes JSON to stdout with updated structured_output.html.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "report.html"

_STATUS_MAP = {
    "stable": ("bg-emerald-100 text-emerald-700", "✅", "稳定"),
    "at_risk": ("bg-amber-100 text-amber-700", "⚠️", "关注"),
    "critical": ("bg-rose-100 text-rose-700", "🚨", "危急"),
}

_TRIAGE_MAP = {
    "emergency": ("bg-rose-50 text-rose-700 border-rose-400", "🚨", "紧急"),
    "urgent": ("bg-amber-50 text-amber-700 border-amber-400", "⚠️", "较急"),
    "semi_urgent": ("bg-yellow-50 text-yellow-700 border-yellow-400", "📋", "次急"),
    "non_urgent": ("bg-emerald-50 text-emerald-700 border-emerald-400", "✅", "非急"),
}

_VITAL_DEFS = [
    ("blood_pressure", "血压", "mmHg"),
    ("heart_rate", "心率", "bpm"),
    ("blood_oxygen", "血氧", "%"),
    ("blood_glucose", "血糖", "mmol/L"),
    ("steps", "步数", "步"),
]


def _render_vitals(vitals: dict) -> str:
    parts = []
    for key, label, unit in _VITAL_DEFS:
        val = vitals.get(key)
        if val is not None and val != "":
            parts.append(
                f'<div class="bg-slate-50 rounded-lg p-3 text-center border border-slate-100">'
                f'<div class="text-[11px] text-slate-500 font-medium mb-1">{label}</div>'
                f'<div class="text-xl font-bold text-slate-800">{val} '
                f'<span class="text-[10px] font-normal text-slate-400">{unit}</span></div>'
                f'</div>'
            )
        else:
            parts.append(
                f'<div class="bg-slate-50 rounded-lg p-3 text-center border border-slate-100">'
                f'<div class="text-[11px] text-slate-500 font-medium mb-1">{label}</div>'
                f'<div class="text-base text-slate-300">--</div>'
                f'</div>'
            )
    return "\n".join(parts)


def _render_anomaly_tags(anomalies: list[str]) -> str:
    if not anomalies:
        return (
            '<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
            'bg-blue-50 text-blue-600">无异常</span>'
        )
    return "\n".join(
        f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
        f'bg-rose-50 text-rose-700">{a}</span>'
        for a in anomalies
    )


def _render_risk_tags(tags: list[str]) -> str:
    if not tags:
        return (
            '<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
            'bg-emerald-50 text-emerald-700">低风险</span>'
        )
    return "\n".join(
        f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
        f'bg-orange-50 text-orange-700">{t}</span>'
        for t in tags
    )


def _render_reasoning(reasoning: str) -> str:
    if not reasoning:
        return ""
    return (
        '<div class="mt-4">'
        '<div class="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">评估依据</div>'
        f'<div class="text-sm text-slate-700 bg-amber-50 rounded-lg p-3" '
        f'style="border-left:3px solid #f59e0b">{reasoning}</div>'
        '</div>'
    )


def _render_doctor_message(msg: str) -> str:
    if not msg:
        return ""
    return (
        '<div class="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">给医生</div>'
        f'<div class="text-sm text-slate-700 bg-amber-50 rounded-lg p-3 mb-3" '
        f'style="border-left:3px solid #f59e0b">{msg}</div>'
    )


def _render_recommendations(recs: list[str]) -> str:
    if not recs:
        return ""
    html = '<div class="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">具体建议</div>'
    for r in recs:
        html += (
            f'<div class="text-sm text-slate-700 bg-blue-50 rounded-lg p-3 mb-2" '
            f'style="border-left:3px solid #3b82f6">{r}</div>'
        )
    return html


def _render_nutrition_summary(ns: dict) -> str:
    if not ns:
        return ""
    conditions = ns.get("conditions_addressed") or []
    principles = ns.get("diet_principles") or []
    note = ns.get("plan_note") or ""

    inner = (
        '<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5 mb-3">'
        '<div class="flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">'
        '<span class="text-lg">🥗</span>'
        '<h2 class="text-sm font-bold text-slate-800">营养方案摘要</h2>'
        '</div>'
    )
    if conditions:
        inner += '<div class="flex flex-wrap gap-2 mb-3">'
        for c in conditions:
            inner += (
                f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
                f'bg-emerald-50 text-emerald-700">{c}</span>'
            )
        inner += '</div>'
    if principles:
        for p in principles:
            inner += f'<div class="text-sm text-slate-600 mb-1">• {p}</div>'
    if note:
        inner += (
            f'<div class="text-sm text-slate-700 bg-blue-50 rounded-lg p-3 mt-3" '
            f'style="border-left:3px solid #3b82f6">{note}</div>'
        )
    inner += '</div>'
    return inner


def _render_adherence(adh: dict) -> str:
    statuses = adh.get("statuses") or []
    suggestions = adh.get("suggestions") or []
    preferences = adh.get("preferences") or []
    if not statuses and not suggestions and not preferences:
        return ""

    inner = (
        '<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5 mb-3">'
        '<div class="flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">'
        '<span class="text-lg">💊</span>'
        '<h2 class="text-sm font-bold text-slate-800">依从性分析</h2>'
        '</div>'
    )
    if statuses:
        inner += (
            '<div class="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">当前状态</div>'
            '<div class="flex flex-wrap gap-2 mb-3">'
        )
        for s in statuses:
            inner += (
                f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
                f'bg-purple-50 text-purple-700">{s}</span>'
            )
        inner += '</div>'
    if preferences:
        inner += (
            '<div class="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">偏好</div>'
            '<div class="flex flex-wrap gap-2 mb-3">'
        )
        for p in preferences:
            inner += (
                f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
                f'bg-blue-50 text-blue-600">{p}</span>'
            )
        inner += '</div>'
    if suggestions:
        inner += '<div class="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">建议</div>'
        for s in suggestions:
            inner += (
                f'<div class="text-sm text-slate-700 bg-indigo-50 rounded-lg p-3 mb-2" '
                f'style="border-left:3px solid #6366f1">{s}</div>'
            )
    inner += '</div>'
    return inner


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to parse input: {exc}", file=sys.stderr)
        sys.exit(1)

    payload = data.get("payload") or {}
    llm = data.get("llm_result") or {}
    so = llm.get("structured_output") or {}

    try:
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Template not found: {_TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)

    meta = payload.get("meta") or {}
    memory = payload.get("memory") or {}
    signals = payload.get("signals") or {}
    location = payload.get("location") or {}

    status = so.get("patient_status") or "stable"
    s_class, s_icon, s_text = _STATUS_MAP.get(status, _STATUS_MAP["stable"])

    triage = so.get("triage_level") or "non_urgent"
    t_class, t_icon, t_text = _TRIAGE_MAP.get(triage, _TRIAGE_MAP["non_urgent"])

    current_time = meta.get("current_time") or datetime.now().strftime("%Y-%m-%d %H:%M")

    sig_summary = so.get("signals_summary") or {}
    if sig_summary.get("window"):
        signal_window = sig_summary["window"]
    elif signals.get("start_ts") and signals.get("end_ts"):
        signal_window = f'{signals["start_ts"]}  ⟶  {signals["end_ts"]}'
    else:
        signal_window = "暂无数据"

    anomalies = sig_summary.get("anomalies") or signals.get("anomalies") or []
    signal_summary_text = sig_summary.get("description") or signals.get("summary_text") or "暂无数据"

    loc = location.get("current") or {}
    patient_lat = loc.get("lat", 0)
    patient_lon = loc.get("lon", 0)

    if status == "critical":
        ai_map_msg = "检测到潜在风险，已为您查询患者附近的医疗网点，请建议患者及时就医。"
    elif any(kw in t for t in so.get("risk_tags", []) for kw in ("活动", "偏低")):
        ai_map_msg = "患者近期活动量偏低，以下是附近推荐的公园和医疗网点，可建议患者适当外出活动。"
    else:
        ai_map_msg = "已为您查询患者附近的医疗网点和活动场所，方便后续随访参考。"

    html = template.format(
        user_id=meta.get("user_id", "未知"),
        current_time=current_time,
        status_class=s_class,
        status_icon=s_icon,
        status_text=s_text,
        long_term_profile=memory.get("patient_long_term_profile", "暂无数据"),
        recent_dynamics=memory.get("recent_health_dynamics", "暂无数据"),
        signal_window=signal_window,
        anomaly_tags=_render_anomaly_tags(anomalies),
        signal_summary=signal_summary_text,
        vitals_html=_render_vitals(so.get("latest_vitals") or {}),
        triage_class=t_class,
        triage_icon=t_icon,
        triage_text=t_text,
        risk_tags_html=_render_risk_tags(so.get("risk_tags") or []),
        reasoning_html=_render_reasoning(so.get("reasoning") or ""),
        doctor_message_html=_render_doctor_message(so.get("assistant_message_doctor") or ""),
        recommendations_html=_render_recommendations(so.get("recommendations") or []),
        nutrition_summary_html=_render_nutrition_summary(so.get("nutrition_plan_summary") or {}),
        adherence_html=_render_adherence(so.get("adherence_analysis") or {}),
        ai_map_message=ai_map_msg,
        patient_lat=str(patient_lat) if patient_lat else "0",
        patient_lon=str(patient_lon) if patient_lon else "0",
        guardrail=so.get("guardrail") or "本报告由 AI 健康助手自动生成，仅供临床参考，不构成医疗诊断。",
    )

    result = {
        "structured_output": {
            "html": html,
            "detail": so,
        },
    }

    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
