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
import sys
from html import escape
from datetime import datetime
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "instruction.html"
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

_STATUS_MAP = {
    "at_risk": ("bg-amber-100 text-amber-800", "⚠️", "需要关注"),
    "critical": ("bg-rose-100 text-rose-800", "🚨", "请立即就医"),
}

_HEADER_GRADIENT = {
    "at_risk": "bg-gradient-to-br from-amber-500 to-orange-600",
    "critical": "bg-gradient-to-br from-rose-600 to-red-700",
}

_PHYSICIAN_STATUS_MAP = {
    "notified": ("bg-amber-50 text-amber-700 border-amber-200", "📤", "已通知您的医生，将尽快审核。"),
    "reviewed": ("bg-blue-50 text-blue-700 border-blue-200", "👁️", "您的医生已查看您的读数。"),
    "approved_plan": ("bg-emerald-50 text-emerald-700 border-emerald-200", "✅", "您的医生已批准护理方案。"),
    "modified_plan": ("bg-indigo-50 text-indigo-700 border-indigo-200", "✏️", "您的医生已更新护理方案。"),
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


def _load_env() -> None:
    if _ENV_PATH.is_file():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def _render_vitals(vitals: dict) -> str:
    parts = []
    for key, label, unit, icon in _VITAL_DEFS:
        val = vitals.get(key)
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


def _render_actions(actions: list[str]) -> str:
    if not actions:
        return '<div class="text-sm text-slate-400">当前暂无具体行动项。</div>'
    parts = []
    for i, action in enumerate(actions, 1):
        parts.append(
            f'<div class="flex items-start gap-3 bg-rose-50 rounded-lg p-3 border border-rose-100">'
            f'<span class="flex-shrink-0 w-6 h-6 rounded-full bg-rose-600 text-white text-xs '
            f'font-bold flex items-center justify-center mt-0.5">{i}</span>'
            f'<div class="text-sm text-slate-700 leading-relaxed">{escape(action)}</div>'
            f'</div>'
        )
    return "\n".join(parts)


def _render_physician_status(status: str, note: str) -> str:
    cls, icon, default_text = _PHYSICIAN_STATUS_MAP.get(
        status, _PHYSICIAN_STATUS_MAP["notified"]
    )
    html = (
        f'<div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs '
        f'font-semibold border {cls} mb-3">{icon} {default_text}</div>'
    )
    if note:
        html += (
            f'<div class="text-sm text-slate-700 bg-slate-50 rounded-lg p-3 leading-relaxed '
            f'border border-slate-100">{escape(note)}</div>'
        )
    return html


def _render_doctor_notes(doctor_feedback: dict) -> str:
    if not doctor_feedback:
        return ""
    doctor_name = doctor_feedback.get("doctor_name") or "医生"
    timestamp = doctor_feedback.get("timestamp") or ""
    message = doctor_feedback.get("message") or ""
    med_changes = doctor_feedback.get("medication_changes") or []
    if not message and not med_changes:
        return ""
    time_display = _format_time(timestamp) if timestamp else ""
    html = (
        '<div class="bg-white rounded-xl shadow-sm border border-blue-100 p-5 mb-3">'
        '<div class="flex items-center gap-2 mb-3 pb-3 border-b border-blue-50">'
        '<span class="text-lg">📋</span><div class="flex-1">'
        f'<h2 class="text-sm font-bold text-slate-800">{escape(doctor_name)}的详细反馈</h2>'
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
        html += '<div class="mt-2"><div class="text-[11px] text-slate-500 font-semibold mb-2">用药调整</div><div class="space-y-2">'
        for change in med_changes:
            if isinstance(change, dict):
                action = change.get("action") or "调整"
                from_med = change.get("from") or ""
                to_med = change.get("to") or ""
                text = f"{action}: {from_med} → {to_med}" if from_med else f"{action}: {to_med}"
            else:
                text = str(change)
            html += f'<div class="text-xs text-blue-700 bg-blue-50 rounded px-3 py-2 border border-blue-100">💊 {escape(text)}</div>'
        html += '</div></div>'
    html += '</div>'
    return html


def _render_monitoring(plan: dict) -> str:
    what = plan.get("what_to_monitor") or "请遵循医生的指导"
    freq = plan.get("frequency") or "按医生指示"
    next_c = plan.get("next_checkin") or "我们将尽快再次联系您"
    rows = [
        ("📌", "监测内容", what),
        ("🔄", "监测频率", freq),
        ("📅", "下次回访", next_c),
    ]
    parts = []
    for icon, label, value in rows:
        parts.append(
            f'<div class="flex items-start gap-3 bg-slate-50 rounded-lg p-3 border border-slate-100">'
            f'<span class="text-base mt-0.5">{icon}</span>'
            f'<div>'
            f'<div class="text-[11px] text-slate-500 font-medium uppercase tracking-wide">{label}</div>'
            f'<div class="text-sm text-slate-700 mt-0.5">{escape(value)}</div>'
            f'</div>'
            f'</div>'
        )
    return "\n".join(parts)


def _render_map_section(
    ai_msg: str,
    patient_lat: float,
    patient_lon: float,
) -> str:
    lat = patient_lat if patient_lat else 39.9042
    lon = patient_lon if patient_lon else 116.4074

    css = (
        "<style>"
        "#bmap{width:100%;height:100%}"
        "#locate-btn{position:absolute;bottom:12px;right:12px;z-index:999;width:38px;height:38px;"
        "border-radius:50%;border:none;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,0.2);"
        "cursor:pointer;font-size:1.1em;display:flex;align-items:center;justify-content:center}"
        "#locate-btn:active{transform:scale(0.92)}"
        ".map-place{display:flex;align-items:center;gap:10px;background:#f8fafc;border-radius:10px;"
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
        '<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5 mb-3">'
        '<div class="flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">'
        '<span class="text-lg">📍</span>'
        '<h2 class="text-sm font-bold text-slate-800">附近医院</h2>'
        "</div>"
        f'<p class="text-sm text-slate-600 mb-3" id="ai-map-text">{ai_msg}</p>'
        '<div class="rounded-2xl overflow-hidden border border-slate-200 relative" style="height:240px">'
        '<div id="bmap"></div>'
        '<button id="locate-btn" title="回到我的位置">📍</button>'
        "</div>"
        '<div id="map-cards"></div>'
        "</div>"
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
          container.innerHTML = '<div style="text-align:center;color:#bbb;padding:16px;font-size:0.85em">\u9644\u8fd1\u6682\u65e0\u533b\u9662</div>';
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
            card.innerHTML = '<div class="map-place-icon">\ud83c\udfe5</div>'
              +'<div style="flex:1;min-width:0"><div style="font-size:0.9em;font-weight:600;color:#222;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+poi.title+'</div>'
              +'<div style="font-size:0.75em;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+(poi.address||'\u6682\u65e0\u5730\u5740')+'</div></div>'
              +'<div class="map-dist">'+distText+'</div>'
              +'<button class="map-place-nav" title="\u5bfc\u822a">\u27a4</button>';
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
    local.searchNearby('\u533b\u9662', userPoint, 5000);
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
    doctor_feedback = payload.get("doctor_feedback") or {}

    try:
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Template not found: {_TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)

    status = so.get("patient_status") or "at_risk"
    if status not in _STATUS_MAP:
        status = "at_risk"
    badge_class, status_icon, status_text = _STATUS_MAP[status]
    header_gradient = _HEADER_GRADIENT[status]

    meta = payload.get("meta") or {}
    current_time = _format_time(
        meta.get("current_time") or datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    conditions = so.get("conditions") or []
    location = payload.get("location") or {}
    loc = location.get("current") or {}
    patient_lat = loc.get("lat", 39.9042)
    patient_lon = loc.get("lon", 116.4074)

    ai_map_msg = "下方为您查询了附近医院。若症状加重，请尽快前往最近的一家或拨打 120。"

    baidu_map_ak = os.environ.get("BAIDU_MAP_AK", "").strip() or "6zXfgKZZiCdrL3MZBH7DGpjemq5IRxRC"
    map_section = _render_map_section(ai_map_msg, patient_lat, patient_lon)

    report_title = datetime.now().strftime("%Y年%m月%d日") + " 异常报告"
    html = template.format(
        report_title=report_title,
        header_gradient=header_gradient,
        current_time=current_time,
        status_badge_class=badge_class,
        status_icon=status_icon,
        status_text=status_text,
        condition_badges=_render_condition_badges(conditions),
        situation_summary=escape(so.get("situation_summary") or ""),
        doctor_notes_html=_render_doctor_notes(doctor_feedback),
        physician_status_html=_render_physician_status(
            so.get("physician_status") or "notified",
            so.get("physician_note") or "",
        ),
        vitals_html=_render_vitals(so.get("latest_vitals") or {}),
        actions_html=_render_actions(so.get("immediate_actions") or []),
        monitoring_html=_render_monitoring(so.get("monitoring_plan") or {}),
        nearest_care_text=escape(
            so.get("nearest_care_instructions")
            or "如需立即帮助，请拨打 120 或前往最近医院。请勿自行驾车。"
        ),
        map_html=map_section,
        baidu_map_ak=baidu_map_ak,
        guardrail=escape(
            so.get("guardrail")
            or "本指令由 AI 健康助手生成，仅供参考，不构成医疗诊断。如有不适，请立即拨打 120 或联系您的医生。"
        ),
    )

    result = {
        "structured_output": {
            "title": report_title,
            "category": "outlier",
            "html": html,
        },
    }

    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
