# Adherence & Intervention Reference: Clinical Perspective

Version: 1.1
Last Updated: 2026-03-11

## 1. Adherence Assessment Dimensions

Evaluate these four pillars for each patient check-in:

1. **Medication Adherence:** Compliance with prescribed regimen (anti-hypertensive, hypoglycemic, lipid-lowering).
2. **Physical Mobility:** Steps/activity vs. recommended targets.
3. **Diet Compliance:** Sodium, sugar, fat intake adherence.
4. **Monitoring Compliance:** Regular BP, glucose self-monitoring.

## 2. Risk Tag Generation (NLP + Telemetry)

Cross-reference patient dialogue with device data:

- Steps < 1000/day for 3+ days → `Risk_Sedentary_Severe`
- GPS shows no home exits in 4+ days → `Risk_Mobility_Decline`
- "No appetite" / "What's the point" → `Risk_Depression_Isolation`
- Sleep < 4 hours → `Risk_Insomnia`
- GPS confirms activity → `Goal_Met_Mobility`

## 3. Clinical Intervention Triggers

Based on risk tags, recommend:
- Sedentary/Mobility decline: Cardiac function assessment, ECG, activity plan adjustment.
- Depression/Isolation: Mental health screening referral, social worker alert.
- Insomnia: Sleep hygiene review, medication timing review.
- Medication non-adherence: Simplify regimen, pill organizer, adherence monitoring.
