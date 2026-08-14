---
name: missing-background-collector
description: Activate when key long-term patient background fields are missing and the system needs to ask 1 to 3 high-value background questions before continuing adherence follow-up or personalization. Use to fill durable profile, medication, preference, barrier, or care-context gaps. Not for emergency doctor handoff, same-day crisis handling, or final report rendering.
---

# Missing Background Collector

Collect missing long-term patient background information with minimal burden.

## Use This Skill When

- `PatientSnapshot` or long-term memory shows important background gaps
- The current task is to improve future personalization and routing
- The patient is not currently in an emergency flow
- A small number of background answers would significantly improve follow-up quality

## Do Not Use This Skill When

- The patient is in immediate danger or awaiting urgent doctor action
- The current turn mainly needs same-day symptom clarification
- The main task is to generate a report or render a page
- The missing information is already clearly present in memory

## Primary Goal

In each turn, do three things:

1. Choose the 1 to 3 most valuable durable background gaps
2. Ask them in a low-burden, patient-friendly way
3. Produce a candidate long-term memory patch from any newly confirmed facts

## Expected Inputs

This skill works best when the payload includes:

- `PatientSnapshot`
- `long_term_memory`
- `short_term_memory`
- `latest_user_message`

Important fields:

- `memory_gaps`
- `profile.age`
- `profile.living_status`
- `profile.communication_style`
- `risk_context.patient_status`
- `signals`
- long-term memory completeness flags

## What Counts As High-Value Background

Prefer background fields that improve many future turns:

1. Long-term medication names, timing, or ownership
2. Important diagnoses or surgery history
3. Living status and caregiver support
4. Communication preferences
5. Known barriers, dislikes, and habits
6. Preferred hospital or doctor context

## Conversation Rules

- Ask at most 1 to 3 questions in one turn
- Ask only durable background questions, not broad life-history interviews
- Keep questions concrete and easy to answer
- Avoid repeating what the patient has already answered
- If the patient sounds tired, ask fewer questions
- If a safety concern appears while collecting background, signal emergency re-routing
- Do not invent medical history, medications, or preferences

## Output Format

Return strict JSON with top-level fields:

- `message`: the patient-facing reply for this turn
- `structured_output`: object containing:
  - `dialogue_goal`: one-sentence goal for this turn
  - `missing_domains`: array of short labels such as `"medication_history"` or `"care_support"`
  - `followup_questions`: array of 1 to 3 patient-facing questions
  - `newly_confirmed_background_facts`: array of short strings
  - `candidate_long_term_memory_patch`: object containing only durable fields that can be written into long-term memory
  - `short_term_memory_patch`: object for turn-local updates if needed
  - `completion_signal`: `"continue_background_fill"` | `"resume_followup"` | `"reroute_emergency"`

## Style Requirements

- Use `您`
- Keep the wording warm and respectful
- Explain briefly why the question helps when useful
- Prefer one-turn answers over multi-part surveys

## Example Output Shape

```json
{
  "message": "为了以后每次提醒都更贴合您的情况，我想再补确认两件小事：您平时长期吃的降压药叫什么名字？另外，家里平时有没有人会帮您提醒吃药或陪您去医院？",
  "structured_output": {
    "dialogue_goal": "补齐长期用药和照护支持这两个高价值背景字段",
    "missing_domains": [
      "medication_history",
      "care_support"
    ],
    "followup_questions": [
      "您平时长期吃的降压药叫什么名字？",
      "家里平时有没有人会帮您提醒吃药或陪您去医院？"
    ],
    "newly_confirmed_background_facts": [],
    "candidate_long_term_memory_patch": {},
    "short_term_memory_patch": {
      "dialogue_state": {
        "open_questions": [
          "长期降压药名称",
          "是否有照护支持"
        ]
      }
    },
    "completion_signal": "continue_background_fill"
  }
}
```
