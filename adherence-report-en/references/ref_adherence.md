# Adherence & Intervention Reference: Isolation & Mobility

Version: 1.1
Last Updated: 2026-03-11

## 1. Check-in Objectives (Every 3 Days)

During routine voice outreach, the Agent must silently assess three core pillars without sounding like a survey:

1. **Medication Adherence:** Did they take their anti-hypertensive meds?
2. **Physical Mobility:** Are they moving enough to maintain cardiovascular health?
3. **Psychological State:** Are there signs of severe social isolation or depression?

## 2. NLP + Telemetry Inference Mapping (The "Brain")

The Agent must cross-reference patient dialogue with smartwatch GPS/Pedometer data to generate `Risk Tags`.

**Scenario A: Mobility & Sedentary Risks**

- _Dialogue:_ "I'm just tired." + _Data:_ Steps < 1000/day for 3 days.
  -> **Generate Tag:** `Risk_Sedentary_Severe`.
- _Dialogue:_ "My legs hurt when I walk." + _Data:_ GPS shows no exits from home boundary in 4 days.
  -> **Generate Tag:** `Risk_Mobility_Decline`.

**Scenario B: Isolation & Mental Health**

- _Dialogue:_ "Nobody has called me," "I don't have an appetite," "What's the point."
  -> **Generate Tag:** `Risk_Depression_Isolation`.
- _Dialogue:_ "I was up all night watching TV." + _Data:_ Smartwatch sleep tracking shows < 4 hours sleep.
  -> **Generate Tag:** `Risk_Insomnia`.

**Scenario C: Positive Reinforcement**

- _Dialogue:_ "I went to the store." + _Data:_ GPS confirms 1.5-mile round trip.
  -> **Generate Tag:** `Goal_Met_Mobility`.

## 3. Nutrition-Aware Guidance (Memory-Driven)

The Agent should use the patient memory store to provide gentle, personalized nutritional suggestions:

- If `hypertension`: Encourage lower-sodium choices.
- If `type_2_diabetes`: Emphasize steady, lower-sugar options.
- If `poor_appetite`: Suggest simple, small, nutrient-dense options.
- When mobility risk tags are active AND fatigue reported: Pair movement advice with nutrition.

## 4. Safety & Tone Guardrails

- Never contradict explicit clinician instructions.
- Avoid prescribing exact calories or strict meal plans; focus on simple, safer swaps.
- Use reassuring, non-judgmental language and always offer choices rather than commands.
