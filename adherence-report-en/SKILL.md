---
name: adherence-report-en
description: Activate when the user (patient-facing app) asks for a health report, a wellness summary, personalized nutrition guidance, or a weekly meal plan during routine follow-ups. Focused on adherence over recent days/weeks—medication, appetite, exercise, monitoring. Not for emergency or urgent triage situations.
scripts:
  pre_llm: scripts/mock_latest_health.py
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

- Use **only** data present in the payload; do not invent vitals, diagnoses, or numbers.
- Source priority:
  1. `latest_health` — latest vitals (BP, HR, SpO2, glucose, steps)
  2. `memory.patient_long_term_profile` — demographics, history, medications
  3. `memory.recent_health_dynamics` — recent health trends
  4. `memory.tone_profile` (optional) — patient's communication style + current condition context:
     - `condition_context`: `"feeling_unwell"` | `"post_chemotherapy"` | `"post_surgery_recovering"` | `"stable_routine"` — **controls page density**:
       - `feeling_unwell` → simplified page (only: guidance + vitals + meal plan). Patient can't read much.
       - `post_chemotherapy` → comforting tone, emphasis on nutrition/rest (hides: adherence analysis, diet table, map)
       - `post_surgery_recovering` → most sections visible, encouraging tone
       - `stable_routine` → full page with all sections
     - `style`: `"warm_encouraging"` | `"direct_practical"` | `"authority_based"` | `"gentle_patient"` — determines overall tone
     - `preferred_name`: how the patient likes to be addressed
     - `age_group`: `"elderly_70plus"` | `"senior_60_70"` | `"middle_aged"` — affects language complexity and encouragement level
     - `personality_notes`: free-text from caregiver/doctor about how to communicate with this patient
     - `communication_preferences`: `formality`, `motivation_style` (`positive_reinforcement` | `accountability` | `authority_trust`), `information_density` (`simple_focused` | `moderate` | `detailed`), `reference_authority` (boolean — if true, frame advice as "your doctor recommends...")
  5. `memory.key_events` — timestamped events (surgeries, recurring symptoms, alerts)
  6. `adherence_analysis` — medication / diet / exercise / monitoring adherence
  7. `signals` — device signals, anomaly labels
  8. `outlier_analysis` — outlier analysis
  9. `location` — location context
  10. `user_preference` (optional) — patient's stated preferences collected from prior sessions:
     - `cuisine_preferences`: array of cuisine names (e.g. `["Cantonese", "Italian"]`) — use to guide `weekly_meal_plan` food choices
     - `liked`: items the patient previously marked as helpful/enjoyable — prefer similar recommendations
     - `disliked`: items the patient rejected + reason — avoid similar recommendations
- If `latest_health` is empty or all null, infer the latest values from `memory.recent_health_dynamics` or `signals.summary_text` and fill `latest_health_summary` accordingly.
- When a dimension has no data, use empty strings or empty arrays—do not fabricate.
- When `user_preference.cuisine_preferences` is present, the `weekly_meal_plan` **must** reflect those cuisines (e.g., if patient prefers Cantonese, suggest congee, steamed fish, bok choy stir-fry instead of oatmeal and salmon).

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
  - `adherence_analysis`: object with:
    - `period`: string, e.g. `"Past 14 days"`
    - `medication`: object `{ "status": "...", "issues": "...", "adjustments": "..." }`
    - `appetite`: object `{ "status": "...", "cause_if_known": "...", "suggestions": "..." }`
    - `exercise`: object `{ "status": "...", "barriers": "...", "plan": "..." }`
    - `monitoring`: object `{ "status": "...", "gaps": "..." }`
  - `health_guidance`: object with persuasive, condition-specific guidance:
    - `summary`: 2-3 sentences addressing the patient directly, explaining their current situation and why the recommendations matter (warm but firm tone, like a caring family member)
    - `tips`: array of `{"text": "...", "why": "...", "category": "protein|low_salt|low_oil|hydration|fiber|exercise|rest|monitoring"}` — each tip has actionable advice + a personal `why` that connects to the patient's specific conditions/history
  - `recommendations`: array of ~5-6 items. Each item is either a plain string OR an object `{"text": "...", "reason": "...", "category": "medication|diet|exercise|monitoring|lifestyle"}`. When using object form, `reason` explains **why** this is recommended for this specific patient (referencing their conditions, history, or recent events). Prefer object form.
  - `nutrition_advice`: one paragraph (**English**, ~50-100 words)
  - `latest_health_summary`: object with `blood_pressure`, `heart_rate`, `blood_oxygen`, `blood_glucose`, `steps_today` — each a string with units
  - `conditions`: string array, e.g. `["Hypertension", "Type 2 diabetes", "Hyperlipidemia"]`
  - `diet_table`: array of `{"condition", "principle", "recommend", "avoid"}` — all **English**
  - `weekly_meal_plan`: **only 3 days** (UI cycles to 7). Each day: `day` (`"Day 1"` / `"Day 2"` / `"Day 3"`), `breakfast`, `lunch`, `dinner`; each meal array of `{"name", "icon", "condition", "benefit"}` where `benefit` ≤ ~10 English words
  - `diet_tips`: array of `{"icon", "title", "detail"}` — **English**
  - `reasoning`: 2-3 sentences (**English**)
  - `guardrail`: disclaimer text (**English**)

## Expression constraints

- **Language:** English by default; follow `meta.lang` if explicitly set.
- **Tone adaptation (based on `memory.tone_profile`):**
  - `warm_encouraging`: like a caring family member — use "you're doing great", celebrate small wins, gentle nudges. Good for elderly patients who worry about being a burden.
  - `direct_practical`: straightforward, no-nonsense — "here's what to do and why." Less emotional language, more action-focused. Good for independent-minded patients.
  - `authority_based`: frame advice as coming from the care team — "Your doctor has recommended...", "Based on your medical team's assessment...". Good for patients who trust authority and follow doctor's orders closely.
  - `gentle_patient`: very soft, patient, repeats key points — "Take your time", "There's no rush, but...". Good for anxious patients or those with cognitive decline.
  - When `tone_profile` is absent, default to `warm_encouraging`.
  - `health_guidance.summary` and `health_guidance.tips[].why` MUST reflect the chosen tone. Example for same advice:
    - warm: "Your knee is healing beautifully — a little protein at each meal helps it along!"
    - direct: "Protein intake directly supports tissue repair post-surgery."
    - authority: "Your surgeon recommends increased protein to ensure proper healing of the surgical site."
    - gentle: "Don't worry too much — just try to have a little protein when you eat, even a few bites help your knee heal."
- Reference specific recent events from the payload (e.g. "Over the past two weeks, your appetite has been lower than usual...").
- No new diagnoses beyond what the payload supports.
- If sources conflict, note it in `reasoning`.
- Meal plan: exactly **3 days**; keep each `benefit` short.

## References

- `references/ref_adherence.md` — adherence assessment, risk tags, nutrition guidance, tone guardrails
