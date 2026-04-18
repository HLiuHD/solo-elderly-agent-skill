# Emergency Reference Protocol: Cardiovascular & Fall Risk (Solo Patient)

Version: 1.2
Last Updated: 2026-03-11

## 1. Clinical & Hardware Triggers

The Agent must immediately switch to Emergency Mode if ANY of the following are detected:

- **Blood Pressure (BP):** Systolic > 180 mmHg OR Diastolic > 120 mmHg (Hypertensive Crisis).
- **Heart Rate (HR):** Resting HR > 120 bpm OR < 40 bpm.
- **Smartwatch Hardware:** `alert_type: "hard_fall_detected"` OR `alert_type: "irregular_rhythm_afib"`.
- **NLP Keywords Detected:** "chest pain", "crushing", "left arm hurts", "can't breathe", "dizzy", "fell", "can't get up".

## 2. Patient-Facing Emergency Response

If emergency triggers are detected in patient-facing reports:
- Set `patient_status` to "critical"
- Provide clear, calm instructions to the patient
- Recommend calling emergency services or contacting family immediately
- Include emergency contact information in recommendations
