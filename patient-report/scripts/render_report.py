#!/usr/bin/env python3
"""
post_llm script for patient-report skill.

Reads {"payload": {...}, "llm_result": {...}} from stdin.
Renders a patient-facing HTML health report from a template + LLM structured data.
Writes JSON to stdout with updated structured_output.html.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "report.html"

_STATUS_MAP = {
    "stable": ("bg-emerald-100 text-emerald-800", "✅", "身体状态良好"),
    "at_risk": ("bg-amber-100 text-amber-800", "⚠️", "需要关注"),
    "critical": ("bg-rose-100 text-rose-800", "🚨", "请及时就医"),
}

_COND_COLORS = {
    "高血压": "bg-rose-500",
    "2型糖尿病": "bg-amber-500",
    "糖尿病": "bg-amber-500",
    "高脂血症": "bg-orange-500",
    "冠心病": "bg-red-500",
    "化疗期间": "bg-purple-500",
}

_RISK_TAG_COLORS = {
    "心率": "bg-rose-50 text-rose-700 border-rose-200",
    "血压": "bg-rose-50 text-rose-700 border-rose-200",
    "血糖": "bg-amber-50 text-amber-700 border-amber-200",
    "活动": "bg-sky-50 text-sky-700 border-sky-200",
    "偏低": "bg-amber-50 text-amber-700 border-amber-200",
    "偏高": "bg-rose-50 text-rose-700 border-rose-200",
    "异常": "bg-orange-50 text-orange-700 border-orange-200",
}

_VITAL_DEFS = [
    ("blood_pressure", "血压", "mmHg", "💓"),
    ("heart_rate", "心率", "bpm", "❤️"),
    ("blood_oxygen", "血氧", "%", "🫁"),
    ("blood_glucose", "血糖", "mmol/L", "🩸"),
    ("steps_today", "步数", "步", "🚶"),
]

_REC_ICONS = ["💊", "🚶", "🫀", "🩸", "🧈", "🥗", "🧘", "💤"]


def _render_vitals(summary: dict) -> str:
    parts = []
    for key, label, unit, icon in _VITAL_DEFS:
        val = summary.get(key)
        if val is not None and val != "":
            parts.append(
                f'<div class="bg-slate-50 rounded-lg p-3 text-center border border-slate-100">'
                f'<div class="text-lg mb-0.5">{icon}</div>'
                f'<div class="text-[11px] text-slate-500 font-medium mb-1">{label}</div>'
                f'<div class="text-xl font-bold text-slate-800">{val}</div>'
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
            f'rounded-full text-xs font-semibold">{c}</span>'
        )
    return "\n".join(parts)


def _render_risk_tags(tags: list[str]) -> str:
    if not tags:
        return (
            '<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
            'border bg-emerald-50 text-emerald-700 border-emerald-200">暂无风险</span>'
        )
    parts = []
    for tag in tags:
        cls = "bg-slate-50 text-slate-600 border-slate-200"
        for kw, c in _RISK_TAG_COLORS.items():
            if kw in tag:
                cls = c
                break
        parts.append(
            f'<span class="inline-block px-3 py-1 rounded-full text-xs '
            f'font-medium border {cls}">{tag}</span>'
        )
    return "\n".join(parts)


def _render_recommendations(recs: list[str]) -> str:
    if not recs:
        return '<div class="text-sm text-slate-400">暂无具体建议</div>'
    parts = []
    for i, r in enumerate(recs):
        icon = _REC_ICONS[i % len(_REC_ICONS)]
        parts.append(
            f'<div class="flex items-start gap-3 bg-emerald-50 rounded-lg p-3 '
            f'border border-emerald-100">'
            f'<span class="text-base mt-0.5">{icon}</span>'
            f'<div class="text-sm text-slate-700 leading-relaxed">{r}</div>'
            f'</div>'
        )
    return "\n".join(parts)


def _render_reasoning(reasoning: str) -> str:
    if not reasoning:
        return ""
    return (
        '<div class="mt-4 pt-3 border-t border-slate-100">'
        '<div class="text-[11px] text-slate-400 uppercase tracking-wide font-medium mb-1.5">评估依据</div>'
        f'<div class="text-xs text-slate-600 bg-slate-50 rounded-lg p-3 leading-relaxed">{reasoning}</div>'
        '</div>'
    )


def _render_adherence(adh: dict) -> str:
    statuses = adh.get("statuses") or []
    preferences = adh.get("preferences") or []
    suggestions = adh.get("suggestions") or []
    if not statuses and not preferences and not suggestions:
        return ""

    inner = (
        '<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5 mb-3">'
        '<div class="flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">'
        '<span class="text-lg">💊</span>'
        '<h2 class="text-sm font-bold text-slate-800">用药与依从性</h2>'
        '</div>'
    )
    if statuses:
        inner += '<div class="flex flex-wrap gap-2 mb-3">'
        for s in statuses:
            inner += (
                f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
                f'bg-emerald-50 text-emerald-700 border border-emerald-200">{s}</span>'
            )
        inner += '</div>'
    if preferences:
        inner += '<div class="flex flex-wrap gap-2 mb-3">'
        for p in preferences:
            inner += (
                f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
                f'bg-blue-50 text-blue-600 border border-blue-200">{p}</span>'
            )
        inner += '</div>'
    if suggestions:
        for s in suggestions:
            inner += (
                f'<div class="flex items-start gap-3 bg-indigo-50 rounded-lg p-3 '
                f'border border-indigo-100 mb-2">'
                f'<span class="text-base mt-0.5">📋</span>'
                f'<div class="text-sm text-slate-700 leading-relaxed">{s}</div>'
                f'</div>'
            )
    inner += '</div>'
    return inner


def _render_diet_table(diet_table: list[dict]) -> str:
    if not diet_table:
        return ""
    rows = ""
    for item in diet_table:
        rows += (
            f'<tr>'
            f'<td class="px-4 py-3 font-medium text-slate-800">{item.get("condition", "")}</td>'
            f'<td class="px-4 py-3 text-slate-600">{item.get("principle", "")}</td>'
            f'<td class="px-4 py-3 text-emerald-700">{item.get("recommend", "")}</td>'
            f'<td class="px-4 py-3 text-rose-600">{item.get("avoid", "")}</td>'
            f'</tr>'
        )
    return (
        '<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5 mb-3">'
        '<div class="flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">'
        '<span class="text-lg">📋</span>'
        '<h2 class="text-sm font-bold text-slate-800">疾病饮食对照表</h2>'
        '</div>'
        '<div class="overflow-x-auto">'
        '<table class="w-full text-sm">'
        '<thead><tr class="bg-slate-50">'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">疾病</th>'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">原则</th>'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">推荐</th>'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">避免</th>'
        '</tr></thead>'
        f'<tbody class="divide-y divide-slate-100">{rows}</tbody>'
        '</table></div></div>'
    )


def _render_diet_tips(tips: list[dict]) -> str:
    if not tips:
        return ""
    inner = ""
    for tip in tips:
        inner += (
            f'<div class="bg-slate-50 rounded-lg p-3 border border-slate-100">'
            f'<div class="flex items-center gap-2 mb-1">'
            f'<span class="text-base">{tip.get("icon", "💡")}</span>'
            f'<span class="text-xs font-semibold text-slate-700">{tip.get("title", "")}</span>'
            f'</div>'
            f'<div class="text-xs text-slate-600 leading-relaxed">{tip.get("detail", "")}</div>'
            f'</div>'
        )
    return (
        '<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5 mb-3">'
        '<div class="flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">'
        '<span class="text-lg">✨</span>'
        '<h2 class="text-sm font-bold text-slate-800">饮食小贴士</h2>'
        '</div>'
        f'<div class="grid grid-cols-2 gap-2">{inner}</div>'
        '</div>'
    )


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

    patient_name = so.get("patient_name") or "您"
    status = so.get("patient_status") or "stable"
    badge_class, status_icon, status_text = _STATUS_MAP.get(status, _STATUS_MAP["stable"])

    meta = payload.get("meta") or {}
    current_time = meta.get("current_time") or datetime.now().strftime("%Y-%m-%d %H:%M")
    if "T" in str(current_time):
        try:
            dt = datetime.fromisoformat(str(current_time).replace("Z", "+00:00"))
            current_time = dt.strftime("%Y年%m月%d日 %H:%M")
        except (ValueError, TypeError):
            pass

    conditions = so.get("conditions") or []
    location = payload.get("location") or {}
    loc = location.get("current") or {}
    patient_lat = loc.get("lat", 0)
    patient_lon = loc.get("lon", 0)

    if status == "critical":
        ai_map_msg = "检测到健康异常，已为您查询附近的医疗机构，如有不适请及时就医。"
    elif any(kw in t for t in so.get("risk_tags", []) for kw in ("活动", "偏低")):
        ai_map_msg = "您近期活动量偏低哦，天气不错的话可以去附近的公园散散步！"
    else:
        ai_map_msg = "这是您附近的医院和公园，有需要时可以参考。"

    meal_json = json.dumps(so.get("weekly_meal_plan") or [], ensure_ascii=False)

    html = template.format(
        patient_name=patient_name,
        current_time=current_time,
        status_badge_class=badge_class,
        status_icon=status_icon,
        status_text=status_text,
        condition_badges=_render_condition_badges(conditions),
        ai_message=so.get("assistant_message_patient") or "",
        vitals_html=_render_vitals(so.get("latest_health_summary") or {}),
        risk_tags_html=_render_risk_tags(so.get("risk_tags") or []),
        recommendations_html=_render_recommendations(so.get("recommendations") or []),
        reasoning_html=_render_reasoning(so.get("reasoning") or ""),
        adherence_html=_render_adherence(so.get("adherence") or {}),
        nutrition_advice=so.get("nutrition_advice") or "保持均衡饮食，多食新鲜蔬菜水果。",
        diet_table_html=_render_diet_table(so.get("diet_table") or []),
        diet_tips_html=_render_diet_tips(so.get("diet_tips") or []),
        meal_data_json=meal_json,
        ai_map_message=ai_map_msg,
        patient_lat=str(patient_lat) if patient_lat else "0",
        patient_lon=str(patient_lon) if patient_lon else "0",
        guardrail=so.get("guardrail") or "本报告由 AI 健康助手生成，仅供参考。如有不适请及时就医，遵医嘱为准。",
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
