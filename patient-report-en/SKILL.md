---
name: patient-report-en
description: Activate when the user (patient-facing app) asks for a health report, a wellness summary, personalized nutrition guidance, or a weekly meal plan. For solo older adults reading the report themselves—warm tone, clear layout. Not for clinician-facing triage or medical documentation.
scripts:
  pre_llm: scripts/mock_latest_health.py
  post_llm: scripts/render_report_googlemap.py
---

# Patient health report (English)

From the payload’s patient data, produce a **patient-facing** integrated health report: overview, personalized tips, nutrition guidance, and a weekly-style meal plan.

## Design goals

This report is for the **patient** (solo older adult)—warm, readable, moderate information density.  
It is **not** a clinical document for providers; avoid heavy jargon. Use **you** / **your** in a caring, supportive voice (like a trusted health companion).

## Input rules

- Use **only** data present in the payload; do not invent vitals, diagnoses, or numbers.
- Source priority:
  1. `latest_health` — latest vitals (BP, HR, SpO₂, glucose, steps)
  2. `memory.patient_long_term_profile` — demographics, history, medications
  3. `memory.recent_health_dynamics` — recent health trends
  4. `adherence_analysis` — medication / diet / exercise / monitoring adherence
  5. `signals` — device signals, anomaly labels
  6. `outlier_analysis` — outlier analysis
  7. `location` — location context
- If `latest_health` is empty or all null, infer the latest values from `memory.recent_health_dynamics` or `signals.summary_text` and fill `latest_health_summary` accordingly.
- When a dimension has no data, use empty strings or empty arrays—do not fabricate.

## Output format

Strict JSON, top-level keys:

- `message`: One short line, e.g. `"Your health report is ready."`
- `structured_output`: object with:
  - `patient_status`: only `"stable"` | `"at_risk"` | `"critical"`
  - `risk_tags`: string array, e.g. `["Mild heart-rate variability", "Low activity level"]`
  - `assistant_message_patient`: Warm paragraph for the patient (**English**, about 100–200 words): summary + practical lifestyle guidance
  - `recommendations`: string array, ~5 concrete actionable items (**English**)
  - `nutrition_advice`: one paragraph (**English**, ~50–100 words)
  - `latest_health_summary`: object with `blood_pressure`, `heart_rate`, `blood_oxygen`, `blood_glucose`, `steps_today` — each value a **string with units** (English units/labels where appropriate)
  - `adherence`: object with `statuses` (string array, one line each, **English**), `preferences` (string array), `suggestions` (string array)
  - `conditions`: string array of conditions from profile, **English** labels when possible, e.g. `["Hypertension", "Type 2 diabetes", "Hyperlipidemia"]`
  - `diet_table`: array of `{"condition", "principle", "recommend", "avoid"}` — all **English**
  - `weekly_meal_plan`: **only 3 days** of meals (the UI cycles to 7). Each day: `day` (`"Day 1"` / `"Day 2"` / `"Day 3"`), `breakfast`, `lunch`, `dinner`; each meal is an array of `{"name", "icon", "condition", "benefit"}` where `benefit` is a **very short** phrase (≤ ~10 English words, e.g. `"Heart-friendly potassium"`)
  - `diet_tips`: array of `{"icon", "title", "detail"}` — **English**
  - `reasoning`: 2–3 sentences explaining how you used the payload (**English**)
  - `guardrail`: disclaimer text (**English**)

## Expression constraints

- **Language:** English unless `meta.lang` explicitly requests another language; if `meta.lang` is `zh`, you may output Chinese—otherwise default to **English** for all user-visible strings in `structured_output`.
- Tone: supportive, non-alarming; no new medical diagnoses beyond what the payload supports.
- If sources conflict, note it briefly in `reasoning`.
- Meal plan: exactly **3 days** in JSON; keep each `benefit` short.

## References

Optional grounding files (same folder as this skill):

- `references/ref_emergency.md` — emergency triggers and patient-facing escalation
- `references/ref_adherence.md` — adherence, mobility, and tone guardrails
