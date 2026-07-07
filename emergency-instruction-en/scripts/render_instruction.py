#!/usr/bin/env python3
"""
post_llm script for emergency-instruction-en skill.

Reads {"payload": {...}, "llm_result": {...}} from stdin.
Renders a patient-facing emergency instruction HTML page.
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

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "instruction.html"
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

_STATUS_MAP = {
    "at_risk": ("bg-amber-100 text-amber-800", "⚠️", "Needs attention"),
    "critical": ("bg-rose-100 text-rose-800", "🚨", "Seek medical care now"),
}

_HEADER_GRADIENT = {
    "at_risk": "bg-gradient-to-br from-amber-500 to-orange-600",
    "critical": "bg-gradient-to-br from-rose-600 to-red-700",
}

_PHYSICIAN_STATUS_MAP = {
    "notified": ("bg-amber-50 text-amber-700 border-amber-200", "📤", "Your doctor has been notified and will review shortly."),
    "reviewed": ("bg-blue-50 text-blue-700 border-blue-200", "👁️", "Your doctor has reviewed your readings."),
    "approved_plan": ("bg-emerald-50 text-emerald-700 border-emerald-200", "✅", "Your doctor has approved a care plan for you."),
    "modified_plan": ("bg-indigo-50 text-indigo-700 border-indigo-200", "✏️", "Your doctor has updated your care plan."),
}

_VITAL_DEFS = [
    ("blood_pressure", "Blood pressure", "mmHg", "💓"),
    ("heart_rate", "Heart rate", "bpm", "❤️"),
    ("blood_oxygen", "Blood oxygen", "%", "🫁"),
    ("blood_glucose", "Blood glucose", "mmol/L", "🩸"),
]

_COND_COLORS = {
    "Hypertension": "bg-rose-500",
    "Type 2 diabetes": "bg-amber-500",
    "Diabetes": "bg-amber-500",
    "Hyperlipidemia": "bg-orange-500",
    "Coronary artery disease": "bg-red-500",
    "During chemotherapy": "bg-purple-500",
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
                f'<div class="hero-vital-card">'
                f'<div class="hero-vital-top">'
                f'<div><div class="hero-vital-label">{label}</div><div class="hero-vital-value">{escape(str(val))}</div></div>'
                f'<div class="hero-vital-icon">{icon}</div>'
                f'</div>'
                f'<div class="hero-vital-range">{unit}</div>'
                f'</div>'
            )
        else:
            parts.append(
                f'<div class="hero-vital-card">'
                f'<div class="hero-vital-top">'
                f'<div><div class="hero-vital-label">{label}</div><div class="hero-vital-value">--</div></div>'
                f'<div class="hero-vital-icon">{icon}</div>'
                f'</div>'
                f'<div class="hero-vital-range">{unit}</div>'
                f'</div>'
            )
    return "\n".join(parts)


def _render_condition_badges(conditions: list[str]) -> str:
    parts = []
    for c in conditions:
        color = _COND_COLORS.get(c, "bg-slate-500")
        parts.append(
            f'<span class="condition-chip inline-block {color} text-white px-3 py-1 '
            f'rounded-full text-xs font-semibold">{escape(c)}</span>'
        )
    return "\n".join(parts)


def _render_actions(actions: list[str]) -> str:
    if not actions:
        return '<div class="text-sm text-slate-400">No specific actions at this time.</div>'
    parts = []
    for i, action in enumerate(actions, 1):
        parts.append(
            f'<div class="action-step">'
            f'<span class="action-step-index">{i}</span>'
            f'<div class="action-step-copy">{escape(action)}</div>'
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
        '<span class="text-lg">📋</span>'
        '<div class="flex-1">'
        f'<h2 class="text-sm font-bold text-slate-800">{escape(doctor_name)} — detailed notes</h2>'
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
            '<div class="text-[11px] text-slate-400 uppercase tracking-wide font-medium mb-2">'
            'Medication changes</div>'
        )
        for change in med_changes:
            action = change.get("action", "").capitalize()
            from_med = change.get("from", "")
            to_med = change.get("to", "")
            html += (
                '<div class="flex items-start gap-2 bg-rose-50 rounded-lg p-3 border border-rose-100">'
                '<span class="text-sm mt-0.5">💊</span>'
                '<div class="text-xs text-slate-700 leading-relaxed">'
                f'<span class="font-semibold text-rose-700">{escape(action)}:</span> '
            )
            if from_med:
                html += f'<span class="line-through text-slate-400">{escape(from_med)}</span> → '
            if to_med:
                html += f'<span class="font-medium text-emerald-700">{escape(to_med)}</span>'
            html += '</div></div>'
        html += '</div>'

    html += '</div>'
    return html


def _render_monitoring(plan: dict) -> str:
    what = plan.get("what_to_monitor") or "Follow your doctor's guidance"
    freq = plan.get("frequency") or "As directed by your doctor"
    next_c = plan.get("next_checkin") or "We will check on you soon"
    rows = [
        ("📌", "What to monitor", what),
        ("🔄", "How often", freq),
        ("📅", "Next check-in", next_c),
    ]
    parts = []
    for icon, label, value in rows:
        parts.append(
            f'<div class="monitor-row">'
            f'<span class="text-base mt-0.5">{icon}</span>'
            f'<div>'
            f'<div class="monitor-row-label">{label}</div>'
            f'<div class="monitor-row-value">{escape(value)}</div>'
            f'</div>'
            f'</div>'
        )
    return "\n".join(parts)


def _render_map_section(
    ai_msg: str,
    patient_lat: float,
    patient_lon: float,
    google_maps_api_key: str = "",
) -> str:
    lat = patient_lat if patient_lat else 42.2766632
    lon = patient_lon if patient_lon else -71.8079906

    if not google_maps_api_key:
        search_hospitals = (
            f"https://www.google.com/maps/search/hospitals/@{lat},{lon},14z"
        )
        return (
            '<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5 mb-3">'
            '<div class="flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">'
            '<span class="text-lg">📍</span>'
            '<h2 class="text-sm font-bold text-slate-800">Nearby hospitals</h2>'
            "</div>"
            f'<p class="text-sm text-slate-600 mb-3">{escape(ai_msg)}</p>'
            '<div class="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 mb-3">'
            "Set GOOGLE_MAPS_API_KEY to render the interactive map."
            "</div>"
            f'<a class="block rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm font-semibold text-blue-700 hover:bg-blue-100 text-center" href="{search_hospitals}" target="_blank" rel="noopener">🏥 Search nearby hospitals</a>'
            "</div>"
        )

    hosp_js = json.dumps(ai_msg, ensure_ascii=False)
    lat_js = json.dumps(float(lat))
    lon_js = json.dumps(float(lon))

    css = (
        "<style>"
        "#gmap{width:100%;height:100%}"
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
        '<h2 class="text-sm font-bold text-slate-800">Nearby hospitals</h2>'
        "</div>"
        f'<p class="text-sm text-slate-600 mb-3" id="ai-map-text">{ai_msg}</p>'
        '<div class="rounded-2xl overflow-hidden border border-slate-200 relative" style="height:240px">'
        '<div id="gmap"></div>'
        '<button id="locate-btn" title="Center on my location">📍</button>'
        "</div>"
        '<div id="map-cards"></div>'
        "</div>"
    )

    js_template = r"""<script>
(function() {
  var map = null;
  var userPoint = { lat: __FALLBACK_LAT__, lng: __FALLBACK_LON__ };
  var mapMarkers = [];
  var mapCards = [];
  var directionsRenderer = null;
  var directionsService = null;
  var infoWindow = null;
  var placesService = null;

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
    doMapSearch();
  };

  function clearResultMarkers() {
    if (directionsRenderer) directionsRenderer.setDirections({ routes: [] });
    mapMarkers.forEach(function(m) { m.setMap(null); });
    mapMarkers = []; mapCards = [];
  }

  function doMapSearch() {
    if (!placesService) return;
    var container = document.getElementById('map-cards');
    placesService.nearbySearch({ location: userPoint, radius: 5000, type: 'hospital' },
      function(results, status) {
        clearResultMarkers(); container.innerHTML = '';
        if (status !== google.maps.places.PlacesServiceStatus.OK || !results || results.length === 0) {
          container.innerHTML = '<div style="text-align:center;color:#bbb;padding:16px;font-size:0.85em">No nearby hospitals found</div>';
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
          card.innerHTML = '<div class="map-place-icon">\ud83c\udfe5</div>'
            +'<div style="flex:1;min-width:0"><div style="font-size:0.9em;font-weight:600;color:#222;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+escapeHtml(place.name||'Unknown')+'</div>'
            +'<div style="font-size:0.75em;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+escapeHtml(place.vicinity||'No address')+'</div></div>'
            +'<div class="map-dist">'+distText+'</div>'
            +'<button class="map-place-nav" title="Directions">\u27a4</button>';
          card.addEventListener('click', function(e) { if(!e.target.classList.contains('map-place-nav')) focusMapCard(idx, place); });
          card.querySelector('.map-place-nav').addEventListener('click', function(e) { e.stopPropagation(); navigateMapTo(place); });
          container.appendChild(card); mapCards.push(card);
        });
        if (!bounds.isEmpty()) map.fitBounds(bounds, 64);
      });
  }

  function focusMapCard(idx, place) {
    mapCards.forEach(function(c) { c.classList.remove('focused'); });
    mapCards[idx].classList.add('focused');
    mapCards[idx].scrollIntoView({ behavior:'smooth', block:'nearest' });
    map.panTo(place.geometry.location);
    infoWindow.setContent('<b>'+escapeHtml(place.name||'')+'</b><br><span style="color:#888;font-size:12px">'+escapeHtml(place.vicinity||'')+'</span>');
    infoWindow.open(map, mapMarkers[idx]);
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

    js = js_template.replace("__FALLBACK_LON__", lon_js).replace("__FALLBACK_LAT__", lat_js)
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
    patient_lat = loc.get("lat", 42.2766632)
    patient_lon = loc.get("lon", -71.8079906)

    ai_map_msg = (
        "Nearby hospitals are shown below. If your symptoms worsen, "
        "please go to the nearest one or call 911."
    )

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
        ai_map_msg, patient_lat, patient_lon, google_maps_api_key,
    )

    report_title = "Emergency instructions"
    html = template.format(
        report_title=report_title,
        header_gradient=header_gradient,
        current_time=current_time,
        status_badge_class=badge_class,
        status_icon=status_icon,
        status_text=status_text,
        condition_badges=_render_condition_badges(conditions),
        situation_summary=escape(so.get("situation_summary") or ""),
        physician_status_html=_render_physician_status(
            so.get("physician_status") or "notified",
            so.get("physician_note") or "",
        ),
        doctor_notes_html=_render_doctor_notes(doctor_feedback),
        vitals_html=_render_vitals(so.get("latest_vitals") or {}),
        actions_html=_render_actions(so.get("immediate_actions") or []),
        monitoring_html=_render_monitoring(so.get("monitoring_plan") or {}),
        nearest_care_text=escape(
            so.get("nearest_care_instructions")
            or "If you need immediate help, call emergency services (911) or go to the nearest hospital."
        ),
        map_html=map_section,
        maps_script=maps_script,
        guardrail=escape(
            so.get("guardrail")
            or (
                "This instruction was generated by an AI health assistant for guidance only. "
                "It is not a medical diagnosis. If you feel unwell, call emergency services or your doctor immediately."
            )
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
