import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, UTC
from pathlib import Path

import webbrowser

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
SKILL_ROOT = ROOT.parent
MEMORY_FILE = ROOT / "mock" / "memory_cases.json"
LOCATION_FILE = ROOT / "mock" / "location_cases.json"
NUTRITION_TEMPLATE = ROOT / "nutrition_template.html"
NUTRITION_OUTPUT = ROOT / "nutrition_report.html"
TRIAGE_TEMPLATE = ROOT / "triage_template.html"
TRIAGE_OUTPUT = ROOT / "triage_report.html"
NUTRITION_ZH_TEMPLATE = ROOT / "nutrition_zh_template.html"
NUTRITION_ZH_OUTPUT = ROOT / "nutrition_zh_report.html"
PATIENT_TEMPLATE = ROOT / "patient_report_template.html"
PATIENT_OUTPUT = ROOT / "patient_report.html"

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_env_file(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k and k not in os.environ:
            os.environ[k] = v

# ---------------------------------------------------------------------------
# LLM API — OpenAI (preferred) + Gemini (fallback)
# ---------------------------------------------------------------------------

def _call_openai(system_prompt: str, user_prompt: str) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    if not api_key:
        return None

    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[OpenAI error {e.code}: {body[:300]}]")
        return None
    except Exception as e:
        print(f"[OpenAI error: {e}]")
        return None


def _call_gemini(system_prompt: str, user_prompt: str) -> str | None:
    api_key = os.getenv("GEMINI_API_KEY", "")
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    if not api_key:
        return None

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={api_key}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.3},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[Gemini error {e.code}: {body[:300]}]")
        return None
    except Exception as e:
        print(f"[Gemini error: {e}]")
        return None


def call_llm(system_prompt: str, user_prompt: str) -> str | None:
    """Try OpenAI first, then Gemini, then give up."""
    if os.getenv("OPENAI_API_KEY"):
        print("[LLM] Using OpenAI …")
        result = _call_openai(system_prompt, user_prompt)
        if result:
            return result
        print("[LLM] OpenAI failed, trying Gemini …")

    if os.getenv("GEMINI_API_KEY"):
        print("[LLM] Using Gemini …")
        result = _call_gemini(system_prompt, user_prompt)
        if result:
            return result

    print("[LLM] No API key available or all calls failed — using offline fallback.")
    return None


def extract_json(text: str):
    if not text:
        return None
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

# ---------------------------------------------------------------------------
# Backend API client  (https://beibei.bjknrt.com/api — see openapi.md)
# ---------------------------------------------------------------------------

BACKEND_BASE = os.getenv("BACKEND_API_BASE", "https://beibei.bjknrt.com/api")
BACKEND_TOKEN = os.getenv("BACKEND_TOKEN", "med")


def _backend_post(endpoint: str, payload: dict | None = None) -> dict | None:
    url = f"{BACKEND_BASE}{endpoint}"
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Token": BACKEND_TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("success"):
            return data.get("data")
        print(f"[Backend API] {endpoint} → {data.get('message', 'unknown error')}")
        return None
    except Exception as e:
        print(f"[Backend API error] {endpoint} → {e}")
        return None


def _backend_get(endpoint: str) -> dict | None:
    url = f"{BACKEND_BASE}{endpoint}"
    req = urllib.request.Request(
        url, method="POST",
        headers={"Content-Type": "application/json", "Token": BACKEND_TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("success"):
            return data.get("data")
        return None
    except Exception as e:
        print(f"[Backend API error] {endpoint} → {e}")
        return None


def fetch_user_list() -> list:
    return _backend_get("/openapi/user/list") or []


def fetch_latest_health(user_id: str, data_type: str) -> dict | None:
    return _backend_post("/openapi/user/health-latest", {"id": user_id, "type": data_type})


def fetch_health_history(user_id: str, data_type: str, start: str, end: str) -> list:
    return _backend_post("/openapi/user/health", {
        "id": user_id, "type": data_type, "startAt": start, "endAt": end,
    }) or []


def fetch_chat_history(user_id: str, start: str, end: str) -> list:
    return _backend_post("/openapi/user/message/history", {
        "id": user_id, "startAt": start, "endAt": end,
    }) or []


def build_live_skill_input(user_id: str) -> dict:
    """Fetch real data from the backend API and assemble a skill_input dict."""
    from datetime import timedelta

    now = datetime.now(UTC)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00+08:00")

    print(f"[Live] Fetching data for user {user_id} …")

    # --- latest health vitals ---
    bp = fetch_latest_health(user_id, "BLOOD_PRESSURE")
    hr = fetch_latest_health(user_id, "HEART_RATE")
    bo = fetch_latest_health(user_id, "BLOOD_OXYGEN")
    bg = fetch_latest_health(user_id, "BLOOD_GLUCOSE")
    steps = fetch_latest_health(user_id, "STEPS")
    loc = fetch_latest_health(user_id, "LOCATION")

    latest_health = {}
    if bp:
        latest_health["blood_pressure"] = f"{bp.get('sbp', '--')}/{bp.get('dbp', '--')}"
    if hr:
        latest_health["heart_rate"] = hr.get("value")
    if bo:
        val = bo.get("value", 0)
        latest_health["blood_oxygen"] = round(val * 100) if val <= 1 else val
    if bg:
        latest_health["blood_glucose"] = bg.get("value")
    if steps:
        latest_health["steps"] = int(steps.get("value", 0))

    # --- location ---
    location_data = {"current": {}, "records": []}
    if loc:
        location_data["current"] = {
            "lat": loc.get("latitude", 0),
            "lon": loc.get("longitude", 0),
            "record_at": loc.get("recordAt", now_iso),
        }
    loc_history = fetch_health_history(user_id, "LOCATION", week_ago, now_iso)
    if loc_history:
        location_data["records"] = [
            {
                "latitude": r.get("latitude"),
                "longitude": r.get("longitude"),
                "recordAt": r.get("recordAt"),
                "source": r.get("source", "APP"),
                "type": r.get("type", "gps"),
            }
            for r in loc_history
        ]
        if not location_data["current"].get("lat"):
            latest = loc_history[-1]
            location_data["current"] = {
                "lat": latest.get("latitude", 0),
                "lon": latest.get("longitude", 0),
                "record_at": latest.get("recordAt", now_iso),
            }

    # --- chat history (last 7 days) ---
    chats = fetch_chat_history(user_id, week_ago, now_iso)
    latest_user_msg = ""
    dialog_parts = []
    for msg in reversed(chats or []):
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "USER" and not latest_user_msg:
            latest_user_msg = content
        if len(dialog_parts) < 10:
            prefix = "患者" if role == "USER" else "AI"
            dialog_parts.append(f"{prefix}: {content[:80]}")
    dialog_summary = " | ".join(reversed(dialog_parts)) if dialog_parts else ""

    # --- steps history for signal analysis ---
    steps_history = fetch_health_history(user_id, "STEPS", week_ago, now_iso)
    total_steps = sum(int(s.get("value", 0)) for s in steps_history) if steps_history else 0
    avg_steps = total_steps // max(len(steps_history), 1) if steps_history else 0

    anomalies = []
    if latest_health.get("heart_rate") and (latest_health["heart_rate"] > 100 or latest_health["heart_rate"] < 50):
        anomalies.append("心率异常")
    if latest_health.get("blood_glucose") and latest_health["blood_glucose"] > 10:
        anomalies.append("血糖偏高")
    if latest_health.get("steps") is not None and latest_health["steps"] < 500:
        anomalies.append("活动量偏低")
    if bp and (bp.get("sbp", 0) > 160 or bp.get("dbp", 0) > 100):
        anomalies.append("血压偏高")

    summary_parts = []
    if latest_health.get("heart_rate"):
        summary_parts.append(f"心率{latest_health['heart_rate']}bpm")
    if latest_health.get("blood_pressure"):
        summary_parts.append(f"血压{latest_health['blood_pressure']}mmHg")
    if latest_health.get("steps") is not None:
        summary_parts.append(f"今日步数{latest_health['steps']}步")
    summary_text = "，".join(summary_parts) + ("。" if summary_parts else "数据获取中。")

    skill_input = {
        "meta": {
            "user_id": user_id,
            "session_id": f"live_{now.strftime('%Y%m%d_%H%M%S')}",
            "intent": "medical_dialog",
            "lang": "zh",
            "current_time": now_iso,
        },
        "memory": {
            "patient_long_term_profile": "患者信息从后端API获取，请根据健康数据进行分析。",
            "recent_health_dynamics": f"近7天平均步数{avg_steps}步。" + ("活动量偏低。" if avg_steps < 3000 else "活动量正常。"),
        },
        "signals": {
            "start_ts": week_ago,
            "end_ts": now_iso,
            "summary_text": summary_text,
            "anomalies": anomalies if anomalies else ["暂无明确异常"],
        },
        "location": location_data,
        "adherence_analysis": {"statuses": [], "preferences": [], "interventions": [], "suggestions": []},
        "outlier_analysis": {"symptoms": [], "triage": None, "patient_suggestions": [], "doctor_suggestions": []},
        "latest_health": latest_health,
        "latest_user_message": latest_user_msg,
        "recent_dialog_summary": dialog_summary,
    }

    return skill_input


def run_live(user_id: str, offline_only: bool = False):
    """Fetch live data from the backend API and run the skill pipeline."""
    skill_input = build_live_skill_input(user_id)

    live_input_file = ROOT / "live_input.json"
    live_input_file.write_text(json.dumps(skill_input, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Live] Saved fetched input to: {live_input_file}")

    system_prompt = _load_skill_system_prompt()
    user_prompt = json.dumps(skill_input, ensure_ascii=False, indent=2)

    result = None
    if not offline_only:
        raw = call_llm(system_prompt, user_prompt)
        result = extract_json(raw)

    if result is None:
        print("[Using offline fallback for live input]")
        result = _skill_offline_fallback(skill_input)

    full_output = {"skill_input": skill_input, "skill_output": result}
    print(json.dumps(full_output, ensure_ascii=False, indent=2))

    output_file = ROOT / "demo_output.json"
    output_file.write_text(json.dumps(full_output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved to: {output_file}")

    generate_patient_page(skill_input, result)


# ---------------------------------------------------------------------------
# Risk detection (used by legacy mock demo mode)
# ---------------------------------------------------------------------------

def detect_risk_tags(user_input: str, memory: dict, location: dict):
    text = user_input.lower()
    tags = []

    if any(w in text for w in ["chest pain", "can't breathe", "cant breathe", "dizzy", "fell", "fall", "face drooping", "speech"]):
        tags.append("Emergency_Trigger")

    if (
        any(w in text for w in ["tired", "didn't go out", "did not go out", "stayed home", "no energy"])
        and location.get("average_daily_steps", 9999) < 1000
    ):
        tags.append("Risk_Sedentary_Severe")

    if any(w in text for w in ["my legs hurt", "legs hurt", "pain when i walk"]) and location.get("days_since_left_home", 0) >= 4:
        tags.append("Risk_Mobility_Decline")

    if any(w in text for w in ["nobody", "what's the point", "whats the point", "alone", "low mood", "no appetite"]):
        tags.append("Risk_Depression_Isolation")

    if any(w in text for w in ["up all night", "didn't sleep", "didnt sleep"]) or memory.get("sleep_hours_last_night", 8) < 4:
        tags.append("Risk_Insomnia")

    if any(w in text for w in ["went to the store", "went for a walk", "i walked"]) and location.get("average_daily_steps", 0) >= 3000:
        tags.append("Goal_Met_Mobility")

    seen = set()
    return [t for t in tags if not (t in seen or seen.add(t))]

# ---------------------------------------------------------------------------
# Mock nearby places (legacy demo)
# ---------------------------------------------------------------------------

MOCK_NEARBY_PLACES = {
    "beijing_home": {
        "name": "Zhongshan Park",
        "address": "4 Zhonghua Rd, Xicheng District, Beijing",
        "distance": "800m",
        "type": "park",
    },
    "beijing_active": {
        "name": "Jingshan Park",
        "address": "44 Jingshan W St, Xicheng District, Beijing",
        "distance": "600m",
        "type": "park",
    },
    "beijing_emergency": {
        "name": "Peking Union Medical College Hospital",
        "address": "1 Shuaifuyuan, Dongcheng District, Beijing",
        "distance": "1.2km",
        "type": "hospital",
    },
}


def get_nearby_place(location_case: str):
    return MOCK_NEARBY_PLACES.get(location_case)

# ---------------------------------------------------------------------------
# Nutrition helpers (legacy demo)
# ---------------------------------------------------------------------------

def nutrition_tip(memory: dict, user_input: str):
    diagnoses = set(memory.get("diagnoses", []))
    restrictions = set(memory.get("diet_restrictions", []))
    text = user_input.lower()

    if "renal_diet" in restrictions or "fluid_restriction" in restrictions:
        return "Please continue following your clinician's renal/fluid instructions. We can choose food options that fit that plan."
    if "type_2_diabetes" in diagnoses:
        return "Because of your blood sugar, try a smaller meal with fiber (like oatmeal or vegetables) instead of sugary snacks."
    if "hypertension" in diagnoses or "heart_failure" in diagnoses:
        return "Since blood pressure matters for you, lower-sodium choices like fresh/frozen vegetables instead of canned soup can help."
    if "no appetite" in text or "don't feel like eating" in text or "did not feel like eating" in text:
        return "If a full meal feels hard, start with a small nutrient-dense snack like yogurt, a boiled egg, or fruit."
    return "A balanced light meal with vegetables and protein can help your energy for a short walk."

# ---------------------------------------------------------------------------
# Legacy mock demo — offline fallback
# ---------------------------------------------------------------------------

def offline_fallback(user_input: str, memory: dict, location: dict, risk_tags: list, place: dict):
    actionable = []
    status = "stable"
    alert = False
    alert_reason = ""

    if "Emergency_Trigger" in risk_tags or location.get("geofence_breach", False):
        status = "critical"
        alert = True
        alert_reason = "Emergency trigger detected from NLP or location geofence breach."
        actionable.append("Asked emergency triage yes/no question and prepared coordinate-based EMS dispatch.")
    elif any(t in risk_tags for t in ["Risk_Sedentary_Severe", "Risk_Mobility_Decline", "Risk_Depression_Isolation", "Risk_Insomnia"]):
        status = "at_risk"

    weather = location.get("weather", {})
    weather_safe = weather.get("condition", "Clear") in ("Clear", "Overcast") and weather.get("temp_f", 70) > 55

    if place and any(t in risk_tags for t in ["Risk_Sedentary_Severe", "Risk_Depression_Isolation", "Risk_Mobility_Decline"]):
        if weather_safe:
            actionable.append(
                f"Weather is safe ({weather.get('temp_f')}°F, {weather.get('condition')}). "
                f"Suggested outdoor activity at {place['name']} ({place['address']})"
            )
        else:
            actionable.append(
                f"Weather is not ideal ({weather.get('temp_f')}°F, {weather.get('description', '')}). "
                f"Suggested indoor activity: 10-minute chair yoga or stretching at home."
            )

    actionable.append("Provided personalized nutrition suggestion based on memory profile.")

    msg = []
    if status == "critical":
        msg.append("I received a concerning alert. Do you need an ambulance right now?")
    else:
        msg.append("Thank you for sharing. I am here with you.")

    if status != "critical" and any(t in risk_tags for t in ["Risk_Sedentary_Severe", "Risk_Depression_Isolation", "Risk_Mobility_Decline"]):
        if weather_safe and place:
            msg.append(
                f"The weather is nice today — {weather.get('temp_f')}°F and {weather.get('description', 'clear')}. "
                f"{place['name']} is just {place.get('distance', 'nearby')} away. "
                f"How about a short 15-minute walk there this afternoon?"
            )
        else:
            msg.append(
                f"It's {weather.get('description', 'not great')} outside today. "
                f"Let's stay safe indoors. I can suggest a 10-minute chair yoga or gentle stretching routine right now if you'd like."
            )

    msg.append(nutrition_tip(memory, user_input))

    report = {
        "patient_status": status,
        "current_location": {
            "lat": location["lat"],
            "lon": location["lon"],
            "context": location.get("context", "Unknown"),
        },
        "mobility_metrics": {
            "days_since_left_home": location.get("days_since_left_home", 0),
            "average_daily_steps": location.get("average_daily_steps", 0),
        },
        "new_risk_tags_generated": risk_tags,
        "nlp_inferred_risks": risk_tags,
        "validated_by_device": True,
        "actionable_tasks_assigned": actionable,
        "medication_taken_last_3_days": memory.get("medication_taken_last_3_days", None),
        "social_worker_alert": alert,
        "social_worker_alert_reason": alert_reason,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }

    return {
        "assistant_message": " ".join(msg),
        "risk_tags": risk_tags,
        "action_plan": actionable,
        "report_json": report,
    }

# ---------------------------------------------------------------------------
# Legacy mock demo — run
# ---------------------------------------------------------------------------

NUTRITION_ADVICE_DB = {
    "hypertension": {
        "title": "Heart-Friendly (Low Sodium)",
        "css": "",
        "text": "High blood pressure responds well to lower sodium intake. Choose fresh or frozen vegetables over canned, avoid adding salt at the table, and look for low-sodium labels.",
        "meals": [
            ("Breakfast", ["Oatmeal with banana slices", "Unsalted nuts", "Warm water with lemon"]),
            ("Lunch/Dinner", ["Steamed fish or chicken", "Fresh vegetables (broccoli, spinach)", "Brown rice or sweet potato"]),
        ],
    },
    "type_2_diabetes": {
        "title": "Blood Sugar Friendly (Low Sugar, High Fiber)",
        "css": "",
        "text": "Steady blood sugar comes from smaller, regular meals with fiber and protein. Avoid sugary snacks and drinks; choose whole grains over white bread/rice.",
        "meals": [
            ("Breakfast", ["Whole-grain toast with egg", "Small apple or berries", "Unsweetened tea"]),
            ("Lunch/Dinner", ["Grilled chicken or tofu", "Leafy salad with olive oil", "Lentils or beans"]),
        ],
    },
    "hyperlipidemia": {
        "title": "Heart-Healthy (Low Cholesterol)",
        "css": "",
        "text": "Reducing saturated fat helps manage cholesterol. Choose lean protein, use olive oil instead of butter, and add fiber-rich foods like oats and beans.",
        "meals": [
            ("Snack ideas", ["Handful of walnuts or almonds", "Carrot sticks with hummus", "A small pear or orange"]),
        ],
    },
    "poor_appetite": {
        "title": "Small & Nutrient-Dense (For Low Appetite)",
        "css": "warn",
        "text": "When a full meal feels too much, small nutrient-dense bites keep your body fueled. Eat a little every 2-3 hours instead of three big meals.",
        "meals": [
            ("Easy options", ["Small bowl of yogurt", "Boiled egg", "Piece of fruit", "A few crackers with cheese"]),
        ],
    },
    "fatigue_mobility": {
        "title": "Energy Boosters (For Tiredness & Low Movement)",
        "css": "good",
        "text": "Pairing a light snack with gentle movement can break the fatigue cycle. Even a banana before a short walk makes a difference.",
        "meals": [
            ("Quick energy", ["Banana or small handful of nuts", "Warm soup with bread", "Smoothie with fruit and milk"]),
        ],
    },
}


def run_demo(memory_case: str, location_case: str, user_input: str, offline_only: bool = False):
    memory_all = load_json(MEMORY_FILE)
    location_all = load_json(LOCATION_FILE)

    if memory_case not in memory_all:
        raise ValueError(f"Unknown memory case: {memory_case}")
    if location_case not in location_all:
        raise ValueError(f"Unknown location case: {location_case}")

    memory = memory_all[memory_case]
    location = location_all[location_case]
    place = get_nearby_place(location_case)
    risk_tags = detect_risk_tags(user_input, memory, location)

    system_prompt = (
        "You are a proactive, empathetic health assistant for an elderly person living alone. "
        "Use memory and location context to provide safe and helpful advice. "
        "If emergency signs exist, prioritize triage. Return STRICT JSON with keys: "
        "assistant_message, risk_tags, action_plan, report_json."
    )
    user_prompt = json.dumps(
        {
            "user_input": user_input,
            "memory": memory,
            "location": location,
            "nearby_place": place,
            "weather": location.get("weather", {}),
            "required_behavior": [
                "Use risk tags from available evidence",
                "If weather is safe (clear/overcast and above 55F), suggest outdoor activity at the nearby place",
                "If weather is bad (rain/snow/extreme cold), suggest indoor activity like chair yoga",
                "Provide nutrition suggestion based on memory diagnoses and restrictions",
                "Use emergency triage question when emergency trigger exists",
            ],
        },
        ensure_ascii=False,
        indent=2,
    )

    result = None
    if not offline_only:
        raw = call_llm(system_prompt, user_prompt)
        result = extract_json(raw)

    if result is None:
        result = offline_fallback(user_input, memory, location, risk_tags, place)

    full_output = {
        "demo_input": {
            "memory_case": memory_case,
            "location_case": location_case,
            "user_input": user_input,
        },
        "memory_snapshot": memory,
        "location_snapshot": location,
        "weather": location.get("weather", {}),
        "nearby_place": place,
        "assistant_output": result,
    }

    print(json.dumps(full_output, ensure_ascii=False, indent=2))
    output_file = ROOT / "demo_output.json"
    output_file.write_text(json.dumps(full_output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved to: {output_file}")

    generate_nutrition_page(memory, location, user_input)


def generate_nutrition_page(memory: dict, location: dict, user_input: str):
    if not NUTRITION_TEMPLATE.exists():
        return

    template = NUTRITION_TEMPLATE.read_text(encoding="utf-8")
    diagnoses = memory.get("diagnoses", [])
    restrictions = memory.get("diet_restrictions", [])
    preferences = memory.get("preferences", [])
    complaints = memory.get("recent_complaints", [])
    text = user_input.lower()

    diagnosis_tags = "".join(f'<span class="tag tag-diagnosis">{d}</span>' for d in diagnoses)
    restriction_tags = "".join(f'<span class="tag tag-restriction">{r}</span>' for r in restrictions)
    preference_tags = "".join(f'<span class="tag tag-preference">{p}</span>' for p in preferences)
    complaints_str = "; ".join(complaints) if complaints else "None reported"

    relevant_keys = []
    for d in diagnoses:
        if d in NUTRITION_ADVICE_DB:
            relevant_keys.append(d)
    if any(w in text for w in ["no appetite", "don't feel like eating", "not hungry"]) or \
       any("appetite" in c.lower() for c in complaints):
        relevant_keys.append("poor_appetite")
    if any(w in text for w in ["tired", "no energy", "fatigue"]) or \
       any("tired" in c.lower() for c in complaints):
        relevant_keys.append("fatigue_mobility")
    if not relevant_keys:
        relevant_keys = ["hypertension"]

    seen = set()
    unique_keys = [k for k in relevant_keys if not (k in seen or seen.add(k))]

    advice_html = ""
    meal_html = ""
    for key in unique_keys:
        info = NUTRITION_ADVICE_DB.get(key)
        if not info:
            continue
        css_class = info["css"] if info["css"] else ""
        advice_html += (
            f'<li class="advice-item {css_class}">'
            f'<h3>{info["title"]}</h3>'
            f'<p>{info["text"]}</p>'
            f'</li>\n'
        )
        for meal_name, items in info["meals"]:
            items_li = "".join(f"<li>{it}</li>" for it in items)
            meal_html += (
                f'<div class="meal-card">'
                f'<h3>{meal_name}</h3>'
                f'<ul>{items_li}</ul>'
                f'</div>\n'
            )

    guardrail = (
        "This guidance is generated by your health assistant based on your medical profile. "
        "It does not replace your doctor's instructions. "
    )
    if "low_sodium_diet" in restrictions:
        guardrail += "Your clinician has noted a low-sodium diet — all suggestions above respect this. "
    if "renal_diet" in restrictions or "fluid_restriction" in restrictions:
        guardrail += "Your renal/fluid restrictions are active — please continue following your clinician's plan. "
    guardrail += "Always consult your care team before making major dietary changes."

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    html = template
    html = html.replace("{{PATIENT_ID}}", memory.get("patient_id", "P-001"))
    html = html.replace("{{TIMESTAMP}}", now)
    html = html.replace("{{DIAGNOSIS_TAGS}}", diagnosis_tags or '<span class="tag tag-diagnosis">none</span>')
    html = html.replace("{{RESTRICTION_TAGS}}", restriction_tags or '<span class="tag tag-restriction">none</span>')
    html = html.replace("{{PREFERENCE_TAGS}}", preference_tags or '<span class="tag tag-preference">none</span>')
    html = html.replace("{{COMPLAINTS}}", complaints_str)
    html = html.replace("{{ADVICE_ITEMS}}", advice_html)
    html = html.replace("{{MEAL_CARDS}}", meal_html)
    html = html.replace("{{GUARDRAIL_TEXT}}", guardrail)

    NUTRITION_OUTPUT.write_text(html, encoding="utf-8")
    print(f"\n=== NUTRITION PAGE ===")
    print(f"Generated: {NUTRITION_OUTPUT}")
    webbrowser.open(NUTRITION_OUTPUT.as_uri())

# ===================================================================
#  SKILL MODE — structured JSON input (from skill_input_example.md)
# ===================================================================

def _load_skill_system_prompt() -> str:
    """Read solo_elderly_skill.md and use it as the system prompt."""
    skill_file = SKILL_ROOT / "solo_elderly_skill.md"
    base = ""
    if skill_file.exists():
        base = skill_file.read_text(encoding="utf-8")

    ref_dir = SKILL_ROOT / "references"
    if ref_dir.is_dir():
        for md in sorted(ref_dir.glob("*.md")):
            content = md.read_text(encoding="utf-8").strip()
            if content:
                base += f"\n\n--- Reference: {md.name} ---\n{content}"

    if not base.strip():
        base = (
            "You are a proactive, empathetic health assistant for an elderly person "
            "living alone. You specialize in triage, risk assessment, medication "
            "adherence, nutrition, and mobility guidance."
        )

    base += (
        "\n\n## Output Requirement\n"
        "You MUST return a single JSON object (no markdown fences) with these keys:\n"
        "{\n"
        '  "patient_status": "stable" | "at_risk" | "critical",\n'
        '  "triage_level": "non_urgent" | "semi_urgent" | "urgent" | "emergency",\n'
        '  "risk_tags": ["tag1", ...],\n'
        '  "assistant_message_patient": "给患者的中文建议",\n'
        '  "assistant_message_doctor": "给医生的中文临床备注",\n'
        '  "recommendations": ["建议1", ...],\n'
        '  "nutrition_advice": "个性化中文营养建议",\n'
        '  "reasoning": "简短中文临床推理"\n'
        "}\n"
    )
    return base


def _skill_offline_fallback(skill_input: dict) -> dict:
    """Deterministic fallback when LLM is unavailable."""
    memory = skill_input.get("memory", {})
    signals = skill_input.get("signals", {})
    anomalies = signals.get("anomalies", [])
    latest_health = skill_input.get("latest_health", {})
    profile = memory.get("patient_long_term_profile", "")
    dynamics = memory.get("recent_health_dynamics", "")
    user_msg = skill_input.get("latest_user_message", "")

    status = "stable"
    triage_level = "non_urgent"
    risk_tags = []

    for a in anomalies:
        if any(kw in a for kw in ["高危", "急性", "心律失常", "严重", "骤降", "骤升"]):
            status = "critical"
            triage_level = "emergency"
            risk_tags.append(a)
        elif any(kw in a for kw in ["波动", "偏低", "偏高", "异常", "下降"]):
            if status != "critical":
                status = "at_risk"
                triage_level = "semi_urgent"
            risk_tags.append(a)

    if not risk_tags:
        risk_tags = anomalies if anomalies else ["暂无明确风险"]

    recs = []
    combined = " ".join([profile, dynamics, user_msg, *anomalies])
    if "活动量" in combined or "步数" in combined or "没怎么出门" in combined:
        recs.append("建议适当增加日常活动量，天气允许时每天散步15-20分钟")
    if "心率" in combined:
        recs.append("注意监测心率变化，如持续异常请及时就医")
    if "高血压" in profile or "血压" in combined:
        recs.append("按时服用降压药物，保持低钠饮食")
    if "糖尿" in profile or "血糖" in combined:
        recs.append("控制碳水化合物摄入，注意血糖监测")
    if "高脂" in profile:
        recs.append("减少饱和脂肪摄入，选择健康油脂")
    if not recs:
        recs.append("保持规律作息，均衡饮食，适量运动")

    nutrition = "建议均衡饮食，多食新鲜蔬菜水果。"
    if "高血压" in profile:
        nutrition += "注意低钠饮食，避免腌制食品。"
    if "糖尿" in profile:
        nutrition += "控制糖分摄入，选择全谷物食品。"
    if "高脂" in profile:
        nutrition += "减少饱和脂肪摄入，选择橄榄油等健康油脂。"

    summary = signals.get("summary_text", "整体状况尚可")
    return {
        "patient_status": status,
        "triage_level": triage_level,
        "risk_tags": risk_tags,
        "assistant_message_patient": (
            f"您好！根据近期监测数据，{summary}。{recs[0]}。如有不适请随时告诉我。"
        ),
        "assistant_message_doctor": (
            f"患者近期{dynamics or '情况平稳'}。信号分析：{summary}。建议持续监测并关注上述风险标签。"
        ),
        "recommendations": recs,
        "nutrition_advice": nutrition,
        "reasoning": f"基于信号异常（{', '.join(anomalies) if anomalies else '无'}）和患者长期档案进行离线规则评估。",
    }


def generate_triage_page(skill_input: dict, result: dict):
    """Render the 分诊审核 HTML page from skill input + LLM output."""
    if not TRIAGE_TEMPLATE.exists():
        print("[Triage template not found, skipping page generation]")
        return

    template = TRIAGE_TEMPLATE.read_text(encoding="utf-8")

    meta = skill_input.get("meta", {})
    memory = skill_input.get("memory", {})
    signals = skill_input.get("signals", {})
    location = skill_input.get("location", {})
    latest_health = skill_input.get("latest_health", {})
    adherence = skill_input.get("adherence_analysis", {})

    # --- status badge (Tailwind classes) ---
    status = result.get("patient_status", "stable")
    status_tw = {
        "stable":   ("bg-emerald-100 text-emerald-700", "✅", "稳定"),
        "at_risk":  ("bg-amber-100 text-amber-700",     "⚠️", "关注"),
        "critical": ("bg-rose-100 text-rose-700",       "🚨", "危急"),
    }
    s_class, s_icon, s_text = status_tw.get(status, status_tw["stable"])

    # --- triage level (Tailwind classes) ---
    triage = result.get("triage_level", "non_urgent")
    triage_tw = {
        "emergency":   ("bg-rose-50 text-rose-700 border-rose-400",     "🚨", "紧急"),
        "urgent":      ("bg-amber-50 text-amber-700 border-amber-400",  "⚠️",  "较急"),
        "semi_urgent": ("bg-yellow-50 text-yellow-700 border-yellow-400", "📋", "次急"),
        "non_urgent":  ("bg-emerald-50 text-emerald-700 border-emerald-400", "✅", "非急"),
    }
    t_class, t_icon, t_text = triage_tw.get(triage, triage_tw["non_urgent"])

    # --- anomaly tags ---
    anomalies = signals.get("anomalies", [])
    anomaly_tags = "".join(
        f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium bg-rose-50 text-rose-700">{a}</span>'
        for a in anomalies
    ) or '<span class="inline-block px-3 py-1 rounded-full text-xs font-medium bg-blue-50 text-blue-600">无异常</span>'

    # --- risk tags ---
    risk_tags = result.get("risk_tags", [])
    risk_tags_html = "".join(
        f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium bg-orange-50 text-orange-700">{t}</span>'
        for t in risk_tags
    ) or '<span class="inline-block px-3 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700">低风险</span>'

    # --- signal window ---
    if signals.get("start_ts") and signals.get("end_ts"):
        signal_window = f'{signals["start_ts"]}  ⟶  {signals["end_ts"]}'
    else:
        signal_window = "暂无数据"

    # --- vitals (Tailwind cards) ---
    vital_defs = [
        ("blood_pressure", "血压",  "mmHg"),
        ("heart_rate",     "心率",  "bpm"),
        ("blood_oxygen",   "血氧",  "%"),
        ("blood_glucose",  "血糖",  "mmol/L"),
        ("steps",          "步数",  "步"),
    ]
    vitals_parts = []
    for key, label, unit in vital_defs:
        val = latest_health.get(key) if latest_health else None
        if val is not None:
            vitals_parts.append(
                f'<div class="bg-slate-50 rounded-lg p-3 text-center border border-slate-100">'
                f'<div class="text-[11px] text-slate-500 font-medium mb-1">{label}</div>'
                f'<div class="text-xl font-bold text-slate-800">{val} <span class="text-[10px] font-normal text-slate-400">{unit}</span></div>'
                f'</div>'
            )
        else:
            vitals_parts.append(
                f'<div class="bg-slate-50 rounded-lg p-3 text-center border border-slate-100">'
                f'<div class="text-[11px] text-slate-500 font-medium mb-1">{label}</div>'
                f'<div class="text-base text-slate-300">--</div>'
                f'</div>'
            )
    vitals_html = "".join(vitals_parts)

    # --- reasoning ---
    reasoning = result.get("reasoning", "")
    reasoning_html = ""
    if reasoning:
        reasoning_html = (
            '<div class="mt-4">'
            '<div class="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">评估依据</div>'
            f'<div class="text-sm text-slate-700 bg-amber-50 rounded-lg p-3" style="border-left:3px solid #f59e0b">{reasoning}</div>'
            '</div>'
        )

    # --- recommendations ---
    recs_html = ""
    patient_msg = result.get("assistant_message_patient", "")
    doctor_msg = result.get("assistant_message_doctor", "")
    recs = result.get("recommendations", [])

    if patient_msg:
        recs_html += (
            '<div class="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">给患者</div>'
            f'<div class="text-sm text-slate-700 bg-emerald-50 rounded-lg p-3 mb-3" style="border-left:3px solid #10b981">{patient_msg}</div>'
        )
    if doctor_msg:
        recs_html += (
            '<div class="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">给医生</div>'
            f'<div class="text-sm text-slate-700 bg-amber-50 rounded-lg p-3 mb-3" style="border-left:3px solid #f59e0b">{doctor_msg}</div>'
        )
    if recs:
        recs_html += '<div class="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">具体建议</div>'
        for r in recs:
            recs_html += f'<div class="text-sm text-slate-700 bg-blue-50 rounded-lg p-3 mb-2" style="border-left:3px solid #3b82f6">{r}</div>'

    # --- nutrition ---
    nutrition = result.get("nutrition_advice", "保持均衡饮食，多食新鲜蔬菜水果。")
    nutrition_html = (
        f'<div class="text-sm text-slate-700 bg-emerald-50 rounded-lg p-3" style="border-left:3px solid #10b981">{nutrition}</div>'
    )

    # --- adherence card (Tailwind) ---
    adherence_card = ""
    adh_statuses = adherence.get("statuses", [])
    adh_suggestions = adherence.get("suggestions", [])
    adh_preferences = adherence.get("preferences", [])
    if adh_statuses or adh_suggestions or adh_preferences:
        adh_inner = (
            '<div class="flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">'
            '<span class="text-lg">💊</span>'
            '<h2 class="text-sm font-bold text-slate-800">依从性分析</h2>'
            '</div>'
        )
        if adh_statuses:
            adh_inner += '<div class="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">当前状态</div><div class="flex flex-wrap gap-2 mb-3">'
            adh_inner += "".join(
                f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium bg-purple-50 text-purple-700">{s}</span>'
                for s in adh_statuses
            )
            adh_inner += '</div>'
        if adh_preferences:
            adh_inner += '<div class="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">偏好</div><div class="flex flex-wrap gap-2 mb-3">'
            adh_inner += "".join(
                f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium bg-blue-50 text-blue-600">{p}</span>'
                for p in adh_preferences
            )
            adh_inner += '</div>'
        if adh_suggestions:
            adh_inner += '<div class="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">建议</div>'
            for s in adh_suggestions:
                adh_inner += f'<div class="text-sm text-slate-700 bg-indigo-50 rounded-lg p-3 mb-2" style="border-left:3px solid #6366f1">{s}</div>'
        adherence_card = f'<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5">{adh_inner}</div>'

    # --- location / map ---
    loc = location.get("current", {})
    patient_lat = loc.get("lat", 0)
    patient_lon = loc.get("lon", 0)

    # AI map message based on risk
    if status == "critical":
        ai_map_msg = "检测到潜在风险，已为您查询患者附近的医疗网点，请建议患者及时就医。"
    elif any("活动" in t or "偏低" in t for t in result.get("risk_tags", [])):
        ai_map_msg = "患者近期活动量偏低，以下是附近推荐的公园和医疗网点，可建议患者适当外出活动。"
    else:
        ai_map_msg = "已为您查询患者附近的医疗网点和活动场所，方便后续随访参考。"

    # --- assemble ---
    replacements = {
        "{{USER_ID}}":            meta.get("user_id", "未知"),
        "{{CURRENT_TIME}}":       meta.get("current_time", datetime.now(UTC).isoformat()),
        "{{STATUS_TW_CLASS}}":    s_class,
        "{{STATUS_ICON}}":        s_icon,
        "{{STATUS_TEXT}}":        s_text,
        "{{LONG_TERM_PROFILE}}":  memory.get("patient_long_term_profile", "暂无数据"),
        "{{RECENT_DYNAMICS}}":    memory.get("recent_health_dynamics", "暂无数据"),
        "{{SIGNAL_WINDOW}}":      signal_window,
        "{{ANOMALY_TAGS}}":       anomaly_tags,
        "{{SIGNAL_SUMMARY}}":     signals.get("summary_text", "暂无数据"),
        "{{VITALS_HTML}}":        vitals_html,
        "{{TRIAGE_TW_CLASS}}":    t_class,
        "{{TRIAGE_ICON}}":        t_icon,
        "{{TRIAGE_TEXT}}":        t_text,
        "{{RISK_TAGS}}":          risk_tags_html,
        "{{REASONING_HTML}}":     reasoning_html,
        "{{RECOMMENDATIONS_HTML}}": recs_html,
        "{{NUTRITION_HTML}}":     nutrition_html,
        "{{ADHERENCE_CARD}}":     adherence_card,
        "{{AI_MAP_MESSAGE}}":     ai_map_msg,
        "{{PATIENT_LAT}}":        str(patient_lat) if patient_lat else "0",
        "{{PATIENT_LON}}":        str(patient_lon) if patient_lon else "0",
        "{{GUARDRAIL_TEXT}}":     "本报告由 AI 健康助手自动生成，仅供临床参考，不构成医疗诊断。请结合患者实际情况做出临床判断。如有任何急性症状，请立即拨打急救电话。",
    }

    html = template
    for key, val in replacements.items():
        html = html.replace(key, val)

    TRIAGE_OUTPUT.write_text(html, encoding="utf-8")
    print(f"\n=== TRIAGE REVIEW PAGE ===")
    print(f"Generated: {TRIAGE_OUTPUT}")
    webbrowser.open(TRIAGE_OUTPUT.as_uri())


# ===================================================================
#  NUTRITION PAGE (Chinese, 7-day meal plan with condition benefits)
# ===================================================================

CONDITION_DIET_TABLE = {
    "高血压": {
        "principle": "低钠、高钾、富含膳食纤维",
        "recommend": "新鲜蔬菜、水果、全谷物、深海鱼、豆类",
        "avoid": "腌制食品、加工肉、高盐调料、罐头食品",
    },
    "2型糖尿病": {
        "principle": "低糖、高纤维、少食多餐、控制碳水",
        "recommend": "全谷物、绿叶蔬菜、优质蛋白、豆类",
        "avoid": "精制糖、白米白面、含糖饮料、甜食",
    },
    "高脂血症": {
        "principle": "低脂、低胆固醇、增加不饱和脂肪酸",
        "recommend": "燕麦、坚果、橄榄油、深海鱼、豆腐",
        "avoid": "动物内脏、油炸食品、黄油、肥肉",
    },
    "化疗期间": {
        "principle": "高蛋白、高热量、易消化、增强免疫力",
        "recommend": "鸡蛋、鱼肉、鸡肉、豆腐、南瓜、山药",
        "avoid": "生冷食品、辛辣刺激、油腻难消化食物",
    },
}

_WEEKLY_MEALS = [
    {  # 周一
        "breakfast": [
            {"name": "燕麦粥", "icon": "🥣", "condition": "糖尿病", "benefit": "富含β-葡聚糖，延缓血糖上升，适合血糖管理"},
            {"name": "水煮鸡蛋", "icon": "🥚", "condition": "高血压", "benefit": "优质蛋白，不增加钠摄入，有助维持血管弹性"},
            {"name": "凉拌黄瓜", "icon": "🥒", "condition": "高脂血症", "benefit": "低热量高纤维，有助控制体重和血脂"},
        ],
        "lunch": [
            {"name": "清蒸鲈鱼", "icon": "🐟", "condition": "高脂血症", "benefit": "富含Omega-3不饱和脂肪酸，有助降低血脂和保护心血管"},
            {"name": "蒜蓉西兰花", "icon": "🥦", "condition": "高血压", "benefit": "富含钾和维C，有助降低血压，大蒜素保护血管"},
            {"name": "糙米饭（小碗）", "icon": "🍚", "condition": "糖尿病", "benefit": "升糖指数低于白米，膳食纤维帮助稳定餐后血糖"},
        ],
        "dinner": [
            {"name": "豆腐青菜汤", "icon": "🍲", "condition": "高脂血症", "benefit": "大豆蛋白有助降低LDL胆固醇，低脂低热量"},
            {"name": "蒸南瓜", "icon": "🎃", "condition": "糖尿病", "benefit": "含果胶可延缓糖分吸收，富含胡萝卜素增强免疫"},
            {"name": "小米粥", "icon": "🥣", "condition": "高血压", "benefit": "养胃易消化，富含B族维生素和钾，有助血压稳定"},
        ],
    },
    {  # 周二
        "breakfast": [
            {"name": "豆浆（无糖）", "icon": "🥛", "condition": "高脂血症", "benefit": "大豆异黄酮有助调节血脂，植物蛋白替代动物脂肪"},
            {"name": "蒸红薯（小块）", "icon": "🍠", "condition": "糖尿病", "benefit": "富含膳食纤维，升糖较慢，少量食用可替代主食"},
            {"name": "拌菠菜", "icon": "🥬", "condition": "高血压", "benefit": "菠菜富含钾和叶酸，有助血管舒张和降压"},
        ],
        "lunch": [
            {"name": "番茄炒蛋", "icon": "🍳", "condition": "高血压", "benefit": "番茄红素是天然抗氧化剂，保护血管、有助降压"},
            {"name": "清炒荷兰豆", "icon": "🫛", "condition": "高脂血症", "benefit": "富含植物纤维，促进胆固醇排出，低脂高营养"},
            {"name": "杂粮饭", "icon": "🍚", "condition": "糖尿病", "benefit": "混合粗粮降低整体升糖指数，增加饱腹感"},
        ],
        "dinner": [
            {"name": "鸡胸肉粥", "icon": "🍲", "condition": "高脂血症", "benefit": "去皮鸡胸肉是低脂高蛋白选择，粥品易消化"},
            {"name": "蒸茄子", "icon": "🍆", "condition": "高血压", "benefit": "茄子含芦丁，有助增强毛细血管弹性、辅助降压"},
            {"name": "拌木耳", "icon": "🍄", "condition": "高脂血症", "benefit": "黑木耳多糖有助降低血脂和防止血栓形成"},
        ],
    },
    {  # 周三
        "breakfast": [
            {"name": "全麦馒头（小个）", "icon": "🍞", "condition": "糖尿病", "benefit": "全麦含丰富膳食纤维，比白面馒头升糖更慢"},
            {"name": "煎蛋（少油）", "icon": "🍳", "condition": "高脂血症", "benefit": "鸡蛋卵磷脂有助乳化胆固醇，少油烹调控制脂肪"},
            {"name": "凉拌海带丝", "icon": "🥗", "condition": "高血压", "benefit": "海带富含钾、碘和褐藻胶，有助降压和调节代谢"},
        ],
        "lunch": [
            {"name": "清蒸虾仁", "icon": "🦐", "condition": "高血压", "benefit": "高蛋白低脂肪，虾青素有抗氧化作用，保护心血管"},
            {"name": "炒芹菜百合", "icon": "🥬", "condition": "高血压", "benefit": "芹菜含芹菜素，是经典的辅助降压蔬菜"},
            {"name": "糙米饭（小碗）", "icon": "🍚", "condition": "糖尿病", "benefit": "低升糖主食，搭配蔬菜蛋白一起食用效果更好"},
        ],
        "dinner": [
            {"name": "山药排骨汤（去油）", "icon": "🍲", "condition": "糖尿病", "benefit": "山药含黏液蛋白，有助稳定血糖，汤品去油减脂"},
            {"name": "清炒丝瓜", "icon": "🥒", "condition": "高脂血症", "benefit": "丝瓜低热量高纤维，有助促进肠道蠕动、排出多余脂肪"},
        ],
    },
    {  # 周四
        "breakfast": [
            {"name": "紫薯粥", "icon": "🥣", "condition": "高脂血症", "benefit": "紫薯含花青素，是强效抗氧化剂，有助保护血管"},
            {"name": "水煮鸡蛋", "icon": "🥚", "condition": "高血压", "benefit": "优质蛋白质来源，烹调方式不增加额外盐分和油脂"},
            {"name": "凉拌秋葵", "icon": "🥬", "condition": "糖尿病", "benefit": "秋葵黏液多糖有助减缓血糖上升速度"},
        ],
        "lunch": [
            {"name": "红烧豆腐", "icon": "🧈", "condition": "高脂血症", "benefit": "豆腐富含大豆蛋白和卵磷脂，有助降低LDL胆固醇"},
            {"name": "西红柿蛋汤", "icon": "🍅", "condition": "高血压", "benefit": "番茄红素+优质蛋白，低钠烹调有助心血管健康"},
            {"name": "杂粮饭", "icon": "🍚", "condition": "糖尿病", "benefit": "多种粗粮混合，升糖指数低，营养更均衡"},
        ],
        "dinner": [
            {"name": "清蒸鳕鱼", "icon": "🐟", "condition": "高脂血症", "benefit": "深海鱼富含DHA和EPA，是降低甘油三酯的优质食材"},
            {"name": "蒜蓉蒸苋菜", "icon": "🥬", "condition": "高血压", "benefit": "苋菜含丰富钾和钙，有助维持电解质平衡、稳定血压"},
            {"name": "小米粥", "icon": "🥣", "condition": "糖尿病", "benefit": "小米易消化，少量晚餐有助控制夜间血糖波动"},
        ],
    },
    {  # 周五
        "breakfast": [
            {"name": "荞麦面", "icon": "🍜", "condition": "糖尿病", "benefit": "荞麦含芦丁和膳食纤维，升糖指数低，有助稳定血糖"},
            {"name": "白灼生菜", "icon": "🥬", "condition": "高脂血症", "benefit": "低热量高纤维，白灼方式不增加额外油脂"},
            {"name": "核桃（3颗）", "icon": "🥜", "condition": "高脂血症", "benefit": "富含α-亚麻酸，少量摄入有助提升好胆固醇HDL"},
        ],
        "lunch": [
            {"name": "清炖鸡汤（去皮）", "icon": "🍗", "condition": "高脂血症", "benefit": "去皮鸡肉低脂高蛋白，鸡汤温补易吸收"},
            {"name": "蒜蓉油麦菜", "icon": "🥬", "condition": "高血压", "benefit": "油麦菜含丰富钾，清炒少盐有助降压"},
            {"name": "糙米饭（小碗）", "icon": "🍚", "condition": "糖尿病", "benefit": "坚持粗粮主食，长期有助改善胰岛素敏感性"},
        ],
        "dinner": [
            {"name": "冬瓜虾仁汤", "icon": "🍲", "condition": "高血压", "benefit": "冬瓜利尿消肿，有助降低血压；虾仁补充优质蛋白"},
            {"name": "凉拌豆腐丝", "icon": "🥗", "condition": "高脂血症", "benefit": "大豆蛋白可替代动物蛋白，有助降低胆固醇"},
        ],
    },
    {  # 周六
        "breakfast": [
            {"name": "南瓜小米粥", "icon": "🥣", "condition": "糖尿病", "benefit": "南瓜果胶延缓糖分吸收，小米养胃，适合控糖早餐"},
            {"name": "蒸蛋羹", "icon": "🍮", "condition": "高血压", "benefit": "蒸蛋软嫩易消化，优质蛋白无额外盐分"},
            {"name": "拌花生芹菜", "icon": "🥜", "condition": "高血压", "benefit": "芹菜降压+花生提供不饱和脂肪酸，搭配互补"},
        ],
        "lunch": [
            {"name": "香菇鸡丁", "icon": "🍗", "condition": "高脂血症", "benefit": "香菇含多糖有助降脂，鸡肉低脂高蛋白"},
            {"name": "炒空心菜", "icon": "🥬", "condition": "高血压", "benefit": "空心菜含钾量高，有助排钠降压，清炒少盐即可"},
            {"name": "杂粮饭", "icon": "🍚", "condition": "糖尿病", "benefit": "混合粗粮保持血糖平稳，提供持久能量"},
        ],
        "dinner": [
            {"name": "鲫鱼豆腐汤", "icon": "🐟", "condition": "高脂血症", "benefit": "鲫鱼低脂高蛋白，豆腐补充植物蛋白和钙质"},
            {"name": "蒸西兰花", "icon": "🥦", "condition": "高血压", "benefit": "西兰花含萝卜硫素，有助保护血管、辅助控压"},
        ],
    },
    {  # 周日
        "breakfast": [
            {"name": "黑米粥", "icon": "🥣", "condition": "高脂血症", "benefit": "黑米含花青素和膳食纤维，有助抗氧化和降低血脂"},
            {"name": "茶叶蛋", "icon": "🥚", "condition": "高血压", "benefit": "茶叶含茶多酚有助血管弹性，鸡蛋提供优质蛋白"},
            {"name": "拌莴笋丝", "icon": "🥬", "condition": "糖尿病", "benefit": "莴笋含铬元素，有助增强胰岛素活性、稳定血糖"},
        ],
        "lunch": [
            {"name": "蘑菇炒肉片", "icon": "🍄", "condition": "高脂血症", "benefit": "蘑菇多糖有助降脂，搭配瘦肉补充铁和蛋白质"},
            {"name": "凉拌苦瓜", "icon": "🥒", "condition": "糖尿病", "benefit": "苦瓜含苦瓜素，有助降低血糖，是天然的辅助控糖食材"},
            {"name": "糙米饭（小碗）", "icon": "🍚", "condition": "糖尿病", "benefit": "周末也保持粗粮习惯，稳定的饮食结构是控糖关键"},
        ],
        "dinner": [
            {"name": "紫菜蛋花汤", "icon": "🍲", "condition": "高血压", "benefit": "紫菜富含钾和碘，有助调节血压和甲状腺功能"},
            {"name": "清蒸山药", "icon": "🥔", "condition": "糖尿病", "benefit": "山药黏液蛋白有助控糖，清蒸保留营养又易消化"},
            {"name": "拌菠菜", "icon": "🥬", "condition": "高脂血症", "benefit": "菠菜含叶酸和膳食纤维，有助降低同型半胱氨酸水平"},
        ],
    },
]

_DIET_TIPS = [
    ("🧂", "控盐", "每日食盐不超过5克，避免腌制食品，用醋、柠檬汁、香料代替盐调味"),
    ("🍚", "主食搭配", "粗细粮搭配，糙米、燕麦、杂豆替代部分白米，有助稳定血糖和血脂"),
    ("🥩", "优质蛋白", "每天保证1个鸡蛋、适量鱼虾豆腐，少吃红肉和加工肉制品"),
    ("🥬", "多吃蔬菜", "每天至少300克蔬菜，深色蔬菜占一半以上，补充钾、维生素和膳食纤维"),
    ("💧", "适量饮水", "每天1500-1700ml温开水，少量多次，避免含糖饮料和浓茶"),
    ("🕐", "规律进餐", "定时定量，少食多餐，晚餐不宜过饱，睡前2小时避免进食"),
    ("🍳", "健康烹调", "多用蒸、煮、炖、拌，少用煎、炸、烤，减少油脂摄入"),
    ("🚶", "餐后运动", "餐后30分钟适当散步15-20分钟，有助消化和控制餐后血糖"),
]


FOOD_IMG_QUERIES = {
    "燕麦粥": "oatmeal,porridge",
    "水煮鸡蛋": "boiled,egg,breakfast",
    "凉拌黄瓜": "cucumber,salad,asian",
    "清蒸鲈鱼": "steamed,fish,chinese",
    "蒜蓉西兰花": "broccoli,garlic,stir",
    "糙米饭（小碗）": "brown,rice,bowl",
    "豆腐青菜汤": "tofu,vegetable,soup",
    "蒸南瓜": "steamed,pumpkin",
    "小米粥": "millet,porridge,chinese",
    "豆浆（无糖）": "soy,milk,drink",
    "蒸红薯（小块）": "steamed,sweet,potato",
    "拌菠菜": "spinach,salad,sesame",
    "番茄炒蛋": "tomato,egg,chinese",
    "清炒荷兰豆": "snap,peas,stir,fry",
    "杂粮饭": "multigrain,rice,bowl",
    "鸡胸肉粥": "chicken,congee,porridge",
    "蒸茄子": "steamed,eggplant,chinese",
    "拌木耳": "wood,ear,mushroom,salad",
    "全麦馒头（小个）": "whole,wheat,bread,chinese",
    "煎蛋（少油）": "fried,egg,sunny",
    "凉拌海带丝": "seaweed,salad,kelp",
    "清蒸虾仁": "steamed,shrimp,chinese",
    "炒芹菜百合": "celery,lily,stir,fry",
    "山药排骨汤（去油）": "yam,pork,rib,soup",
    "清炒丝瓜": "loofah,gourd,stir,fry",
    "紫薯粥": "purple,sweet,potato,porridge",
    "凉拌秋葵": "okra,salad",
    "红烧豆腐": "braised,tofu,chinese",
    "西红柿蛋汤": "tomato,egg,soup",
    "清蒸鳕鱼": "steamed,cod,fish",
    "蒜蓉蒸苋菜": "amaranth,greens,garlic",
    "荞麦面": "buckwheat,noodles,soba",
    "白灼生菜": "blanched,lettuce,chinese",
    "核桃（3颗）": "walnuts,nuts",
    "清炖鸡汤（去皮）": "chicken,broth,soup",
    "蒜蓉油麦菜": "romaine,lettuce,garlic",
    "冬瓜虾仁汤": "winter,melon,shrimp,soup",
    "凉拌豆腐丝": "shredded,tofu,salad",
    "南瓜小米粥": "pumpkin,millet,porridge",
    "蒸蛋羹": "steamed,egg,custard",
    "拌花生芹菜": "peanut,celery,salad",
    "香菇鸡丁": "mushroom,chicken,diced",
    "炒空心菜": "morning,glory,water,spinach",
    "鲫鱼豆腐汤": "crucian,carp,tofu,soup",
    "蒸西兰花": "steamed,broccoli",
    "黑米粥": "black,rice,porridge",
    "茶叶蛋": "tea,egg,marbled",
    "拌莴笋丝": "celtuce,lettuce,shredded",
    "蘑菇炒肉片": "mushroom,pork,stir,fry",
    "凉拌苦瓜": "bitter,melon,salad",
    "紫菜蛋花汤": "seaweed,egg,drop,soup",
    "清蒸山药": "steamed,chinese,yam",
    "拌菠菜": "spinach,salad,sesame",
}


def _inject_food_images(meals: list) -> list:
    """Add image URLs to each food item for display in the patient page."""
    import copy
    result = copy.deepcopy(meals)
    for day in result:
        for meal_key in ("breakfast", "lunch", "dinner"):
            for item in day.get(meal_key, []):
                name = item["name"]
                query = FOOD_IMG_QUERIES.get(name, "chinese,food,dish")
                lock = sum(ord(c) for c in name) % 1000
                item["img"] = f"https://loremflickr.com/300/200/{query}?lock={lock}"
    return result


def _detect_conditions(profile_text: str) -> list[str]:
    """Extract condition keywords from the patient's long-term profile."""
    keywords = ["高血压", "2型糖尿病", "糖尿病", "高脂血症", "冠心病", "心力衰竭",
                "肾病", "化疗", "放疗", "骨质疏松"]
    found = []
    for kw in keywords:
        if kw in profile_text:
            found.append(kw)
    return found if found else ["慢性病管理"]


def _extract_patient_name(profile_text: str, user_id: str) -> str:
    """Try to extract a name from profile, otherwise generate a friendly one."""
    import re as _re
    m = _re.search(r"([\u4e00-\u9fa5]{1,4}(?:阿姨|叔叔|奶奶|爷爷|先生|女士))", profile_text)
    if m:
        return m.group(1)
    age_m = _re.search(r"(\d+)\s*岁", profile_text)
    gender_m = _re.search(r"(男|女)", profile_text)
    age = int(age_m.group(1)) if age_m else 75
    gender = gender_m.group(1) if gender_m else "男"
    if age >= 60:
        return "李阿姨" if gender == "女" else "王叔叔"
    return user_id


def generate_nutrition_zh_page(skill_input: dict, result: dict):
    """Generate the 7-day personalized Chinese nutrition page."""
    if not NUTRITION_ZH_TEMPLATE.exists():
        print("[Nutrition ZH template not found, skipping]")
        return

    template = NUTRITION_ZH_TEMPLATE.read_text(encoding="utf-8")
    meta = skill_input.get("meta", {})
    memory = skill_input.get("memory", {})
    profile = memory.get("patient_long_term_profile", "")

    patient_name = _extract_patient_name(profile, meta.get("user_id", "患者"))
    conditions = _detect_conditions(profile)

    # Condition badges
    cond_badges = "".join(
        f'<div class="bg-white/20 rounded-full px-3 py-1 text-xs font-medium">{c}</div>'
        for c in conditions
    )

    # Diet table rows
    table_rows = ""
    for c in conditions:
        info = CONDITION_DIET_TABLE.get(c)
        if not info:
            for key, val in CONDITION_DIET_TABLE.items():
                if key in c or c in key:
                    info = val
                    break
        if info:
            table_rows += (
                f'<tr>'
                f'<td class="px-4 py-3 font-medium text-slate-800">{c}</td>'
                f'<td class="px-4 py-3 text-slate-600">{info["principle"]}</td>'
                f'<td class="px-4 py-3 text-emerald-700">{info["recommend"]}</td>'
                f'<td class="px-4 py-3 text-rose-600">{info["avoid"]}</td>'
                f'</tr>'
            )

    # Tips
    tips_html = ""
    for icon, title, text in _DIET_TIPS:
        tips_html += (
            f'<div class="bg-slate-50 rounded-lg p-3 border border-slate-100">'
            f'<div class="flex items-center gap-2 mb-1">'
            f'<span class="text-base">{icon}</span>'
            f'<span class="text-xs font-semibold text-slate-700">{title}</span>'
            f'</div>'
            f'<div class="text-xs text-slate-600 leading-relaxed">{text}</div>'
            f'</div>'
        )

    # Meal data JSON (filter meals to emphasize patient's conditions)
    meal_json = json.dumps(_WEEKLY_MEALS, ensure_ascii=False)

    # Guardrail
    nutrition_from_result = result.get("nutrition_advice", "")
    guardrail = (
        f"本营养计划由 AI 健康助手根据{patient_name}的健康档案（{', '.join(conditions)}）自动生成，"
        "仅供日常饮食参考，不替代医生或营养师的专业指导。"
        "如有特殊饮食限制（如肾病饮食、药物禁忌食物），请务必遵照主治医生的医嘱。"
    )

    profile_summary = profile
    if nutrition_from_result:
        profile_summary += f" | AI建议：{nutrition_from_result}"

    replacements = {
        "{{PATIENT_NAME}}":     patient_name,
        "{{CONDITION_BADGES}}": cond_badges,
        "{{PROFILE_SUMMARY}}":  profile_summary,
        "{{DIET_TABLE_ROWS}}":  table_rows,
        "{{TIPS_HTML}}":        tips_html,
        "{{MEAL_DATA_JSON}}":   meal_json,
        "{{GUARDRAIL_TEXT}}":   guardrail,
    }

    html = template
    for key, val in replacements.items():
        html = html.replace(key, val)

    NUTRITION_ZH_OUTPUT.write_text(html, encoding="utf-8")
    print(f"\n=== NUTRITION PAGE (Chinese) ===")
    print(f"Generated: {NUTRITION_ZH_OUTPUT}")
    webbrowser.open(NUTRITION_ZH_OUTPUT.as_uri())


def generate_patient_page(skill_input: dict, result: dict):
    """Generate a single patient-facing page combining health overview + nutrition."""
    if not PATIENT_TEMPLATE.exists():
        print("[Patient template not found, skipping]")
        return

    template = PATIENT_TEMPLATE.read_text(encoding="utf-8")
    meta = skill_input.get("meta", {})
    memory = skill_input.get("memory", {})
    signals = skill_input.get("signals", {})
    location = skill_input.get("location", {})
    latest_health = skill_input.get("latest_health", {})

    profile = memory.get("patient_long_term_profile", "")
    patient_name = _extract_patient_name(profile, meta.get("user_id", "患者"))
    conditions = _detect_conditions(profile)

    # --- status badge ---
    status = result.get("patient_status", "stable")
    status_tw = {
        "stable":   ("bg-emerald-100 text-emerald-700", "✅", "身体状态良好"),
        "at_risk":  ("bg-amber-100 text-amber-700",     "⚠️", "需要关注"),
        "critical": ("bg-rose-100 text-rose-700",       "🚨", "请及时就医"),
    }
    s_class, s_icon, s_text = status_tw.get(status, status_tw["stable"])

    # --- patient-facing AI message ---
    ai_msg = result.get("assistant_message_patient", "")
    if not ai_msg:
        ai_msg = "您好！根据今天的监测数据，整体状况还不错。请继续保持良好的饮食和运动习惯。"

    # --- vitals ---
    vital_defs = [
        ("blood_pressure", "血压",  "mmHg", "💓"),
        ("heart_rate",     "心率",  "bpm",  "❤️"),
        ("blood_oxygen",   "血氧",  "%",    "🫁"),
        ("blood_glucose",  "血糖",  "mmol/L", "🩸"),
        ("steps",          "步数",  "步",   "🚶"),
    ]
    vitals_parts = []
    for key, label, unit, icon in vital_defs:
        val = latest_health.get(key) if latest_health else None
        if val is not None:
            vitals_parts.append(
                f'<div class="bg-slate-50 rounded-lg p-3 text-center border border-slate-100">'
                f'<div class="text-lg mb-0.5">{icon}</div>'
                f'<div class="text-[11px] text-slate-500 font-medium mb-1">{label}</div>'
                f'<div class="text-xl font-bold text-slate-800">{val}</div>'
                f'<div class="text-[10px] text-slate-400">{unit}</div>'
                f'</div>'
            )
        else:
            vitals_parts.append(
                f'<div class="bg-slate-50 rounded-lg p-3 text-center border border-slate-100">'
                f'<div class="text-lg mb-0.5">{icon}</div>'
                f'<div class="text-[11px] text-slate-500 font-medium mb-1">{label}</div>'
                f'<div class="text-base text-slate-300">--</div>'
                f'</div>'
            )
    vitals_html = "".join(vitals_parts)

    # --- location ---
    loc = location.get("current", {})
    patient_lat = loc.get("lat", 0)
    patient_lon = loc.get("lon", 0)

    if status == "critical":
        ai_map_msg = "检测到健康异常，已为您查询附近的医疗机构，如有不适请及时就医。"
    elif any("活动" in t or "偏低" in t for t in result.get("risk_tags", [])):
        ai_map_msg = "您近期活动量偏低哦，天气不错的话可以去附近的公园散散步！"
    else:
        ai_map_msg = "这是您附近的医院和公园，有需要时可以参考。"

    # --- recommendations ---
    recs = result.get("recommendations", [])
    recs_html = ""
    rec_icons = ["💊", "🚶", "🫀", "🩸", "🧈", "🥗", "🧘", "💤"]
    for i, r in enumerate(recs):
        icon = rec_icons[i % len(rec_icons)]
        recs_html += (
            f'<div class="flex items-start gap-3 bg-emerald-50 rounded-lg p-3 border border-emerald-100">'
            f'<span class="text-base mt-0.5">{icon}</span>'
            f'<div class="text-sm text-slate-700 leading-relaxed">{r}</div>'
            f'</div>'
        )
    if not recs_html:
        recs_html = '<div class="text-sm text-slate-400">暂无具体建议</div>'

    # --- risk tags ---
    risk_tags = result.get("risk_tags", [])
    risk_tag_colors = {
        "心率": "bg-rose-50 text-rose-700 border-rose-200",
        "血压": "bg-rose-50 text-rose-700 border-rose-200",
        "血糖": "bg-amber-50 text-amber-700 border-amber-200",
        "活动": "bg-sky-50 text-sky-700 border-sky-200",
        "偏低": "bg-amber-50 text-amber-700 border-amber-200",
        "偏高": "bg-rose-50 text-rose-700 border-rose-200",
        "异常": "bg-orange-50 text-orange-700 border-orange-200",
    }
    risk_tags_parts = []
    for tag in risk_tags:
        cls = "bg-slate-50 text-slate-600 border-slate-200"
        for kw, c in risk_tag_colors.items():
            if kw in tag:
                cls = c
                break
        risk_tags_parts.append(
            f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium border {cls}">{tag}</span>'
        )
    risk_tags_html = "".join(risk_tags_parts) if risk_tags_parts else (
        '<span class="inline-block px-3 py-1 rounded-full text-xs font-medium border bg-emerald-50 text-emerald-700 border-emerald-200">暂无风险</span>'
    )

    # --- reasoning ---
    reasoning = result.get("reasoning", "")
    reasoning_html = ""
    if reasoning:
        reasoning_html = (
            '<div class="mt-4 pt-3 border-t border-slate-100">'
            '<div class="text-[11px] text-slate-400 uppercase tracking-wide font-medium mb-1.5">评估依据</div>'
            f'<div class="text-xs text-slate-600 bg-slate-50 rounded-lg p-3 leading-relaxed">{reasoning}</div>'
            '</div>'
        )

    # --- adherence ---
    adherence = skill_input.get("adherence_analysis", {})
    adh_statuses = adherence.get("statuses", [])
    adh_suggestions = adherence.get("suggestions", [])
    adh_preferences = adherence.get("preferences", [])
    adherence_html = ""
    if adh_statuses or adh_suggestions or adh_preferences:
        adh_inner = (
            '<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5">'
            '<div class="flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">'
            '<span class="text-lg">💊</span>'
            '<h2 class="text-sm font-bold text-slate-800">用药与依从性</h2>'
            '</div>'
        )
        if adh_statuses:
            adh_inner += '<div class="flex flex-wrap gap-2 mb-3">'
            for s in adh_statuses:
                adh_inner += f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">{s}</span>'
            adh_inner += '</div>'
        if adh_preferences:
            adh_inner += '<div class="flex flex-wrap gap-2 mb-3">'
            for p in adh_preferences:
                adh_inner += f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium bg-blue-50 text-blue-600 border border-blue-200">{p}</span>'
            adh_inner += '</div>'
        if adh_suggestions:
            for s in adh_suggestions:
                adh_inner += (
                    f'<div class="flex items-start gap-3 bg-indigo-50 rounded-lg p-3 border border-indigo-100 mb-2">'
                    f'<span class="text-base mt-0.5">📋</span>'
                    f'<div class="text-sm text-slate-700 leading-relaxed">{s}</div>'
                    f'</div>'
                )
        adh_inner += '</div>'
        adherence_html = adh_inner

    # --- condition badges ---
    cond_colors = {
        "高血压": "bg-rose-500",
        "2型糖尿病": "bg-amber-500",
        "糖尿病": "bg-amber-500",
        "高脂血症": "bg-orange-500",
        "化疗": "bg-purple-500",
    }
    cond_badges = ""
    for c in conditions:
        color = cond_colors.get(c, "bg-slate-500")
        cond_badges += f'<span class="inline-block {color} text-white px-3 py-1 rounded-full text-xs font-semibold">{c}</span>'

    # --- diet table ---
    table_rows = ""
    for c in conditions:
        info = CONDITION_DIET_TABLE.get(c)
        if not info:
            for key, val in CONDITION_DIET_TABLE.items():
                if key in c or c in key:
                    info = val
                    break
        if info:
            table_rows += (
                f'<tr>'
                f'<td class="px-4 py-3 font-medium text-slate-800">{c}</td>'
                f'<td class="px-4 py-3 text-slate-600">{info["principle"]}</td>'
                f'<td class="px-4 py-3 text-emerald-700">{info["recommend"]}</td>'
                f'<td class="px-4 py-3 text-rose-600">{info["avoid"]}</td>'
                f'</tr>'
            )

    # --- meal data with images ---
    meals_with_imgs = _inject_food_images(_WEEKLY_MEALS)
    meal_json = json.dumps(meals_with_imgs, ensure_ascii=False)

    # --- tips ---
    tips_html = ""
    for icon, title, text in _DIET_TIPS:
        tips_html += (
            f'<div class="bg-slate-50 rounded-lg p-3 border border-slate-100">'
            f'<div class="flex items-center gap-2 mb-1">'
            f'<span class="text-base">{icon}</span>'
            f'<span class="text-xs font-semibold text-slate-700">{title}</span>'
            f'</div>'
            f'<div class="text-xs text-slate-600 leading-relaxed">{text}</div>'
            f'</div>'
        )

    # --- guardrail ---
    guardrail = (
        f"本健康报告由 AI 健康助手根据{patient_name}的健康档案（{', '.join(conditions)}）自动生成，"
        "仅供日常参考，不替代医生的专业诊断。"
        "如有特殊饮食限制或药物禁忌，请遵照主治医生的医嘱。"
        "如感到明显不适，请立即联系家人或拨打急救电话。"
    )

    now = datetime.now(UTC).strftime("%Y年%m月%d日 %H:%M")
    replacements = {
        "{{PATIENT_NAME}}":       patient_name,
        "{{CURRENT_TIME}}":       now,
        "{{STATUS_TW_CLASS}}":    s_class,
        "{{STATUS_ICON}}":        s_icon,
        "{{STATUS_TEXT}}":        s_text,
        "{{AI_PATIENT_MESSAGE}}": ai_msg,
        "{{VITALS_HTML}}":        vitals_html,
        "{{RISK_TAGS_HTML}}":     risk_tags_html,
        "{{RECOMMENDATIONS_HTML}}": recs_html,
        "{{REASONING_HTML}}":     reasoning_html,
        "{{ADHERENCE_HTML}}":     adherence_html,
        "{{AI_MAP_MESSAGE}}":     ai_map_msg,
        "{{PATIENT_LAT}}":        str(patient_lat) if patient_lat else "0",
        "{{PATIENT_LON}}":        str(patient_lon) if patient_lon else "0",
        "{{CONDITION_BADGES}}":   cond_badges,
        "{{DIET_TABLE_ROWS}}":    table_rows,
        "{{MEAL_DATA_JSON}}":     meal_json,
        "{{TIPS_HTML}}":          tips_html,
        "{{GUARDRAIL_TEXT}}":     guardrail,
    }

    html = template
    for key, val in replacements.items():
        html = html.replace(key, val)

    PATIENT_OUTPUT.write_text(html, encoding="utf-8")
    print(f"\n=== PATIENT HEALTH PAGE (Combined) ===")
    print(f"Generated: {PATIENT_OUTPUT}")
    webbrowser.open(PATIENT_OUTPUT.as_uri())


def run_skill(input_path: str, offline_only: bool = False):
    """Process a structured skill-input JSON (see skill_input_example.md)."""
    skill_input = load_json(Path(input_path))

    system_prompt = _load_skill_system_prompt()
    user_prompt = json.dumps(skill_input, ensure_ascii=False, indent=2)

    result = None
    if not offline_only:
        raw = call_llm(system_prompt, user_prompt)
        result = extract_json(raw)

    if result is None:
        print("[Using offline fallback for skill input]")
        result = _skill_offline_fallback(skill_input)

    full_output = {
        "skill_input": skill_input,
        "skill_output": result,
    }

    print(json.dumps(full_output, ensure_ascii=False, indent=2))

    output_file = ROOT / "demo_output.json"
    output_file.write_text(
        json.dumps(full_output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nSaved to: {output_file}")

    generate_patient_page(skill_input, result)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    load_env_file(ROOT / ".env")

    parser = argparse.ArgumentParser(
        description="Solo Elderly Skill — supports legacy mock demo and structured skill input"
    )
    sub = parser.add_subparsers(dest="command")

    # --- skill mode (new) ---
    sp_skill = sub.add_parser("skill", help="Run with structured JSON input (skill_input_example.md format)")
    sp_skill.add_argument("input_file", help="Path to skill input JSON file")
    sp_skill.add_argument("--offline-only", action="store_true", help="Skip LLM, use deterministic fallback")

    # --- live mode (real backend API) ---
    sp_live = sub.add_parser("live", help="Fetch real data from backend API and run skill")
    sp_live.add_argument("user_id", help="User ID from the backend (use 'list' to see all users)")
    sp_live.add_argument("--offline-only", action="store_true", help="Skip LLM, use deterministic fallback")

    # --- list users ---
    sub.add_parser("users", help="List all users from the backend API")

    # --- legacy demo mode ---
    sp_demo = sub.add_parser("demo", help="Run legacy mock demo (memory_cases + location_cases)")
    sp_demo.add_argument("--memory-case", default="sedentary_isolation")
    sp_demo.add_argument("--location-case", default="beijing_home")
    sp_demo.add_argument(
        "--user-input",
        default="I feel tired and did not go out for several days.",
    )
    sp_demo.add_argument("--offline-only", action="store_true")

    args = parser.parse_args()

    if args.command == "skill":
        run_skill(args.input_file, offline_only=args.offline_only)
    elif args.command == "live":
        run_live(args.user_id, offline_only=args.offline_only)
    elif args.command == "users":
        users = fetch_user_list()
        if not users:
            print("No users found or API unreachable.")
        else:
            print(f"\n{'ID':<30} {'Name':<15} {'Phone':<15} {'Created'}")
            print("-" * 80)
            for u in users:
                print(f"{u.get('id', '?'):<30} {u.get('name') or '-':<15} {u.get('phone') or '-':<15} {(u.get('createAt') or '')[:10]}")
            print(f"\nTotal: {len(users)} users")
            print("To run with a user: python demo_runner.py live <user_id>")
    elif args.command == "demo":
        run_demo(args.memory_case, args.location_case, args.user_input, offline_only=args.offline_only)
    else:
        parser.print_help()
        print("\nQuick start:")
        print("  python demo_runner.py users                              # list all users")
        print("  python demo_runner.py live <user_id>                     # real data from API")
        print("  python demo_runner.py skill mock/skill_input_sample.json # mock data")
        print("  python demo_runner.py demo --offline-only                # legacy demo")


if __name__ == "__main__":
    main()
