---
name: adherence-report-en
description: Activate when the user (patient-facing app) asks for a health report, a wellness summary, personalized nutrition guidance, or a weekly meal plan during routine follow-ups. Focused on adherence over recent days/weeks—medication, appetite, exercise, monitoring. Not for emergency or urgent triage situations.
scripts:
  post_llm: scripts/render_report.py
---

# Adherence health report (English)

After a routine check-in or follow-up consultation, produce a **patient-facing** adherence report: how the patient has been doing over the past days/weeks, personalized adjustments, nutrition guidance, and a meal plan.

## Design goals

This report is for the **patient** (solo older adult)—warm, readable, moderate information density.
- Focus on what happened in the recent period: appetite changes, medication side effects, exercise patterns, monitoring gaps.
- When issues are found (e.g. drug-induced appetite loss), explain the likely cause and offer adjusted plans.
- This is **not** for emergencies. If `patient_status` would be `"critical"`, the emergency-instruction skill should be used instead.

## Input rules

- This skill currently supports only the MVP payload; ignore old payload fields even if present.
- Use **only** data present in the payload; do not invent vitals, diagnoses, or numbers.
- The report should **prefer the patient's own concrete facts** over generic disease-level advice.
  - If the payload includes history, surgery, current medications, medication reactions, abnormal readings, device anomalies, or monitoring gaps, try to surface them in `assistant_message_patient`, `health_guidance.summary`, `health_guidance.tips[].why`, and `recommendations[].reason`.
  - Recommendations should answer: "Why does this matter for this patient right now?" For example: because of post-surgery recovery, medication discomfort, recent BP/SpO2 changes, or declining activity.
- MVP input only depends on these fields:
  1. `memory.archive` — long-term health archive summary from `memory_archive.scenario_answer`
  2. `memory.recent.adherence` — recent adherence summary from `query_health_memory_by_type.light_summary_answer`
  3. `memory.recent.outlier` — recent outlier summary from `query_health_memory_by_type.light_summary_answer`
  4. `latest_health` — real latest measured values; show only metrics present in the payload
  5. `latest_health_meta` — measurement time, source, and aggregation note
  6. `signal_trends` — real signal trends for `week` / `month` / `quarter`
  7. `adherence_analysis` — current structured adherence result, shaped as `statuses[]` and `suggestions[]` on input
  8. `location` (optional) — only when real coordinates exist
  9. `patient` (optional) — only when the main service provides basic profile fields
- Do not require or invent `ehr` / `clinical_context` / `recent_memory[]` / `topic` / `conversation`.
- Do not infer latest vital values from memory, EHR, history, or generic prose. If `latest_health` does not contain a metric, leave it out.
- `blood_glucose` may appear only when `latest_health.blood_glucose` or `signal_trends.*.metrics.blood_glucose` exists. Otherwise do not show glucose cards, glucose trends, or glucose conclusions.
- Diabetes may be used as long-term history for diet guidance; without real recent glucose monitoring, do not say recent glucose is high, low, or well controlled.
- `adherence_analysis.statuses[]` and `adherence_analysis.suggestions[]` are fact sources, not final UI copy. Digest, split, merge, and rewrite them before using them in `assistant_message_*`, `recommendations`, `nutrition_*`, or `weekly_meal_plan`; do not paste one long suggestion directly into a card.
- When a dimension has no data, use empty strings or empty arrays—do not fabricate.
- New context must be folded into one of the MVP fields above; do not add parallel duplicate fields.

## Output format

Strict JSON, top-level keys:

- `message`: One short line, e.g. `"Your adherence report is ready."`
- `structured_output`: object with:
  - `patient_status`: only `"stable"` | `"at_risk"` (no `"critical"` — that belongs to emergency-instruction)
  - `risk_tags`: string array, e.g. `["Low activity level", "Appetite decreased"]`
  - `assistant_message_patient`: Warm paragraph (**English**, ~100-200 words): summary of recent adherence + encouragement + key adjustments (used as fallback if `assistant_message_sections` is absent)
  - `assistant_message_sections`: array of structured message blocks, each with:
    - `type`: `"good_news"` | `"attention"` | `"plan"` | `"encouragement"` — determines icon and color
    - `title`: short label (e.g. "Good news", "Things to watch", "What we've prepared", "You've got this")
    - `content`: 1-2 sentences for that section
  - `personalized_evidence` (required):
    - 3-5 items, each shaped like `{ "title": "...", "evidence": "...", "why_it_matters": "...", "category": "history|surgery|medication|lab|symptom|monitoring" }`
    - This should explicitly tell the patient which facts drove the current advice: history, medication reactions, recovery stage, abnormal tests, or recent monitoring changes
    - It must be digested from `memory.archive`, `memory.recent.*`, `adherence_analysis`, and `latest_health`; do not copy long raw text blocks
    - If medication side effects, post-op recovery, or abnormal tests are present, try to cover them directly
  - `adherence_analysis`: object with:
    - `period`: string, e.g. `"Past 14 days"`
    - `medication`: object `{ "status": "...", "issues": "...", "adjustments": "..." }`
    - `appetite`: object `{ "status": "...", "cause_if_known": "...", "suggestions": "..." }`
    - `exercise`: object `{ "status": "...", "barriers": "...", "plan": "..." }`
    - `monitoring`: object `{ "status": "...", "gaps": "..." }`
  - `health_guidance`: object with persuasive, condition-specific guidance:
    - `summary`: 2-3 sentences addressing the patient directly, explaining their current situation and why the recommendations matter (warm but firm tone, like a caring family member)
    - `tips`: array of `{"text": "...", "why": "...", "category": "protein|low_salt|low_oil|hydration|fiber|exercise|rest|monitoring"}` — each tip has actionable advice + a personal `why` that connects to the patient's specific conditions/history
  - `recommendations`: array of ~5-6 items. Each item is either a plain string OR an object `{"text": "...", "reason": "...", "category": "medication|diet|exercise|monitoring|lifestyle"}`. When using object form, `reason` explains **why** this is recommended for this specific patient (referencing their conditions, history, or recent events). Prefer object form. The first 3 items appear as "today's top three actions"; AI must prioritize and rewrite them, not merely copy `suggestions[]`.
  - `nutrition_advice`: one paragraph (**English**, ~50-100 words), grounded in real diet/appetite/condition facts; avoid generic "eat healthy" prose.
  - `nutrition_priorities`: 3-4 items shaped as `{ "title": "...", "action": "...", "reason": "...", "category": "low_salt|low_oil|protein|hydration|fiber|meal_rhythm" }`. This is qualitative AI-generated nutrition guidance; do not output percentages, calories, macros, or "AI estimate" numbers unless the payload explicitly provides them.
  - `latest_health_summary`: object containing only real metrics present in payload. Allowed keys include `blood_pressure`, `heart_rate`, `blood_oxygen`, `blood_glucose`, `steps_today`; omit missing keys. The renderer ultimately rebuilds this block from `payload.latest_health`
  - `conditions`: string array, e.g. `["Hypertension", "Type 2 diabetes", "Hyperlipidemia"]`
  - `diet_table`: array of `{"condition", "principle", "recommend", "avoid"}` — all **English**
  - `weekly_meal_plan`: **only 3 days** (UI cycles to 7). Each day: `day` (`"Day 1"` / `"Day 2"` / `"Day 3"`), `breakfast`, `lunch`, `dinner`; each meal array of `{"name", "icon", "condition", "benefit"}` where `benefit` ≤ ~10 English words. The meal plan should be AI-generated from payload conditions, diet issues, appetite/activity state, and preferences when available; return an empty array when there is not enough support.
  - `diet_tips`: array of `{"icon", "title", "detail"}` — **English**
  - `reasoning`: 2-3 sentences (**English**)
  - `guardrail`: disclaimer text (**English**)

## Expression constraints

- **Language:** English by default; follow `meta.lang` if explicitly set.
- **Tone:** warm and practical by default, like a caring family member; the current MVP payload does not read `tone_profile`.
- Reference specific recent events from the payload (e.g. "Over the past two weeks, your appetite has been lower than usual...").
- If the payload includes a specific medication name, procedure, date, abnormal lab, or physician note, keep that anchor in the wording whenever possible instead of flattening it into vague phrases like "your recent health has been unstable."
- `recommendations[].reason` should not stop at "helpful for hypertension" or "good for diabetes." Make it as patient-specific as the data allows: "Because you recently..." or "Since your recovery is still..."
- No new diagnoses beyond what the payload supports.
- If sources conflict, note it in `reasoning`.
- Meal plan: exactly **3 days** when supported by the payload, otherwise return an empty array; keep each `benefit` short.
- AI-generated content includes the hero summary, top three actions, special reminder, nutrition priorities, nutrition advice, and three-day meal plan. The renderer should only hide missing data and display the structure; it should not create these rich content blocks.

## References

- `references/ref_adherence.md` — adherence assessment, risk tags, nutrition guidance, tone guardrails
