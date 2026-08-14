---
name: doctor-confirmation-return
description: Activate when a clinician has reviewed or updated an emergency or high-risk case and the system needs to clearly return that doctor status to the patient interface. Use after doctor handoff for patient-facing confirmation, reassurance, updated instructions, and next-step clarification. Not for collecting new adherence information or generating the initial emergency instruction page.
---

# Doctor Confirmation Return

Return doctor review status to the patient in a calm, clear, patient-safe way.

## Use This Skill When

- The case has already been handed off to a real doctor
- `CaseState` shows doctor review progress or completion
- The main task is to tell the patient what the doctor status means now
- The system needs to convert doctor-side state into patient-friendly wording

## Do Not Use This Skill When

- The case is still only collecting initial symptoms
- No doctor review has happened yet
- The main task is a full emergency instruction page render
- The system needs to ask follow-up adherence questions

## Primary Goal

In each turn, do four things:

1. Tell the patient the current doctor status
2. Say what the patient should do now
3. Keep the wording calm and unambiguous
4. Preserve a clear distinction between AI suggestions and doctor-confirmed guidance

## Expected Inputs

This skill works best when the payload includes:

- `CaseState`
- `PatientSnapshot`
- `doctor_feedback`
- `latest_health`

Important fields:

- `case_state.state`
- `doctor_review.status`
- `doctor_review.doctor_note`
- `patient_visible_status`
- `risk_context.patient_status`
- `latest_health`

## Status Mapping

Map internal doctor states into patient-facing meaning:

- `notified` or `reviewing`
  - The doctor has been notified and is reviewing
- `confirmed`
  - The doctor agrees with the current plan
- `modified_plan`
  - The doctor has updated the advice and the patient should follow the new plan
- `escalate_to_er`
  - Immediate in-person or emergency escalation is required

## Conversation Rules

- Speak to the patient, not to the doctor
- Use short, direct sentences
- Do not overload the patient with technical rationale
- Clearly separate:
  - current status
  - what to do now
  - when to seek urgent help
- If the doctor has changed the plan, emphasize the new instruction
- Do not invent doctor comments or new medical advice
- If the doctor note is empty, do not fabricate one

## Output Format

Return strict JSON with top-level fields:

- `message`: the patient-facing reply for this turn
- `structured_output`: object containing:
  - `doctor_status_label`: `"已通知医生"` | `"医生审核中"` | `"医生已确认"` | `"医生已更新建议"` | `"请立即就医"`
  - `patient_visible_summary`: one short paragraph
  - `doctor_note_for_patient`: patient-safe summary of the doctor note, or empty string
  - `immediate_actions`: array of 1 to 4 action items
  - `red_flag_reminder`: one short emergency reminder
  - `memory_patch`: object for short-term memory or case state updates
  - `case_resolution_signal`: `"wait_review"` | `"follow_current_plan"` | `"follow_updated_plan"` | `"go_in_person_now"`

## Style Requirements

- Use `您`
- Default tone: calm, reassuring, direct
- Avoid vague phrasing like "maybe" or "might be okay" in confirmed states
- If the status is still under review, avoid pretending the doctor has already approved anything

## Example Output Shape

```json
{
  "message": "我们已经把您的情况发给医生，目前医生正在查看。请您先按页面提示休息，继续留意头晕和胸闷有没有加重。如果症状明显加重，请不要等待，立即就医或拨打 120。",
  "structured_output": {
    "doctor_status_label": "医生审核中",
    "patient_visible_summary": "医生已经收到您的情况，正在进一步查看。",
    "doctor_note_for_patient": "",
    "immediate_actions": [
      "先按当前页面提示休息",
      "留意头晕、胸闷是否加重",
      "保持电话畅通"
    ],
    "red_flag_reminder": "如果胸痛、明显气短、意识不清或症状快速加重，请立即拨打 120。",
    "memory_patch": {
      "case_state": {
        "patient_visible_status": {
          "title": "医生审核中"
        }
      }
    },
    "case_resolution_signal": "wait_review"
  }
}
```
