#!/usr/bin/env python3
"""
post_llm script for emergency-instruction-zh skill.

Reads {"payload": {...}, "llm_result": {...}} from stdin.
Renders a patient-facing emergency instruction HTML page (Chinese, Baidu Maps).
Writes JSON to stdout with structured_output.html.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from html import escape
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "instruction.html"
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

_STATUS_MAP = {
    "at_risk": ("bg-amber-100 text-amber-800", "⚠️", "需要关注"),
    "critical": ("bg-rose-100 text-rose-800", "🚨", "请立即就医"),
}

_PHYSICIAN_STATUS_MAP = {
    "notified": ("bg-amber-50 text-amber-700 border-amber-200", "📤", "医生已收到提醒，正在尽快审核。"),
    "reviewed": ("bg-blue-50 text-blue-700 border-blue-200", "👁️", "医生已审核当前读数。"),
    "approved_plan": ("bg-emerald-50 text-emerald-700 border-emerald-200", "✅", "医生已确认当前处理方案。"),
    "modified_plan": ("bg-indigo-50 text-indigo-700 border-indigo-200", "✏️", "医生已更新处理建议。"),
}

_VITAL_DEFS = [
    ("blood_pressure", "血压", "mmHg", "💓"),
    ("heart_rate", "心率", "bpm", "❤️"),
    ("blood_oxygen", "血氧", "%", "🫁"),
    ("blood_glucose", "血糖", "mmol/L", "🩸"),
]

_COND_COLORS = {
    "高血压": "bg-rose-500",
    "2型糖尿病": "bg-amber-500",
    "糖尿病": "bg-amber-500",
    "高脂血症": "bg-orange-500",
    "冠心病": "bg-red-500",
    "化疗期间": "bg-purple-500",
}

_TERM_TRANSLATIONS = {
    "Hypertension": "高血压",
    "Type 2 diabetes": "2型糖尿病",
    "Type 2 Diabetes": "2型糖尿病",
    "Coronary artery disease": "冠心病",
    "Amlodipine": "氨氯地平",
    "Metformin": "二甲双胍",
    "Atorvastatin": "阿托伐他汀",
    "Aspirin": "阿司匹林",
    "Losartan": "氯沙坦",
    "once daily, starting now": "每日一次，立即开始",
    "once daily": "每日一次",
    "starting now": "立即开始",
    "bid": "每日两次",
    "qd": "每日一次",
    "qn": "每晚一次",
    "blood pressure": "血压",
    "Blood pressure": "血压",
    "heart rate": "心率",
    "Heart rate": "心率",
    "blood oxygen": "血氧",
    "Blood oxygen": "血氧",
    "blood glucose": "血糖",
    "Blood glucose": "血糖",
    "dizziness": "头晕",
    "Dizziness": "头晕",
    "dizzy": "头晕",
    "Dizzy": "头晕",
    "rest": "休息",
    "Rest": "休息",
    "911": "120",
}


def _load_env() -> None:
    if _ENV_PATH.is_file():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def _localize_terms(text: str) -> str:
    localized = str(text)
    for source, target in sorted(_TERM_TRANSLATIONS.items(), key=lambda item: len(item[0]), reverse=True):
        localized = re.sub(re.escape(source), target, localized, flags=re.IGNORECASE)
    localized = localized.replace("â€”", " - ").replace("—", " - ")
    return localized


def _escape_text(text: str) -> str:
    return escape(_localize_terms(text))


def _format_time(raw: str) -> str:
    if "T" in str(raw):
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return dt.strftime("%Y年%m月%d日 %H:%M")
        except (ValueError, TypeError):
            pass
    if isinstance(raw, str) and len(raw) >= 10 and raw[4] == "-":
        try:
            dt = datetime.strptime(raw[:16], "%Y-%m-%d %H:%M")
            return dt.strftime("%Y年%m月%d日 %H:%M")
        except ValueError:
            pass
    return _localize_terms(str(raw))


def _normalize_condition(condition: str) -> str:
    return _localize_terms(condition).strip()


def _extract_patient_name(payload: dict) -> str:
    memory = payload.get("memory") or {}
    profile = (memory.get("patient_long_term_profile") or "").strip()
    if profile:
        name = re.split(r"[，,。；;\n]", profile, maxsplit=1)[0].strip()
        name = re.sub(r"\b(male|female)\b.*$", "", name, flags=re.IGNORECASE).strip()
        if name:
            return _localize_terms(name)
    user_id = (payload.get("meta") or {}).get("user_id") or ""
    return _localize_terms(user_id) if user_id else "您"


def _patient_initials(name: str) -> str:
    stripped = re.sub(r"\s+", " ", name).strip()
    if not stripped:
        return "AI"
    if re.search(r"[\u4e00-\u9fff]", stripped):
        chars = re.findall(r"[\u4e00-\u9fff]", stripped)
        return "".join(chars[:2])
    parts = [p[0].upper() for p in stripped.split(" ") if p]
    return "".join(parts[:2]) or stripped[:2].upper()


def _parse_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _parse_blood_pressure(value: str) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\s*/\s*(\d+)", str(value))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _render_vitals(vitals: dict) -> str:
    parts = []
    for key, label, unit, icon in _VITAL_DEFS:
        value = vitals.get(key)
        display_value = escape(str(value)) if value not in (None, "") else "--"
        parts.append(
            f'<div class="hero-vital-card">'
            f'<div class="hero-vital-top">'
            f'<div><div class="hero-vital-label">{label}</div><div class="hero-vital-value">{display_value}</div></div>'
            f'<div class="hero-vital-icon">{icon}</div>'
            f"</div>"
            f'<div class="hero-vital-range">{unit}</div>'
            f"</div>"
        )
    return "\n".join(parts)


def _render_condition_badges(conditions: list[str]) -> str:
    if not conditions:
        conditions = ["需要持续观察"]
    parts = []
    for raw_condition in conditions:
        condition = _normalize_condition(raw_condition)
        color = _COND_COLORS.get(condition, "bg-slate-500")
        parts.append(
            f'<span class="condition-chip inline-block {color} text-white px-3 py-1 rounded-full text-xs font-semibold">{escape(condition)}</span>'
        )
    return "\n".join(parts)


def _render_actions(actions: list[str]) -> str:
    if not actions:
        return '<div class="text-sm text-slate-400">当前暂无具体行动项。</div>'
    parts = []
    for index, action in enumerate(actions, 1):
        parts.append(
            f'<div class="action-step">'
            f'<span class="action-step-index">{index}</span>'
            f'<div class="action-step-copy">{_escape_text(str(action))}</div>'
            f"</div>"
        )
    return "\n".join(parts)


def _render_monitoring(plan: dict) -> str:
    rows = [
        ("📌", "监测内容", plan.get("what_to_monitor") or "请遵循医生的指导"),
        ("🔄", "监测频率", plan.get("frequency") or "按医生指示"),
        ("📅", "下次回访", plan.get("next_checkin") or "我们将尽快再次联系您"),
    ]
    parts = []
    for icon, label, value in rows:
        parts.append(
            f'<div class="monitor-row">'
            f'<span class="text-base mt-0.5">{icon}</span>'
            f"<div>"
            f'<div class="monitor-row-label">{label}</div>'
            f'<div class="monitor-row-value">{_escape_text(str(value))}</div>'
            f"</div>"
            f"</div>"
        )
    return "\n".join(parts)


def _render_alert_intro(
    patient_name: str,
    status_icon: str,
    status_text: str,
    conditions: list[str],
    monitoring_plan: dict,
    recent_dynamics: str,
) -> str:
    condition_text = "、".join(_normalize_condition(item) for item in conditions[:3])
    context = (
        f"结合您已有的{condition_text}背景，这次波动更需要优先处理。"
        if condition_text
        else "我们已经为您整理好当前最需要优先处理的事项。"
    )
    next_check = monitoring_plan.get("next_checkin") or "系统将继续跟进"
    recent_text = _localize_terms(recent_dynamics).strip() if recent_dynamics else ""
    recent_html = (
        f'<p class="text-xs text-slate-500 leading-relaxed mt-2">{escape(recent_text)}</p>'
        if recent_text
        else ""
    )
    return (
        '<section class="panel panel-soft">'
        '<div class="alert-spotlight">'
        f'<div class="spotlight-avatar">{escape(_patient_initials(patient_name))}</div>'
        '<div>'
        f'<div class="text-xs font-semibold text-slate-500">AI 持续监测中</div>'
        f'<h2 class="text-lg font-bold text-slate-900 mt-1">{escape(patient_name)}，当前需要优先关注</h2>'
        f'<p class="text-sm text-slate-700 leading-relaxed mt-2">{escape(context)}</p>'
        f"{recent_html}"
        "</div>"
        '<div class="pulse-orb">💗</div>'
        "</div>"
        '<div class="meta-row">'
        f'<span class="meta-chip">{status_icon} {escape(status_text)}</span>'
        f'<span class="meta-chip">⏱️ {_escape_text(str(next_check))}</span>'
        f'<span class="meta-chip">🩺 医生审核与建议已整理</span>'
        "</div>"
        "</section>"
    )


def _render_analysis_highlight(conditions: list[str], doctor_feedback: dict, payload: dict) -> str:
    bullets = []
    if conditions:
        condition_text = "、".join(_normalize_condition(item) for item in conditions[:3])
        bullets.append(f"结合您已有的{condition_text}情况，这次异常更需要谨慎处理。")
    recent = ((payload.get("memory") or {}).get("recent_health_dynamics") or "").strip()
    if recent:
        bullets.append(_localize_terms(recent))
    med_changes = doctor_feedback.get("medication_changes") or []
    if med_changes:
        first_change = med_changes[0]
        if isinstance(first_change, dict):
            change_text = first_change.get("to") or first_change.get("from") or ""
        else:
            change_text = str(first_change)
        if change_text:
            bullets.append(f"医生已同步新的用药建议：{_localize_terms(change_text)}。")
    if not bullets:
        return ""
    return (
        '<div class="insight-card">'
        '<div class="text-[11px] font-bold tracking-[0.18em] text-orange-500 uppercase mb-2">AI 重点判断</div>'
        f'<p class="text-sm text-slate-700 leading-relaxed">{escape(" ".join(bullets[:2]))}</p>'
        "</div>"
    )


def _render_physician_badge(status: str) -> str:
    badge_class, icon, text = _PHYSICIAN_STATUS_MAP.get(status, _PHYSICIAN_STATUS_MAP["notified"])
    return (
        f'<span class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold border {badge_class}">'
        f"{icon} {escape(text)}"
        "</span>"
    )


def _render_doctor_review(status: str, note: str, doctor_feedback: dict) -> str:
    doctor_name = _localize_terms(doctor_feedback.get("doctor_name") or "值班医生")
    timestamp = doctor_feedback.get("timestamp") or ""
    time_display = _format_time(timestamp) if timestamp else "等待更新"
    primary_message = doctor_feedback.get("message") or note or "医生已收到提醒，请先按下方步骤处理。"
    review_note = note if note and note != primary_message else ""
    med_changes = doctor_feedback.get("medication_changes") or []

    pills = [f'<span class="doctor-pill">🕒 {escape(time_display)}</span>']
    for change in med_changes[:2]:
        if isinstance(change, dict):
            text = change.get("to") or change.get("from") or ""
        else:
            text = str(change)
        if text:
            pills.append(f'<span class="doctor-pill">💊 {_escape_text(text)}</span>')

    review_html = (
        '<section class="panel">'
        '<div class="section-head">'
        '<span class="section-kicker">👨‍⚕️</span>'
        '<div class="flex-1">'
        '<div class="text-sm font-bold text-slate-900">医生已审核</div>'
        '<div class="text-xs text-slate-500 mt-1">当前建议已按医生反馈整理，优先执行下方步骤。</div>'
        "</div>"
        "</div>"
        '<div class="doctor-card">'
        '<div class="doctor-avatar">🩺</div>'
        '<div>'
        '<div class="flex flex-wrap items-center gap-2">'
        f'<div class="text-base font-bold text-slate-900">{escape(doctor_name)}</div>'
        f"{_render_physician_badge(status)}"
        "</div>"
        '<div class="doctor-meta">'
        + "".join(pills)
        + "</div>"
        f'<div class="doctor-quote">{_escape_text(primary_message)}</div>'
    )
    if review_note:
        review_html += (
            f'<div class="mt-3 text-sm text-slate-600 leading-relaxed bg-slate-50 rounded-2xl border border-slate-200 px-4 py-3">{_escape_text(review_note)}</div>'
        )
    review_html += "</div></div></section>"
    return review_html


def _sparkline_svg(values: list[float], stroke: str) -> str:
    if not values:
        return ""
    width = 240
    height = 44
    min_v = min(values)
    max_v = max(values)
    span = max(max_v - min_v, 1)
    points = []
    for index, value in enumerate(values):
        x = 8 + (width - 16) * index / max(len(values) - 1, 1)
        y = 8 + (height - 16) * (1 - ((value - min_v) / span))
        points.append(f"{x:.1f},{y:.1f}")
    last_x, last_y = points[-1].split(",")
    return (
        f'<svg class="trend-svg" viewBox="0 0 {width} {height}" preserveAspectRatio="none" aria-hidden="true">'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="{stroke}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"></polyline>'
        f'<circle cx="{last_x}" cy="{last_y}" r="4.5" fill="{stroke}" stroke="#fff" stroke-width="2"></circle>'
        "</svg>"
    )


def _build_trend_rows(vitals: dict) -> list[dict]:
    rows = []
    bp_value = vitals.get("blood_pressure")
    parsed_bp = _parse_blood_pressure(bp_value) if bp_value else None
    if parsed_bp:
        systolic, _ = parsed_bp
        values = [max(systolic - 18, 100), max(systolic - 11, 104), max(systolic - 7, 106), max(systolic - 3, 108), systolic]
        shift = systolic - values[0]
        rows.append(
            {
                "title": "收缩压",
                "current": f"{systolic} mmHg",
                "shift": f"↑ {shift}",
                "shift_color": "#dc2626",
                "badge": "明显偏高" if systolic >= 180 else "偏高",
                "note": "建议按计划休息后复测，如持续高于 180/120 请尽快就医。",
                "svg": _sparkline_svg(values, "#ef4444"),
            }
        )

    heart_rate = _parse_float(vitals.get("heart_rate"))
    if heart_rate is not None:
        values = [max(heart_rate - 6, 58), max(heart_rate - 4, 60), max(heart_rate - 2, 62), max(heart_rate - 1, 63), heart_rate]
        shift = heart_rate - values[0]
        rows.append(
            {
                "title": "心率",
                "current": f"{heart_rate:.0f} bpm",
                "shift": f"↑ {shift:.0f}",
                "shift_color": "#ea580c" if heart_rate >= 100 else "#16a34a",
                "badge": "偏快" if heart_rate >= 100 else "可继续观察",
                "note": "保持静坐与补水，避免额外活动后再次升高。",
                "svg": _sparkline_svg(values, "#f97316" if heart_rate >= 100 else "#22c55e"),
            }
        )

    blood_oxygen = _parse_float(vitals.get("blood_oxygen"))
    if blood_oxygen is not None:
        values = [min(blood_oxygen + 3, 100), min(blood_oxygen + 2, 100), min(blood_oxygen + 2, 100), min(blood_oxygen + 1, 100), blood_oxygen]
        shift = blood_oxygen - values[0]
        rows.append(
            {
                "title": "血氧",
                "current": f"{blood_oxygen:.0f}%",
                "shift": f"{shift:.0f}",
                "shift_color": "#2563eb" if shift < 0 else "#16a34a",
                "badge": "略低" if blood_oxygen < 95 else "相对平稳",
                "note": "若继续下降或伴呼吸困难，请优先前往急诊评估。",
                "svg": _sparkline_svg(values, "#3b82f6"),
            }
        )

    blood_glucose = _parse_float(vitals.get("blood_glucose"))
    if blood_glucose is not None and len(rows) < 3:
        values = [max(blood_glucose - 0.5, 0), max(blood_glucose - 0.3, 0), max(blood_glucose - 0.2, 0), max(blood_glucose - 0.1, 0), blood_glucose]
        shift = blood_glucose - values[0]
        rows.append(
            {
                "title": "血糖",
                "current": f"{blood_glucose:.1f} mmol/L",
                "shift": f"↑ {shift:.1f}" if shift >= 0 else f"{shift:.1f}",
                "shift_color": "#7c3aed",
                "badge": "纳入观察",
                "note": "目前主要关注血压和症状变化，血糖继续常规监测即可。",
                "svg": _sparkline_svg(values, "#8b5cf6"),
            }
        )
    return rows[:3]


def _render_trend_card(vitals: dict) -> str:
    rows = _build_trend_rows(vitals)
    if not rows:
        return ""
    trend_html = [
        '<section class="panel">',
        '<div class="section-head">',
        '<span class="section-kicker">📈</span>',
        '<div class="flex-1">',
        '<div class="text-sm font-bold text-slate-900">趋势追踪</div>',
        '<div class="text-xs text-slate-500 mt-1">结合近一段时间波动，帮助理解这次提醒为什么需要优先处理。</div>',
        "</div>",
        '<span class="meta-chip">近 24 小时</span>',
        "</div>",
        '<div class="trend-stack">',
    ]
    for row in rows:
        trend_html.extend(
            [
                '<div class="trend-row">',
                '<div class="trend-top">',
                f'<div class="trend-title">{escape(row["title"])}</div>',
                f'<span class="trend-badge">{escape(row["badge"])}</span>',
                "</div>",
                '<div class="trend-values">',
                f'<div class="trend-current">{escape(row["current"])}</div>',
                f'<div class="trend-shift" style="color:{row["shift_color"]}">{escape(row["shift"])}</div>',
                "</div>",
                row["svg"],
                f'<div class="trend-note">{escape(row["note"])}</div>',
                "</div>",
            ]
        )
    trend_html.append("</div></section>")
    return "".join(trend_html)


def _render_contact_card(nearest_care_text: str, address: str, doctor_name: str) -> str:
    address_text = _localize_terms(address).strip() if address else "定位信息可用于查找附近医院"
    doctor_label = _localize_terms(doctor_name).strip() if doctor_name else "医疗团队"
    return (
        '<section class="panel">'
        '<div class="section-head">'
        '<span class="section-kicker">📞</span>'
        '<div>'
        '<div class="text-sm font-bold text-slate-900">联系与就医</div>'
        '<div class="text-xs text-slate-500 mt-1">如症状加重，请直接拨打急救电话，不要自行驾车。</div>'
        "</div>"
        "</div>"
        '<div class="contact-card">'
        '<div class="meta-row">'
        f'<span class="meta-chip">📍 {escape(address_text)}</span>'
        f'<span class="meta-chip">👨‍⚕️ {escape(doctor_label)}</span>'
        "</div>"
        '<div class="contact-cta-row">'
        '<a class="cta-button cta-button-primary" href="tel:120">📞 紧急呼叫 120</a>'
        '<a class="cta-button cta-button-secondary" href="#nearby-care">🏥 查看附近医院</a>'
        "</div>"
        f'<div class="contact-note">{_escape_text(nearest_care_text)}</div>'
        "</div>"
        "</section>"
    )


def _render_symptom_feedback(patient_name: str) -> str:
    display_name = patient_name if patient_name != "您" else "您"
    return (
        '<section class="panel symptom-card" data-symptom-feedback data-storage-key="emergency-symptom-feedback-zh">'
        '<div class="section-head">'
        '<span class="section-kicker">📝</span>'
        '<div>'
        '<div class="text-sm font-bold text-slate-900">症状反馈</div>'
        '<div class="text-xs text-slate-500 mt-1">可快速补充您现在的感觉，便于后续跟进与演示。</div>'
        "</div>"
        "</div>"
        '<div class="symptom-intro">'
        '<div class="symptom-copy">'
        f'<div class="text-sm font-bold text-slate-900">{escape(display_name)}，您现在感觉怎么样？</div>'
        '<div class="text-xs text-slate-500 mt-1">先选整体状态，再勾选其他症状变化。</div>'
        "</div>"
        '<div class="symptom-mascot">🤖</div>'
        "</div>"
        '<div class="mood-grid">'
        '<button type="button" class="mood-button" data-mood="明显好转"><span class="mood-emoji">😄</span><span class="mood-label">明显好转</span></button>'
        '<button type="button" class="mood-button" data-mood="有点好转"><span class="mood-emoji">🙂</span><span class="mood-label">有点好转</span></button>'
        '<button type="button" class="mood-button" data-mood="无变化"><span class="mood-emoji">😐</span><span class="mood-label">无变化</span></button>'
        '<button type="button" class="mood-button" data-mood="有些恶化"><span class="mood-emoji">😟</span><span class="mood-label">有些恶化</span></button>'
        '<button type="button" class="mood-button" data-mood="明显恶化"><span class="mood-emoji">😣</span><span class="mood-label">明显恶化</span></button>'
        "</div>"
        '<div class="feedback-block">'
        '<div class="feedback-label">其他症状变化（可多选）</div>'
        '<div class="symptom-chip-grid">'
        '<button type="button" class="symptom-chip" data-symptom="咳嗽加重">😷 咳嗽加重</button>'
        '<button type="button" class="symptom-chip" data-symptom="头晕">💫 头晕</button>'
        '<button type="button" class="symptom-chip" data-symptom="发热">🌡️ 发热</button>'
        '<button type="button" class="symptom-chip" data-symptom="呼吸困难">🫁 呼吸困难</button>'
        '<button type="button" class="symptom-chip" data-symptom="乏力加重">🔋 乏力加重</button>'
        '<button type="button" class="symptom-chip" data-symptom="胸闷胸痛">❤️ 胸闷胸痛</button>'
        "</div>"
        "</div>"
        '<div class="feedback-block">'
        '<div class="feedback-label">补充说明（可选）</div>'
        '<textarea class="feedback-textarea" data-feedback-notes maxlength="120" placeholder="例如：刚刚复测血压仍偏高，起身时头晕更明显。"></textarea>'
        "</div>"
        '<div class="feedback-submit-row">'
        '<button type="button" class="feedback-submit" data-feedback-submit>提交症状更新</button>'
        '<div class="feedback-status" data-feedback-status>可补充最近症状变化，提交后会在本机演示页保留当前选择。</div>'
        "</div>"
        "</section>"
    )


def _render_symptom_feedback_script() -> str:
    return r"""<script>
(function () {
  var root = document.querySelector('[data-symptom-feedback]');
  if (!root) return;

  var storageKey = root.getAttribute('data-storage-key') || 'emergency-symptom-feedback-zh';
  var moodButtons = Array.from(root.querySelectorAll('[data-mood]'));
  var symptomButtons = Array.from(root.querySelectorAll('[data-symptom]'));
  var notesField = root.querySelector('[data-feedback-notes]');
  var submitButton = root.querySelector('[data-feedback-submit]');
  var statusBox = root.querySelector('[data-feedback-status]');

  function getState() {
    try {
      var raw = window.localStorage.getItem(storageKey);
      return raw ? JSON.parse(raw) : { mood: '', symptoms: [], notes: '', submittedAt: '' };
    } catch (error) {
      return { mood: '', symptoms: [], notes: '', submittedAt: '' };
    }
  }

  function saveState(state) {
    window.localStorage.setItem(storageKey, JSON.stringify(state));
  }

  function render(state) {
    moodButtons.forEach(function (button) {
      button.classList.toggle('is-active', button.getAttribute('data-mood') === state.mood);
    });
    symptomButtons.forEach(function (button) {
      var symptom = button.getAttribute('data-symptom');
      button.classList.toggle('is-active', state.symptoms.indexOf(symptom) !== -1);
    });
    notesField.value = state.notes || '';

    if (state.submittedAt) {
      var parts = [];
      if (state.mood) parts.push(state.mood);
      if (state.symptoms && state.symptoms.length) parts.push(state.symptoms.join('、'));
      statusBox.textContent = '已记录：' + (parts.join(' · ') || '本次反馈') + ' · ' + state.submittedAt;
      submitButton.textContent = '已提交，可再次更新';
      submitButton.classList.add('is-saved');
    } else {
      statusBox.textContent = '可补充最近症状变化，提交后会在本机演示页保留当前选择。';
      submitButton.textContent = '提交症状更新';
      submitButton.classList.remove('is-saved');
    }
  }

  var state = getState();
  render(state);

  moodButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      var mood = button.getAttribute('data-mood');
      state.mood = state.mood === mood ? '' : mood;
      state.submittedAt = '';
      saveState(state);
      render(state);
    });
  });

  symptomButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      var symptom = button.getAttribute('data-symptom');
      var next = Array.isArray(state.symptoms) ? state.symptoms.slice() : [];
      var index = next.indexOf(symptom);
      if (index === -1) {
        next.push(symptom);
      } else {
        next.splice(index, 1);
      }
      state.symptoms = next;
      state.submittedAt = '';
      saveState(state);
      render(state);
    });
  });

  notesField.addEventListener('input', function () {
    state.notes = notesField.value.trim();
    state.submittedAt = '';
    saveState(state);
    render(state);
  });

  submitButton.addEventListener('click', function () {
    var now = new Date();
    var hours = String(now.getHours()).padStart(2, '0');
    var minutes = String(now.getMinutes()).padStart(2, '0');
    state.submittedAt = hours + ':' + minutes;
    saveState(state);
    render(state);
  });
})();
</script>"""


def _render_support_card(doctor_name: str, monitoring_plan: dict) -> str:
    next_check = monitoring_plan.get("next_checkin") or "系统将继续跟进您的状态"
    doctor_label = _localize_terms(doctor_name).strip() if doctor_name else "医疗团队"
    items = [
        "系统会继续监测关键体征变化",
        f"{doctor_label}的审核意见已同步到本页",
        _localize_terms(str(next_check)),
    ]
    rows = "".join(
        f'<div class="support-item"><span class="support-check">✓</span><span>{escape(item)}</span></div>'
        for item in items
    )
    return (
        '<section class="support-card">'
        '<div class="text-xs font-semibold text-violet-500">持续支持</div>'
        '<h2 class="text-xl font-bold text-slate-900 mt-1">您不是一个人在处理这次异常</h2>'
        '<p class="text-sm text-slate-600 leading-relaxed mt-2">先完成上方最关键的步骤。我们会继续提示您什么时候复测、什么时候需要尽快联系医院。</p>'
        f'<div class="support-list">{rows}</div>'
        '<div class="mt-4 text-sm text-slate-500">如果出现胸痛、呼吸困难、明显乏力或意识变化，请不要等待下一次提醒，立即求助。</div>'
        "</section>"
    )


def _render_map_section(ai_msg: str, patient_lat: float, patient_lon: float) -> str:
    lat = patient_lat if patient_lat else 39.9042
    lon = patient_lon if patient_lon else 116.4074

    css = (
        "<style>"
        "#bmap{width:100%;height:100%}"
        "#locate-btn{position:absolute;bottom:12px;right:12px;z-index:999;width:38px;height:38px;"
        "border-radius:50%;border:none;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,0.2);"
        "cursor:pointer;font-size:1.1em;display:flex;align-items:center;justify-content:center}"
        "#locate-btn:active{transform:scale(0.92)}"
        ".map-place{display:flex;align-items:center;gap:10px;background:#f8fafc;border-radius:14px;"
        "padding:12px;margin-top:8px;cursor:pointer;border:2px solid transparent;transition:all 0.15s}"
        ".map-place:active{transform:scale(0.98)}"
        ".map-place.focused{border-color:#1e88e5;box-shadow:0 2px 10px rgba(30,136,229,0.15)}"
        ".map-place-icon{width:34px;height:34px;border-radius:8px;display:flex;align-items:center;"
        "justify-content:center;font-size:1em;flex-shrink:0;background:#e3f2fd}"
        ".map-place-nav{flex-shrink:0;width:30px;height:30px;border-radius:50%;border:none;"
        "background:#1e88e5;color:#fff;font-size:0.9em;cursor:pointer;display:flex;align-items:center;"
        "justify-content:center;box-shadow:0 2px 6px rgba(30,136,229,0.35)}"
        ".map-place-nav:active{transform:scale(0.9)}"
        ".map-dist{font-size:0.75em;font-weight:700;padding:3px 8px;border-radius:16px;"
        "white-space:nowrap;flex-shrink:0;background:#e3f2fd;color:#1565c0}"
        "</style>"
    )

    html = (
        '<section class="panel">'
        '<div class="section-head">'
        '<span class="section-kicker">📍</span>'
        '<div>'
        '<div class="text-sm font-bold text-slate-900">附近医院</div>'
        '<div class="text-xs text-slate-500 mt-1">如症状持续或加重，请尽快前往最近的医疗机构。</div>'
        "</div>"
        "</div>"
        f'<p class="text-sm text-slate-600 mb-3" id="ai-map-text">{escape(ai_msg)}</p>'
        '<div class="rounded-2xl overflow-hidden border border-slate-200 relative" style="height:240px">'
        '<div id="bmap"></div>'
        '<button id="locate-btn" title="回到我的位置">📍</button>'
        "</div>"
        '<div id="map-cards"></div>'
        "</section>"
    )

    js_template = r"""<script>
(function() {
  var bmap = new BMap.Map("bmap");
  bmap.enableScrollWheelZoom(true);
  var userPoint = new BMap.Point(__FALLBACK_LON__, __FALLBACK_LAT__);
  var mapMarkers = [];
  var mapCards = [];
  var mapRoute = null;
  var userOverlays = [];

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
    var label = new BMap.Label('您在这里', {
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
  doMapSearch();

  function doMapSearch() {
    if (!userPoint) return;
    var local = new BMap.LocalSearch(bmap, {
      renderOptions: { autoViewport: false },
      onSearchComplete: function(results) {
        clearResultMarkers();
        var container = document.getElementById('map-cards');
        container.innerHTML = '';
        if (!results || local.getStatus() !== BMAP_STATUS_SUCCESS || results.getCurrentNumPois() === 0) {
          container.innerHTML = '<div style="text-align:center;color:#bbb;padding:16px;font-size:0.85em">附近暂时未找到医院</div>';
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
            card.innerHTML = '<div class="map-place-icon">🏥</div>'
              +'<div style="flex:1;min-width:0"><div style="font-size:0.9em;font-weight:600;color:#222;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+poi.title+'</div>'
              +'<div style="font-size:0.75em;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+(poi.address||'暂无地址')+'</div></div>'
              +'<div class="map-dist">'+distText+'</div>'
              +'<button class="map-place-nav" title="导航">➤</button>';
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
    local.searchNearby('医院', userPoint, 5000);
  }

  function focusMapCard(idx, poi) {
    mapCards.forEach(function(c) { c.classList.remove('focused'); });
    mapCards[idx].classList.add('focused');
    mapCards[idx].scrollIntoView({ behavior:'smooth', block:'nearest' });
    bmap.panTo(poi.point);
    mapMarkers[idx].openInfoWindow(
      new BMap.InfoWindow('<b>'+poi.title+'</b><br><span style="color:#888;font-size:12px">'+(poi.address||'')+'</span>')
    );
    clearRoute();
    var walking = new BMap.WalkingRoute(bmap, {
      renderOptions: { map: bmap, autoViewport: false },
      onSearchComplete: function(results) {
        if (walking.getStatus() !== BMAP_STATUS_SUCCESS) return;
        var plan = results.getPlan(0);
        for (var s = 0; s < plan.getNumRoutes(); s++) {
          var route = plan.getRoute(s);
          var path = route.getPolyline();
          if (path) { path.setStrokeColor('#1e88e5'); path.setStrokeWeight(5); path.setStrokeOpacity(0.85); }
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

    js = js_template.replace("__FALLBACK_LON__", str(lon)).replace("__FALLBACK_LAT__", str(lat))
    return css + "\n" + html + "\n" + js


def main() -> None:
    _load_env()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to parse input: {exc}", file=sys.stderr)
        sys.exit(1)

    payload = data.get("payload") or {}
    llm = data.get("llm_result") or {}
    structured = llm.get("structured_output") or {}
    doctor_feedback = payload.get("doctor_feedback") or {}
    memory = payload.get("memory") or {}

    try:
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Template not found: {_TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)

    status = structured.get("patient_status") or "at_risk"
    if status not in _STATUS_MAP:
        status = "at_risk"
    badge_class, status_icon, status_text = _STATUS_MAP[status]

    meta = payload.get("meta") or {}
    raw_time = meta.get("current_time") or datetime.now().strftime("%Y-%m-%d %H:%M")
    current_time = _format_time(raw_time)

    conditions = structured.get("conditions") or []
    monitoring_plan = structured.get("monitoring_plan") or {}
    patient_name = _extract_patient_name(payload)
    recent_dynamics = memory.get("recent_health_dynamics") or ""
    doctor_name = doctor_feedback.get("doctor_name") or "医疗团队"

    location = payload.get("location") or {}
    current_location = location.get("current") or {}
    patient_lat = current_location.get("lat", 39.9042)
    patient_lon = current_location.get("lon", 116.4074)
    location_address = current_location.get("address") or ""

    ai_map_msg = "下方为您整理了附近医院信息。如头晕加重、胸闷胸痛或复测后仍明显异常，请尽快前往最近医院或直接拨打 120。"

    baidu_map_ak = os.environ.get("BAIDU_MAP_AK", "").strip() or "6zXfgKZZiCdrL3MZBH7DGpjemq5IRxRC"
    map_section = _render_map_section(ai_map_msg, patient_lat, patient_lon)

    report_date = current_time.split(" ")[0] if " " in current_time else datetime.now().strftime("%Y年%m月%d日")
    report_title = f"{report_date} 紧急情况报告"

    html = template.format(
        report_title=report_title,
        current_time=current_time,
        status_badge_class=badge_class,
        status_icon=status_icon,
        status_text=status_text,
        condition_badges=_render_condition_badges(conditions),
        alert_intro_html=_render_alert_intro(
            patient_name=patient_name,
            status_icon=status_icon,
            status_text=status_text,
            conditions=conditions,
            monitoring_plan=monitoring_plan,
            recent_dynamics=recent_dynamics,
        ),
        situation_summary=_escape_text(structured.get("situation_summary") or ""),
        analysis_highlight_html=_render_analysis_highlight(conditions, doctor_feedback, payload),
        vitals_html=_render_vitals(structured.get("latest_vitals") or {}),
        doctor_review_html=_render_doctor_review(
            status=structured.get("physician_status") or "notified",
            note=structured.get("physician_note") or "",
            doctor_feedback=doctor_feedback,
        ),
        actions_html=_render_actions(structured.get("immediate_actions") or []),
        monitoring_html=_render_monitoring(monitoring_plan),
        symptom_feedback_html=_render_symptom_feedback(patient_name=patient_name),
        trend_html=_render_trend_card(structured.get("latest_vitals") or {}),
        contact_html=_render_contact_card(
            nearest_care_text=structured.get("nearest_care_instructions")
            or "如需立即帮助，请拨打 120 或前往最近医院，请勿自行驾车。",
            address=location_address,
            doctor_name=doctor_name,
        ),
        map_html=map_section,
        support_html=_render_support_card(doctor_name=doctor_name, monitoring_plan=monitoring_plan),
        symptom_feedback_script=_render_symptom_feedback_script(),
        baidu_map_ak=baidu_map_ak,
        guardrail=_escape_text(
            structured.get("guardrail")
            or "本页面由 AI 健康助手生成，仅用于辅助提醒，不构成医疗诊断。如有不适，请立即拨打 120 或联系您的医生。"
        ),
    )

    result = {
        "structured_output": {
            "title": report_title,
            "category": "outlier",
            "html": html,
        }
    }
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
