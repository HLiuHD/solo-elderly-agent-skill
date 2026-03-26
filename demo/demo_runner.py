import argparse
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, UTC
from pathlib import Path

import webbrowser

ROOT = Path(__file__).resolve().parent
MEMORY_FILE = ROOT / "mock" / "memory_cases.json"
LOCATION_FILE = ROOT / "mock" / "location_cases.json"
NUTRITION_TEMPLATE = ROOT / "nutrition_template.html"
NUTRITION_OUTPUT = ROOT / "nutrition_report.html"


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


def detect_risk_tags(user_input: str, memory: dict, location: dict):
    text = user_input.lower()
    tags = []

    if any(w in text for w in ["chest pain", "can't breathe", "cant breathe", "dizzy", "fell", "fall", "face drooping", "speech"]):
        tags.append("Emergency_Trigger")

    if (
        any(w in text for w in ["tired", "didn't go out", "did not go out", "stayed home", "no energy"]) and location.get("average_daily_steps", 9999) < 1000
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

    # De-duplicate while preserving order.
    deduped = []
    for t in tags:
        if t not in deduped:
            deduped.append(t)
    return deduped


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


def call_llm(system_prompt: str, user_prompt: str):
    api_key = os.getenv("GEMINI_API_KEY", "")
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    if not api_key:
        print("[LLM skipped: no GEMINI_API_KEY in .env]")
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
        print(f"[LLM call failed: {e.code} {e.reason}]")
        print(f"[Response: {body[:300]}]")
        print("Falling back to offline mode.")
        return None
    except Exception as e:
        print(f"[LLM call failed: {e}] Falling back to offline mode.")
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
    unique_keys = []
    for k in relevant_keys:
        if k not in seen:
            seen.add(k)
            unique_keys.append(k)

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


def main():
    load_env_file(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Solo Elderly Skill Demo (Mock Memory + Mock Location + Gemini + Google Maps)")
    parser.add_argument("--memory-case", default="sedentary_isolation", help="memory case key in mock/memory_cases.json")
    parser.add_argument("--location-case", default="beijing_home", help="location case key in mock/location_cases.json")
    parser.add_argument(
        "--user-input",
        default="I feel tired and did not go out for several days.",
        help="simulated patient utterance",
    )
    parser.add_argument("--offline-only", action="store_true", help="skip Gemini call and use deterministic fallback")
    args = parser.parse_args()

    run_demo(args.memory_case, args.location_case, args.user_input, offline_only=args.offline_only)


if __name__ == "__main__":
    main()
