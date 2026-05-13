---
name: emergency-instruction-en
description: Activate when the system detects abnormal vitals or an emergency/urgent triage and needs to deliver clear, concise action instructions to the patient. This is NOT a full health report—it is a lightweight instruction page for urgent situations. Not for routine adherence reporting.
scripts:
  post_llm: scripts/render_instruction.py
---

# Emergency instruction (English)

When an emergency or urgent triage is triggered, produce a **patient-facing** instruction page: what is happening, what the physician has communicated, what to do right now, and how to follow up.

## Design goals

This is an **instruction**, not a report. Keep it short, clear, and calming.
- The patient (solo older adult) may be anxious—use a reassuring, supportive tone.
- No diet tables, no meal plans, no lengthy analysis. Only what matters right now.
- Layout: situation → physician status → immediate actions → monitoring plan → nearest care.

## Input rules

- Use **only** data present in the payload; never invent vitals or diagnoses.
- Source priority:
  1. `latest_health` — current vitals that triggered the alert
  2. `memory.patient_long_term_profile` — demographics, history, medications
  3. `signals` — device signals, anomaly labels, hardware alerts
  4. `physician_response` — physician review status and notes (if available)
  5. `location` — patient location for nearest-care guidance
- When a field has no data, use empty strings—do not fabricate.

## Output format

Strict JSON, top-level keys:

- `message`: One short line, e.g. `"Emergency instructions are ready for you."`
- `structured_output`: object with:
  - `patient_status`: only `"at_risk"` | `"critical"`
  - `situation_summary`: 2–3 sentences explaining what triggered this instruction and the current concern (**English**)
  - `physician_status`: only `"notified"` | `"reviewed"` | `"approved_plan"` | `"modified_plan"`
  - `physician_note`: summary of physician's response/modifications, or empty string if not yet reviewed (**English**)
  - `immediate_actions`: string array, 3–5 concrete things to do right now (**English**), e.g. `"Measure your blood pressure and write it down"`, `"If chest pain worsens, call 911 immediately"`
  - `monitoring_plan`: object with `what_to_monitor` (string), `frequency` (string, e.g. `"Every 30 minutes"`), `next_checkin` (string, e.g. `"The system will check on you in 2 hours"`)
  - `nearest_care_instructions`: one paragraph of text on how to reach nearby care (**English**)
  - `latest_vitals`: object with `blood_pressure`, `heart_rate`, `blood_oxygen`, `blood_glucose` — each a string with units
  - `conditions`: string array of known conditions from profile, e.g. `["Hypertension", "Type 2 diabetes"]`
  - `guardrail`: disclaimer text (**English**)

## Expression constraints

- **Language:** English by default; follow `meta.lang` if explicitly set.
- Tone: calm, clear, reassuring. No jargon. Use "you" / "your".
- Do not add diagnoses beyond what the payload supports.
- Keep the entire output concise—this is meant to be read quickly in an urgent moment.

## References

- `references/ref_emergency.md` — emergency triggers and patient-facing escalation protocol
