# How to Explain Your Pipeline Slides to Others

Use this as a **speaker guide**: what to say (in plain language) for each slide when presenting to your group (Memory, model training, engineering).

---

## Slide 1 — Title

**What to say:**  
*"This is an overview of the Solo Elderly Agent pipeline — what we have today. It’s relevant for everyone: Memory, model training, and engineering, because each part of the pipeline touches your work."*

**Don’t:** Rush. Let people see the title and subtitle.

---

## Slide 2 — Agenda

**What to say:**  
*"I’ll walk through seven things: who we’re building for, the end-to-end pipeline, where the logic lives in the repo, how we turn conversation and device data into risk tags — that’s the part that matters for model training — then interventions and tools, what we need from Memory, and how we report back to clinicians. At the end I’ll call out handoffs for each team."*

**Don’t:** Read every bullet. Just hit: scenario → pipeline → artifacts → risk tags → interventions → Memory → reporting → handoffs.

---

## Slide 3 — Scenario & Goal

**What to say:**  
*"We’re building for one person: elderly, living alone, no family support. They have a smartwatch that gives us GPS, vitals, and fall detection. We reach out by voice every three days. The goal is to be their main safety net: use that telemetry plus what they say and what we remember to detect risk — falls, very high blood pressure, isolation, not moving enough, low mood — trigger emergency when needed, and nudge daily habits: mobility, mental health, and nutrition."*

**If someone asks “why no family?”:**  
*"There’s no one to call. So the agent has to decide when to dispatch EMS or alert the care team, using rules we’ve defined."*

---

## Slide 4 — End-to-End Pipeline (Diagram)

**What to say:**  
*"This is the full flow, left to right. Three inputs: smartwatch telemetry, the conversation — that’s NLP — and patient memory. Those feed into a risk-tagging step: we combine what the person said with device data and memory to assign tags like ‘sedentary,’ ‘isolation,’ or ‘goal met.’ Those tags drive three kinds of actions: emergency workflow, mobility and isolation interventions — weather, parks, events — and nutrition guidance. Everything ends in a structured report that goes to the PCP and social worker dashboard."*

**Point at the diagram** while you say: inputs → inference (risk tags) → interventions → outputs.

**If someone asks “who runs the risk tagging?”:**  
*"That’s where model training comes in: the model plus our rules map dialogue and telemetry to those tags. The logic for *which* tags and when is in our reference docs; the actual prediction can be your model."*

---

## Slide 5 — Artifacts

**What to say:**  
*"In the repo, there are two main places. The skill file — solo_elderly_skill — is the scenario and orchestration: persona, what we do before each call with Memory and the device API, emergency protocol, adherence flow, and the JSON report schema. The adherence reference — ref_adherence — holds the rules: check-in goals, how we go from NLP and telemetry to risk tags, when we call which MCP tools, nutrition from memory, and what we put in the report. We also have ref_emergency for the full emergency protocol. So: skill = orchestration; refs = the detailed logic."*

**If someone asks “where is Memory?”:**  
*"Memory isn’t a file in this repo — it’s the system you own. We *call* it: we query for complaints, diagnoses, restrictions. So this slide is ‘where *our* logic lives’; Memory is the system we integrate with."*

---

## Slide 6 — Risk Tagging (For Model Training)

**What to say:**  
*"This slide is especially for the model-training folks. The idea is to cross-reference what the person says with device data — GPS, steps, sleep — and output risk tags. For example: if they say ‘I’m just tired’ and steps are under a thousand a day for three days, we tag Risk_Sedentary_Severe. If they say ‘my legs hurt when I walk’ and GPS shows they haven’t left home in four days, we tag Risk_Mobility_Decline. We have tags for depression and isolation, insomnia, and a positive one — Goal_Met_Mobility — when they say they went to the store and GPS backs it up. These tags are the supervised targets: your job is to train and evaluate so that model output plus device data map to exactly these tags."*

**If someone asks “where do these tags come from?”:**  
*"They’re defined in ref_adherence. We can export that section or the full ref as the spec for labeling and evaluation."*

---

## Slide 7 — Interventions & Tools

**What to say:**  
*"When a tag or a trigger fires, we do something. For emergencies — very high BP, hard fall, geofence breach — we get GPS, ask one yes/no question, then dispatch EMS to coordinates, find the nearest ER, and alert PCP and case worker. For mobility and isolation — when we have Risk_Sedentary_Severe or Risk_Depression_Isolation — we call weather; if it’s safe we suggest parks or senior events, if not we suggest something indoors like chair yoga. For nutrition we use Memory: diagnoses, diet notes, restrictions. We give condition-based suggestions — e.g. low sodium for hypertension, small nutrient-dense meals for poor appetite — and we never override what the clinician put in Memory."*

**If someone asks “what’s MCP?”:**  
*"Model Context Protocol — the tools we call for weather, dispatch, parks, ER lookup, etc. Engineering owns wiring those."*

---

## Slide 8 — Memory Interface

**What to say:**  
*"For the Memory team: here’s what we need from you. Before and during each check-in we need recent complaints — e.g. a query like ‘symptoms or complaints in the last seven days’ — for context and for nutrition. We need structured patient facts: diagnoses like hypertension, diabetes, CKD, diet restrictions like low_sodium or renal_diet, and preferences like difficulty cooking or poor appetite. And we need any clinician overrides — e.g. fluid restriction — so the agent can reinforce them and never contradict. On the way out, we can write back a short summary of the check-in — risks, actions taken — so the next cycle has it. So: read for complaints, diagnoses, restrictions, overrides; optional write-back of check-in summary."*

**If someone asks “format?”:**  
*"We can align on a small schema — e.g. how we name diagnoses and restrictions — so our queries and your store match."*

---

## Slide 9 — Reporting & Feedback

**What to say:**  
*"Every check-in produces a structured JSON. It includes patient status — stable, at risk, or critical — current location with lat/lon and context, mobility metrics like days since they left home and average steps, the risk tags we inferred, what we suggested, and whether we raised a social-worker alert and why. That report updates the PCP and social worker dashboard. We also use it to evaluate the pipeline: did the right tags fire? Did we suggest the right interventions? So it’s both clinical output and a feedback loop for improving the system."*

---

## Slide 10 — Next Steps & Handoffs

**What to say:**  
*"Concrete handoffs. Memory: we need reliable read and write for complaints, diagnoses, restrictions, and clinician instructions; optional write-back of a check-in summary. Model training: align on the risk tags we showed — train and evaluate so dialogue plus device data map to those tags; the report fields and tags are your evaluation targets. Engineering: MCP tools — dispatch, ER finder, weather, parks, events — and wiring to the device API and Vector DB. I’m happy to go deeper with any of you after this. Questions?"*

**Then open for Q&A.**

---

## Quick Tips When Presenting

1. **Go slow on the diagram (Slide 4)** — People need a moment to see inputs → inference → interventions → outputs.
2. **Name the teams** — When you hit risk tags, say “for model training”; when you hit Memory, say “for the Memory team.”
3. **One sentence on “why”** — e.g. “We need these tags so the agent knows when to suggest a walk vs when to escalate.”
4. **If you don’t know:** “Good question — I’ll follow up with [Memory / model training / engineering] and get back to you.”
5. **End with next steps** — e.g. “I’ll share the ref docs and this deck; we can set up a short sync with each team to align on interfaces.”

You’ve got this.
