#!/usr/bin/env python3
"""
post_llm script for patient-report-en skill.

Reads {"payload": {...}, "llm_result": {...}} from stdin.
Renders a patient-facing HTML health report from a template + LLM structured data.
Writes JSON to stdout with updated structured_output.html.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "report.html"
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

_STATUS_MAP = {
    "stable": ("bg-emerald-100 text-emerald-800", "✅", "Doing well"),
    "at_risk": ("bg-amber-100 text-amber-800", "⚠️", "Needs attention"),
    "critical": ("bg-rose-100 text-rose-800", "🚨", "Seek medical care"),
}

# English + legacy Chinese labels for badge coloring
_COND_COLORS = {
    "Hypertension": "bg-rose-500",
    "Type 2 diabetes": "bg-amber-500",
    "Diabetes": "bg-amber-500",
    "Hyperlipidemia": "bg-orange-500",
    "Coronary artery disease": "bg-red-500",
    "During chemotherapy": "bg-purple-500",
    "高血压": "bg-rose-500",
    "2型糖尿病": "bg-amber-500",
    "糖尿病": "bg-amber-500",
    "高脂血症": "bg-orange-500",
    "冠心病": "bg-red-500",
    "化疗期间": "bg-purple-500",
}

_RISK_TAG_COLORS = {
    "heart rate": "bg-rose-50 text-rose-700 border-rose-200",
    "blood pressure": "bg-rose-50 text-rose-700 border-rose-200",
    "glucose": "bg-amber-50 text-amber-700 border-amber-200",
    "activity": "bg-sky-50 text-sky-700 border-sky-200",
    "low": "bg-amber-50 text-amber-700 border-amber-200",
    "high": "bg-rose-50 text-rose-700 border-rose-200",
    "abnormal": "bg-orange-50 text-orange-700 border-orange-200",
    "心率": "bg-rose-50 text-rose-700 border-rose-200",
    "血压": "bg-rose-50 text-rose-700 border-rose-200",
    "血糖": "bg-amber-50 text-amber-700 border-amber-200",
    "活动": "bg-sky-50 text-sky-700 border-sky-200",
    "偏低": "bg-amber-50 text-amber-700 border-amber-200",
    "偏高": "bg-rose-50 text-rose-700 border-rose-200",
    "异常": "bg-orange-50 text-orange-700 border-orange-200",
}

_VITAL_DEFS = [
    ("blood_pressure", "Blood pressure", "mmHg", "💓"),
    ("heart_rate", "Heart rate", "bpm", "❤️"),
    ("blood_oxygen", "Blood oxygen", "%", "🫁"),
    ("blood_glucose", "Blood glucose", "mmol/L", "🩸"),
    ("steps_today", "Steps today", "steps", "🚶"),
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
            'border bg-emerald-50 text-emerald-700 border-emerald-200">No major risks flagged</span>'
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
            f'font-medium border {cls}">{tag}</span>'
        )
    return "\n".join(parts)


def _render_recommendations(recs: list[str]) -> str:
    if not recs:
        return '<div class="text-sm text-slate-400">No specific recommendations yet</div>'
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
        '<div class="text-[11px] text-slate-400 uppercase tracking-wide font-medium mb-1.5">'
        "How we assessed this</div>"
        f'<div class="text-xs text-slate-600 bg-slate-50 rounded-lg p-3 leading-relaxed">{reasoning}</div>'
        '</div>'
    )


def _extract_text(item) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("text") or item.get("detail") or str(item)
    return str(item)


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
        '<h2 class="text-sm font-bold text-slate-800">Medication & adherence</h2>'
        '</div>'
    )
    if statuses:
        inner += '<div class="flex flex-wrap gap-2 mb-3">'
        for s in statuses:
            text = _extract_text(s)
            inner += (
                f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
                f'bg-emerald-50 text-emerald-700 border border-emerald-200">{text}</span>'
            )
        inner += '</div>'
    if preferences:
        inner += '<div class="flex flex-wrap gap-2 mb-3">'
        for p in preferences:
            text = _extract_text(p)
            inner += (
                f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
                f'bg-blue-50 text-blue-600 border border-blue-200">{text}</span>'
            )
        inner += '</div>'
    if suggestions:
        for s in suggestions:
            text = _extract_text(s)
            inner += (
                f'<div class="flex items-start gap-3 bg-indigo-50 rounded-lg p-3 '
                f'border border-indigo-100 mb-2">'
                f'<span class="text-base mt-0.5">📋</span>'
                f'<div class="text-sm text-slate-700 leading-relaxed">{text}</div>'
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
        '<h2 class="text-sm font-bold text-slate-800">Diet tips</h2>'
        '</div>'
        f'<div class="grid grid-cols-2 gap-2">{inner}</div>'
        '</div>'
    )


def _load_env() -> None:
    if _ENV_PATH.is_file():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def _render_map_section(
    ai_msg_hospital: str,
    ai_msg_park: str,
    patient_lat: float,
    patient_lon: float,
) -> str:
    lat = patient_lat if patient_lat else 42.2766632
    lon = patient_lon if patient_lon else -71.8079906

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
        '<h2 class="text-sm font-bold text-slate-800">Nearby picks</h2>'
        "</div>"
        '<p class="text-sm text-slate-600 mb-3" id="ai-map-text">'
        + ai_msg_hospital
        + "</p>"
        '<div class="rounded-2xl overflow-hidden border border-slate-200 relative" style="height:240px">'
        '<div id="bmap"></div>'
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
    var label = new BMap.Label('You are here', {
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
    document.getElementById('map-cards').innerHTML = '<div style="text-align:center;color:#bbb;padding:16px;font-size:0.85em">Searching…</div>';
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
          container.innerHTML = '<div style="text-align:center;color:#bbb;padding:16px;font-size:0.85em">No nearby places found</div>';
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
              +'<div style="font-size:0.75em;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+(poi.address||'No address')+'</div></div>'
              +'<div class="map-dist '+mode+'">'+distText+'</div>'
              +'<button class="map-place-nav'+(mode==='park'?' park-mode':'')+'" title="Directions">\u27a4</button>';
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

    js = js_template.replace("__HOSP_MSG__", hosp_js)
    js = js.replace("__PARK_MSG__", park_js)
    js = js.replace("__FALLBACK_LON__", str(lon))
    js = js.replace("__FALLBACK_LAT__", str(lat))

    return css + "\n" + html + "\n" + js

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

    try:
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Template not found: {_TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)

    report_title = "Health report"
    header_greeting = "Hello!"
    status = so.get("patient_status") or "stable"
    badge_class, status_icon, status_text = _STATUS_MAP.get(status, _STATUS_MAP["stable"])

    meta = payload.get("meta") or {}
    current_time = meta.get("current_time") or datetime.now().strftime("%Y-%m-%d %H:%M")
    if "T" in str(current_time):
        try:
            dt = datetime.fromisoformat(str(current_time).replace("Z", "+00:00"))
            current_time = dt.strftime("%b %d, %Y %H:%M")
        except (ValueError, TypeError):
            pass
    elif isinstance(current_time, str) and len(current_time) >= 10 and current_time[4] == "-":
        try:
            dt = datetime.strptime(current_time[:16], "%Y-%m-%d %H:%M")
            current_time = dt.strftime("%b %d, %Y %H:%M")
        except ValueError:
            pass

    conditions = so.get("conditions") or []
    location = payload.get("location") or {}
    loc = location.get("current") or {}
    patient_lat = loc.get("lat", 0)
    patient_lon = loc.get("lon", 0)

    if status == "critical":
        ai_map_msg = (
            "We noticed readings that may need urgent attention. "
            "Nearby care locations are shown—please seek medical help if you feel unwell."
        )
        ai_map_msg_park = (
            "When you feel better, a short walk in a nearby park can support recovery—only if your clinician says it is safe."
        )
    elif any(
        "activity" in t.lower()
        or "low" in t.lower()
        or "sedentary" in t.lower()
        or "活动" in t
        or "偏低" in t
        for t in so.get("risk_tags", [])
    ):
        ai_map_msg = (
            "Your recent activity looks a bit low. On a nice day, a gentle walk in a nearby park can help."
        )
        ai_map_msg_park = ai_map_msg
    else:
        ai_map_msg = "Nearby care locations are shown if you ever need them."
        ai_map_msg_park = "On pleasant days, a light walk in a nearby park can support mood and mobility."

    baidu_map_ak = os.environ.get("BAIDU_MAP_AK", "") or "6zXfgKZZiCdrL3MZBH7DGpjemq5IRxRC"
    map_section = _render_map_section(ai_map_msg, ai_map_msg_park, patient_lat, patient_lon)

    meal_json = json.dumps(so.get("weekly_meal_plan") or [], ensure_ascii=False)

    html = template.format(
        report_title=report_title,
        header_greeting=header_greeting,
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
        nutrition_advice=so.get("nutrition_advice")
        or "Aim for balanced meals with plenty of vegetables and adequate hydration.",
        diet_table_html=_render_diet_table(so.get("diet_table") or []),
        diet_tips_html=_render_diet_tips(so.get("diet_tips") or []),
        meal_data_json=meal_json,
        map_html=map_section,
        baidu_map_ak=baidu_map_ak,
        guardrail=so.get("guardrail")
        or (
            "This report was generated by an AI health assistant for information only. "
            "It is not medical advice. If you feel unwell, contact a clinician or emergency services."
        ),
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
