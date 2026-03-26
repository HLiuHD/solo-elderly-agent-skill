# Solo Elderly Agent — Pipeline Overview

**Agent Skill: What We Have Today**  
*For Memory, Model Training & Engineering*

---

# Agenda

1. **Scenario & goal** — Who we're building for  
2. **End-to-end pipeline** — Data flow and decisions  
3. **Artifacts** — Where the logic lives (`solo_elderly_skill`, `ref_adherence`)  
4. **Risk tagging** — For model training (NLP + telemetry → tags)  
5. **Interventions & tools** — Emergency, mobility, nutrition  
6. **Memory interface** — What we need from Memory  
7. **Reporting & feedback** — Outputs for PCP, social worker, evaluation  

---

# 1. Scenario & Goal

**Target:** Elderly, living alone, no family support  
**Devices:** Smartwatch (GPS, vitals, fall detection)  
**Check-in:** Every 3 days (voice)

**Goal:** Act as the primary safety net — use telemetry + conversation + memory to:
- Detect risk (falls, very high BP, isolation, sedentary, low mood)
- Trigger emergency workflows when needed
- Guide daily adherence: mobility, mental health, nutrition

---

# 2. End-to-End Pipeline

**[Insert your Mermaid diagram export here — PNG or SVG]**

**Flow (left → right):**
- **Inputs:** Smartwatch telemetry, conversation (NLP), patient memory  
- **Inference:** Risk tagging engine → risk tags (e.g. sedentary, isolation, goal met)  
- **Interventions:** Emergency workflow, mobility & isolation (weather + parks/events), nutrition guidance  
- **Outputs:** Structured JSON report → PCP & social worker dashboard  

---

# 3. Artifacts — Where the Logic Lives

| File | Role |
|------|------|
| **`solo_elderly_skill.md`** | Scenario + orchestration: persona, pre-call (Memory + Device API), emergency protocol, adherence flow, JSON report schema |
| **`references/ref_adherence.md`** | Risk rules + interventions: check-in objectives, NLP+telemetry → risk tags, MCP triggers (weather, parks, events), **nutrition from memory**, reporting fields |

**References used by the skill:** `ref_emergency`, `ref_adherence` (and implicitly memory/RAG).

---

# 4. Risk Tagging — For Model Training

**Idea:** Cross-reference **dialogue (NLP)** + **telemetry (GPS, steps, sleep)** to produce **risk tags**.

| Dialogue signal | Telemetry | Tag |
|-----------------|-----------|-----|
| "I'm just tired." | Steps &lt; 1000/day, 3 days | `Risk_Sedentary_Severe` |
| "My legs hurt when I walk." | No exit from home, 4 days | `Risk_Mobility_Decline` |
| "Nobody has called me," "What's the point." | — | `Risk_Depression_Isolation` |
| "I was up all night watching TV." | Sleep &lt; 4 hrs | `Risk_Insomnia` |
| "I went to the store." | GPS confirms ~1.5 mi trip | `Goal_Met_Mobility` |

**Handoff for ML:** These tags are the **supervised targets** — train/evaluate so that model output + device data map to these tags.

---

# 5. Interventions & Tools

**Emergency (from skill):**  
Systolic BP &gt; 180, hard fall, geofence breach → get GPS → one yes/no prompt → `dispatch_emergency_services(lat, lon)`, `find_nearby_ER(lat, lon)`, alert PCP + case worker.

**Mobility & isolation (from ref_adherence):**  
If `Risk_Sedentary_Severe` or `Risk_Depression_Isolation`:  
`get_weather(lat, lon)` → if safe: `find_accessible_parks` / `find_community_senior_events`; if not: indoor option (e.g. chair yoga).

**Nutrition (memory-driven):**  
Use memory (diagnoses, diet notes, restrictions) → condition-based suggestions (e.g. low sodium for hypertension, small nutrient-dense meals for poor appetite). Never override clinician instructions in memory.

---

# 6. Memory Interface — What We Rely On

**Pre-call / during check-in we need:**

- **Recent complaints:** e.g. query *"symptoms or complaints in the last 7 days"* (for context and nutrition).
- **Structured patient facts:** Diagnoses (hypertension, diabetes, CKD, etc.), diet restrictions (`low_sodium_diet`, `renal_diet`), preferences (e.g. difficulty cooking, poor appetite).
- **Clinician overrides:** Any explicit instructions (e.g. fluid restriction) so the agent reinforces them and does not contradict.

**Output:** Same memory store can be updated with summary of the check-in (e.g. risks, actions taken) for the next cycle.

---

# 7. Reporting & Feedback

**Every check-in produces a structured JSON**, e.g.:

- `patient_status`: stable | at_risk | critical  
- `current_location` (lat/lon + context)  
- `mobility_metrics`: days_since_left_home, average_daily_steps  
- `nlp_inferred_risks`, `new_risk_tags_generated`  
- `actionable_tasks_assigned`  
- `social_worker_alert` + reason  

**Use:**  
- Update PCP & community case worker dashboard.  
- Evaluate pipeline: did the right tags fire? Did the right interventions get suggested?  

---

# Next Steps & Handoffs

- **Memory:** Reliable read/write of complaints, diagnoses, restrictions, and clinician instructions; optional summary write-back after check-in.
- **Model training:** Align NLP + telemetry → risk tags; use report fields and tags for evaluation and iteration.
- **Engineering:** MCP tools (dispatch, ER finder, weather, parks/events) and wiring to device API and Vector DB.

**Q&A**
