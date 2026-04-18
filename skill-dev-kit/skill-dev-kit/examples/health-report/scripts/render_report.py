#!/usr/bin/env python3
"""
post_llm script for health-report skill.

Reads {"payload": {...}, "llm_result": {...}} from stdin.
Renders the HTML report from a template + LLM structured data.
Writes JSON to stdout with updated structured_output.html.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "report.html"

_STATUS_LABELS = {
    "stable": ("稳定", "badge-stable"),
    "attention": ("需关注", "badge-attention"),
    "warning": ("需就医", "badge-warning"),
}

_ADH_LABELS = {
    "medication": "用药",
    "diet": "饮食",
    "exercise": "运动",
    "monitoring": "监测",
}

_VITAL_STATUS_CLASS = {
    "normal": "note-normal",
    "high": "note-high",
    "low": "note-low",
}

_VITAL_STATUS_TEXT = {
    "normal": "正常",
    "high": "偏高",
    "low": "偏低",
}


def _render_vitals(vitals: list[dict]) -> str:
    parts = []
    for v in vitals:
        status = v.get("status", "normal")
        css_cls = _VITAL_STATUS_CLASS.get(status, "note-normal")
        note = v.get("note") or _VITAL_STATUS_TEXT.get(status, "")
        parts.append(
            f'<div class="vital-card">'
            f'<div class="value">{v.get("value", "--")}</div>'
            f'<div class="unit">{v.get("unit", "")}</div>'
            f'<div class="label">{v.get("label", "")}</div>'
            f'<div class="note {css_cls}">{note}</div>'
            f'</div>'
        )
    return "\n".join(parts)


def _render_risk_tags(tags: list[str]) -> str:
    if not tags:
        return ""
    items = "".join(f'<span class="tag">{t}</span>' for t in tags)
    return f'<div class="tags">{items}</div>'


def _render_recommendations(recs: list[dict]) -> str:
    parts = []
    for r in recs:
        priority = r.get("priority", "medium")
        css_cls = f"rec-{priority}" if priority in ("high", "medium", "low") else "rec-medium"
        parts.append(f'<li class="{css_cls}">{r.get("text", "")}</li>')
    return "\n".join(parts)


def _render_adherence(adh: dict) -> str:
    parts = []
    for key, label in _ADH_LABELS.items():
        item = adh.get(key) or {}
        status = item.get("status", "fair")
        css_cls = f"adh-{status}" if status in ("good", "fair", "poor") else "adh-fair"
        status_icon = {"good": "良好", "fair": "一般", "poor": "需改善"}.get(status, "一般")
        detail = item.get("detail", "暂无数据")
        parts.append(
            f'<div class="adh-item {css_cls}">'
            f'<div class="dim">{label} · {status_icon}</div>'
            f'<div class="detail">{detail}</div>'
            f'</div>'
        )
    return "\n".join(parts)


def _render_diet_section(guidance: list[dict]) -> str:
    if not guidance:
        return ""
    rows = []
    for g in guidance:
        rows.append(
            f'<tr>'
            f'<td>{g.get("condition", "")}</td>'
            f'<td>{g.get("principle", "")}</td>'
            f'<td class="good">{g.get("recommended", "")}</td>'
            f'<td class="avoid">{g.get("avoid", "")}</td>'
            f'</tr>'
        )
    table_rows = "\n".join(rows)
    return (
        '<div class="card">'
        '<div class="card-title">饮食指导</div>'
        '<table class="diet-table">'
        "<thead><tr>"
        '<th>疾病</th><th>原则</th><th>推荐</th><th>避免</th>'
        "</tr></thead>"
        f"<tbody>{table_rows}</tbody>"
        "</table></div>"
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

    # Load template
    try:
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Template not found: {_TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)

    # Extract fields
    patient_name = so.get("patient_name") or "您"
    overall_status = so.get("overall_status") or "stable"
    status_label, status_css = _STATUS_LABELS.get(overall_status, _STATUS_LABELS["stable"])

    meta = payload.get("meta") or {}
    current_time = meta.get("current_time") or datetime.now().strftime("%Y-%m-%d %H:%M")

    # Render HTML
    html = template.format(
        title=f"{patient_name}的健康报告",
        greeting=f"{patient_name}，您好！",
        subtitle=f"这是您的专属健康报告 · {current_time}",
        overview_status_badge=f'<span class="badge {status_css}">{status_label}</span>',
        overall_summary=so.get("overall_summary") or "",
        vitals_html=_render_vitals(so.get("vitals") or []),
        risk_tags_html=_render_risk_tags(so.get("risk_tags") or []),
        recommendations_html=_render_recommendations(so.get("recommendations") or []),
        reasoning=so.get("reasoning") or "",
        adherence_html=_render_adherence(so.get("adherence") or {}),
        diet_section=_render_diet_section(so.get("diet_guidance") or []),
    )

    # Output: update structured_output with rendered html + separate detail
    result = {
        "structured_output": {
            "html": html,
            "detail": so,
        },
    }

    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
