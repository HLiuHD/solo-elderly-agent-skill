# Solo Elderly Skill Demo Kit

This demo lets you present your skill even when production Memory and GPS are not ready.

It uses:
- Mock Memory output (`mock/memory_cases.json`)
- Mock Location output (`mock/location_cases.json`)
- Gemini model (Google AI Studio, free tier, OpenAI-compatible endpoint)
- Google Maps Places API (nearby recommendation by location)
- Deterministic offline fallback so the demo never fails

## 1) Files in this folder

- `demo_runner.py` - run the full demo
- `.env.example` - environment variable template
- `mock/memory_cases.json` - 3 memory scenarios
- `mock/location_cases.json` - 3 location scenarios

## 2) Setup

From PowerShell:

```powershell
cd "c:\Users\henry\Desktop\Agent Skill\demo"
Copy-Item .env.example .env
```

Then edit `.env`:

```env
GEMINI_API_KEY=your_google_ai_studio_key_here
GEMINI_MODEL=gemini-2.0-flash
GOOGLE_MAPS_API_KEY=your_google_maps_api_key_here
```

> If `GEMINI_API_KEY` or `GOOGLE_MAPS_API_KEY` is empty, the demo still runs with fallback behavior.

## 3) Run commands

### A) Default scenario (sedentary/isolation)

```powershell
python demo_runner.py
```

### B) Explicit scenario + user utterance

```powershell
python demo_runner.py --memory-case sedentary_isolation --location-case beijing_home --user-input "I feel tired and did not go out this week."
```

### C) Emergency scenario

```powershell
python demo_runner.py --memory-case emergency_chest_pain --location-case beijing_emergency --user-input "I have chest pain and feel dizzy."
```

### D) Offline-only mode (safe for classroom with unstable network)

```powershell
python demo_runner.py --offline-only --memory-case sedentary_isolation --location-case beijing_home --user-input "I feel lonely and tired."
```

## 4) What the script prints

1. Demo input config
2. Memory snapshot
3. Location snapshot
4. Google Maps nearby place result (if API key available)
5. Final assistant output JSON with:
   - `assistant_message`
   - `risk_tags`
   - `action_plan`
   - `report_json`

This matches your skill design: risk tagging, intervention selection, and structured reporting.

## 5) Suggested live demo script (2-3 minutes)

1. Run Scenario A (sedentary/isolation): show risk tags + nearby place recommendation + nutrition advice.
2. Run Scenario C (emergency): show triage prompt and critical report output.
3. Explain that Memory and GPS are mocked now, but interfaces are the same as production.

## 6) Notes

- Gemini call uses Google's OpenAI-compatible endpoint (`generativelanguage.googleapis.com/v1beta/openai/chat/completions`).
- Google Maps Nearby Search endpoint used:
  `https://maps.googleapis.com/maps/api/place/nearbysearch/json`
- Keyword priority for recommendations: `senior center` first, then `park`.
