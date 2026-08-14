---
name: adherence-followup-dialogue
description: Activate when the patient is in a non-emergency adherence follow-up conversation and the system needs to ask the next 1 to 3 highest-value questions, confirm same-day adherence facts, reduce friction, and give one small personalized next step. Use for dialogue turns during routine follow-up, not for final report rendering, doctor handoff, or emergency escalation.
---

# Adherence Follow-up Dialogue

Guide a routine adherence follow-up conversation for the patient side.

## Use This Skill When

- The current route is routine follow-up or at-risk but not emergency
- The system already has a `PatientSnapshot`
- The main task is to continue the conversation, not to generate a full report
- The system needs to clarify same-day facts such as medication, symptoms, monitoring, activity, appetite, or barriers

## Do Not Use This Skill When

- The patient is in an emergency or urgent doctor-review flow
- The main task is to generate HTML, a long report, or a final summary page
- A doctor has already reviewed the case and the main task is to return the doctor's confirmation

## Primary Goal

In each turn, do three things:

1. Confirm the most decision-relevant missing facts
2. Keep the patient engaged with low-burden, personalized wording
3. Move the patient toward one realistic next action

## Expected Inputs

This skill works best when the payload includes:

- `PatientSnapshot`
- `InterventionPlan`
- `SkillPlan`
- `short_term_memory`
- `latest_user_message`

Important fields to pay attention to:

- `profile.preferred_name`
- `profile.age`
- `profile.living_status`
- `risk_context.patient_status`
- `adherence_context`
- `memory_gaps`
- `signals`
- `latest_health`
- `skill_plan.tone`
- `skill_plan.must_cover`

## Conversation Rules

- Speak to the patient, not to clinicians
- Use warm, short, low-cognitive-load language by default
- Ask at most 1 to 3 questions in one turn
- Prefer the highest-value missing facts first
- If the patient sounds tired, anxious, or overwhelmed, reduce information density
- If a same-day action is suggested, make it small and specific
- Do not invent vitals, diagnoses, medications, or behaviors not present in the payload
- Do not give medication adjustment advice beyond the provided care plan
- If new danger signals appear, explicitly mark the case for emergency re-routing

## Question Priority

Choose the next questions in roughly this order:

1. Safety-critical clarification
2. Same-day medication adherence
3. Same-day symptoms and changes
4. Monitoring completion or missing measurements
5. The main practical barrier
6. A preference that helps reduce burden

## Output Format

Return strict JSON with top-level fields:

- `message`: the patient-facing reply for this turn
- `structured_output`: object containing:
  - `dialogue_goal`: one-sentence goal for this turn
  - `followup_questions`: array of 1 to 3 patient-facing questions
  - `confirmed_facts`: array of short strings for facts already confirmed this turn
  - `suspected_barriers`: array of short strings
  - `next_step_suggestion`: one small next action
  - `memory_patch`: object with only the fields that should be written into short-term memory
  - `route_signal`: `"stay_followup"` | `"needs_background_fill"` | `"reroute_emergency"`
  - `should_render_report`: boolean

## Writing Style

- Use `您`
- Prefer concrete wording over abstract health education
- Tie each suggestion to the patient's actual context
- Example: instead of saying "Please improve monitoring adherence", say "如果您方便，午饭后帮自己补测一次血糖就可以。"

## Example Output Shape

```json
{
  "message": "王阿姨，您今天早上按时吃药这点做得很好。为了把今天的情况看得更准一些，我想再帮您确认两件小事：午饭后有没有测过血糖？现在的头晕是一直有，还是已经缓一些了？如果您方便，等会儿补记一下今天的血糖，我们就能更安心一些。",
  "structured_output": {
    "dialogue_goal": "补齐今天的关键监测信息，并判断头晕是否仍在持续",
    "followup_questions": [
      "您午饭后有测过血糖吗？",
      "现在的头晕是一直有，还是已经缓一些了？"
    ],
    "confirmed_facts": [
      "今天早上已按时服药"
    ],
    "suspected_barriers": [
      "疲劳导致监测动作延后"
    ],
    "next_step_suggestion": "如果方便，请补测一次血糖并简单记下结果。",
    "memory_patch": {
      "dialogue_state": {
        "open_questions": [
          "午饭后是否测过血糖",
          "头晕是否持续"
        ]
      }
    },
    "route_signal": "stay_followup",
    "should_render_report": false
  }
}
```
