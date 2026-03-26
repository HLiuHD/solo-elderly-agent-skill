# Emergency Reference Protocol: Cardiovascular & Fall Risk (Solo Patient)

Version: 1.2
Last Updated: 2026-03-11

## 1. Clinical & Hardware Triggers

The Agent must immediately switch to Emergency Mode if ANY of the following are detected via API telemetry or NLP intent:

- **Blood Pressure (BP):** Systolic > 180 mmHg OR Diastolic > 120 mmHg (Hypertensive Crisis).
- **Heart Rate (HR):** Resting HR > 120 bpm OR < 40 bpm.
- **Smartwatch Hardware:** `alert_type: "hard_fall_detected"` OR `alert_type: "irregular_rhythm_afib"`.
- **Smartwatch GPS:** `Geofence_Breach` (wandering outside safe zones at unusual hours).
- **NLP Keywords Detected:** "chest pain", "crushing", "left arm hurts", "can't breathe", "dizzy", "fell", "can't get up", "face drooping", "speech slurred".

## 2. Triage Logic (Strictly Enforced)
If a trigger is activated, the Agent must interrupt all normal adherence tasks and execute the following:
1. **Assess Consciousness (Voice):** "I received a concerning health alert. Are you experiencing chest pain or having trouble standing up?"
2. **Wait Time:** Allow exactly 15 seconds for a response.
3. **Branch A (Patient responds 'Yes' OR asks for help):** Proceed immediately to Level 1 Dispatch.
4. **Branch B (No response / Silence after 15s):** Assume unconsciousness due to fall or cardiac event. Proceed immediately to Level 1 Dispatch.
5. **Branch C (Patient responds 'No, I'm fine / False alarm'):** Do not dispatch EMS. Proceed to Level 2 Alert. Log the false positive.

## 3. Action & MCP Execution Matrix
**Level 1 Dispatch (Life-Threatening / Unconscious):**
- **MCP Call 1:** `get_current_gps_location(device_id)` — or read current `smartwatch_gps(lat, lon)`.
- **MCP Call 2:** `dispatch_emergency_services(lat, lon, reason="Suspected cardiac event / fall, patient lives alone, unconscious")`. Do not rely on home address if the patient is outdoors.
- **MCP Call 3:** `find_nearby_ER(lat, lon)` — provide EMS with the closest available facility and patient history.
- **MCP Call 4:** `notify_social_worker_and_pcp(patient_id, severity="CRITICAL", location_data)` — push high-priority alert with exact GPS location and time of incident.
- **Agent Behavior:** Stay on the voice line. Loop comforting audio: "Help is on the way, an ambulance has been dispatched to your location. Please stay as still as possible."

**Level 2 Alert (Elevated Risk / False Alarm on Hardware):**
- **MCP Call:** `schedule_urgent_telehealth_visit(patient_id, timeframe="within_24_hours")`
- **Agent Behavior:** Instruct patient to sit down, drink water, and re-test BP in 15 minutes.