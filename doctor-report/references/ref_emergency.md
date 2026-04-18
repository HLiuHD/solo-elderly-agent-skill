# Emergency Reference Protocol: Cardiovascular & Fall Risk (Solo Patient)

Version: 1.2
Last Updated: 2026-03-11

## 1. Clinical & Hardware Triggers

Immediately escalate triage level to "emergency" if ANY of the following are detected:

- **Blood Pressure (BP):** Systolic > 180 mmHg OR Diastolic > 120 mmHg (Hypertensive Crisis).
- **Heart Rate (HR):** Resting HR > 120 bpm OR < 40 bpm.
- **Smartwatch Hardware:** `alert_type: "hard_fall_detected"` OR `alert_type: "irregular_rhythm_afib"`.
- **NLP Keywords:** "chest pain", "crushing", "left arm hurts", "can't breathe", "dizzy", "fell", "can't get up".

## 2. Triage Logic (Strictly Enforced)

- **Emergency:** Life-threatening condition, immediate intervention needed.
- **Urgent:** Significant deterioration, intervention within hours.
- **Semi-urgent:** Elevated risk, monitoring and follow-up within 24 hours.
- **Non-urgent:** Stable, routine follow-up.

## 3. Dispatch & Alert Protocol

For emergency/urgent triage:
- Include precise GPS coordinates in the report.
- Recommend specific clinical actions (ECG, labs, medication adjustment).
- Flag for immediate PCP and social worker notification.
