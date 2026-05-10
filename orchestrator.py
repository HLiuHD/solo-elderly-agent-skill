#!/usr/bin/env python3
"""
Solo Elderly Skill Orchestrator

Full pipeline: signal detection → conversation → doctor report + patient report.

Usage:
  python orchestrator.py                            # auto-detect scenario
  python orchestrator.py --scenario emergency       # emergency triage
  python orchestrator.py --scenario adherence       # routine check-in
  python orchestrator.py --scenario positive        # positive reinforcement
  python orchestrator.py --input path/to/input.json # custom JSON input
  python orchestrator.py --offline-only             # skip LLM, use rules
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCTOR_SKILL_DIR = ROOT / "doctor-report"
PATIENT_SKILL_DIR = ROOT / "patient-report"
DEMO_DIR = ROOT / "demo"
OUTPUT_DIR = ROOT / "output"

# ---------------------------------------------------------------------------
# Env
# ---------------------------------------------------------------------------

def load_env():
    for env_path in [ROOT / ".env", DEMO_DIR / ".env"]:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() and k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()


# ---------------------------------------------------------------------------
# SKILL.md loader (no PyYAML dependency)
# ---------------------------------------------------------------------------
_FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
_RESOURCE_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}


def _parse_frontmatter(text: str) -> dict:
    result: dict = {}
    section: str | None = None
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0 and ":" in stripped:
            key, _, val = stripped.partition(":")
            val = val.strip().strip("\"'")
            if val:
                result[key.strip()] = val
            else:
                result[key.strip()] = {}
                section = key.strip()
        elif indent > 0 and section and isinstance(result.get(section), dict) and ":" in stripped:
            key, _, val = stripped.partition(":")
            result[section][key.strip()] = val.strip().strip("\"'")
    return result


def load_skill(skill_dir: Path) -> dict:
    raw = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    m = _FM_RE.match(raw)
    if not m:
        raise ValueError(f"Missing frontmatter in {skill_dir / 'SKILL.md'}")

    meta = _parse_frontmatter(m.group(1))
    instructions = m.group(2).strip()
    scripts_cfg = meta.get("scripts", {})

    resources = []
    for folder in ("references", "assets"):
        base = skill_dir / folder
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix.lower() in _RESOURCE_SUFFIXES:
                try:
                    content = p.read_text(encoding="utf-8").strip()
                    if content:
                        resources.append({"path": str(p.relative_to(skill_dir)), "content": content})
                except Exception:
                    pass

    def _script(key: str) -> Path | None:
        rel = scripts_cfg.get(key) if isinstance(scripts_cfg, dict) else None
        return (skill_dir / rel).resolve() if rel else None

    return {
        "name": meta.get("name", skill_dir.name),
        "description": meta.get("description", ""),
        "instructions": instructions,
        "dir": skill_dir,
        "pre_llm": _script("pre_llm"),
        "post_llm": _script("post_llm"),
        "resources": resources,
    }


# ---------------------------------------------------------------------------
# Prompt builder (mirrors verify.py)
# ---------------------------------------------------------------------------

def build_skill_prompt(skill: dict, payload: dict) -> str:
    sections = [
        "你现在要执行一个本地 skill。严格遵守下面这份 SKILL.md 的要求，只根据提供的 payload 产出结果。",
        f"[SKILL NAME]\n{skill['name']}",
        f"[SKILL DESCRIPTION]\n{skill['description']}",
        f"[SKILL BODY]\n{skill['instructions']}",
    ]
    if skill["resources"]:
        blocks = [f"## {r['path']}\n{r['content']}" for r in skill["resources"]]
        sections.append("[SKILL RESOURCES]\n" + "\n\n".join(blocks))
    if "script_data" in payload:
        sections.append(
            "[SCRIPT DATA]\npayload 中的 script_data 字段由 pre_llm 脚本自动采集。请优先使用。"
        )
    sections.append(
        "[RUNTIME REQUIREMENT]\n"
        "不要输出解释，不要输出 markdown 代码块，只输出严格 JSON。\n"
        "输出必须包含这些顶层字段：message, structured_output。\n"
        "message 是给用户看的一句话；structured_output 是对象，包含 SKILL.md 要求的所有分析数据。\n"
        "如果 payload 里没有足够信息，明确说明缺失，不要编造。"
    )
    sections.append("[PAYLOAD]\n" + json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# LLM (OpenAI preferred, Gemini fallback, stdlib only)
# ---------------------------------------------------------------------------

def _call_openai(prompt: str) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    if not api_key:
        return None
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [OpenAI error: {e}]")
        return None


def _call_gemini(prompt: str) -> str | None:
    api_key = os.getenv("GEMINI_API_KEY", "")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    if not api_key:
        return None
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={api_key}"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"  [Gemini error: {e}]")
        return None


def call_llm(prompt: str) -> str | None:
    if os.getenv("OPENAI_API_KEY"):
        print("    Using OpenAI ...")
        result = _call_openai(prompt)
        if result:
            return result
        print("    OpenAI failed, trying Gemini ...")
    if os.getenv("GEMINI_API_KEY"):
        print("    Using Gemini ...")
        result = _call_gemini(prompt)
        if result:
            return result
    print("    No API available — offline fallback")
    return None


def extract_json(text: str) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Script runner
# ---------------------------------------------------------------------------

def run_script(script_path: Path, input_json: str, cwd: Path) -> dict:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            input=input_json, capture_output=True, text=True,
            timeout=120, cwd=str(cwd), encoding="utf-8", env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "Timed out after 120s"}
    return {"ok": proc.returncode == 0, "stdout": proc.stdout, "stderr": proc.stderr}


# ---------------------------------------------------------------------------
# Offline fallback
# ---------------------------------------------------------------------------

def _offline_doctor(payload: dict, status: str, triage: str, risk_tags: list) -> dict:
    mem = payload.get("memory", {})
    sig = payload.get("signals", {})
    lh = payload.get("latest_health", {})
    return {
        "message": "患者分诊报告已生成",
        "structured_output": {
            "patient_profile": {
                "name": "王建国", "age": 72, "gender": "男",
                "diagnoses": ["高血压", "2型糖尿病", "高脂血症"],
                "medications": ["氨氯地平 5mg qd", "二甲双胍 500mg bid", "阿托伐他汀 20mg qn"],
                "baseline_note": "独居老人，生活基本自理",
            },
            "patient_status": status,
            "triage_level": triage,
            "risk_tags": risk_tags,
            "assistant_message_doctor": (
                f"患者{mem.get('recent_health_dynamics', '近期情况平稳')}。"
                f"信号分析：{sig.get('summary_text', '暂无')}。建议持续监测。"
            ),
            "reasoning": f"基于设备信号（{', '.join(risk_tags)}）和患者档案进行评估。",
            "signals_summary": {
                "window": f"{sig.get('start_ts', '?')} ~ {sig.get('end_ts', '?')}",
                "description": sig.get("summary_text", "暂无数据"),
                "anomalies": sig.get("anomalies", []),
            },
            "latest_vitals": lh,
            "adherence_analysis": payload.get("adherence_analysis", {}),
            "recommendations": [
                "按时服药并监测血压", "适当增加活动量",
                "低盐低脂饮食", "注意休息和睡眠", "如有不适及时就医",
            ],
            "nutrition_plan_summary": {
                "conditions_addressed": ["高血压", "2型糖尿病", "高脂血症"],
                "diet_principles": ["低钠饮食", "控制碳水", "减少饱和脂肪"],
                "weekly_plan_generated": False,
                "plan_note": "根据患者慢性病组合生成基础营养指导。",
            },
            "guardrail": "本报告由 AI 健康助手自动生成，仅供临床参考，不构成医疗诊断。",
        },
    }


def _offline_patient(payload: dict, status: str, risk_tags: list) -> dict:
    sig = payload.get("signals", {})
    lh = payload.get("latest_health", {})
    return {
        "message": "您的健康报告已生成",
        "structured_output": {
            "patient_name": "王叔叔",
            "patient_status": status,
            "risk_tags": risk_tags,
            "assistant_message_patient": (
                f"王叔叔，您好！{sig.get('summary_text', '整体状况还不错')}。"
                "请继续保持按时服药、规律饮食的好习惯。如有不适请随时告诉我。"
            ),
            "recommendations": [
                "每天按时测量血压，早晚各一次",
                "每天争取散步30分钟，可以慢慢来",
                "做菜少放盐，用醋和葱姜提味",
                "保持规律作息，每晚11点前休息",
                "天气好的时候去附近公园走走",
            ],
            "nutrition_advice": "饮食注意少盐少糖，多吃蔬菜水果，主食可以换成杂粮，对血压血糖都有好处。",
            "latest_health_summary": {
                "blood_pressure": str(lh.get("blood_pressure", "--")),
                "heart_rate": str(lh.get("heart_rate", "--")),
                "blood_oxygen": str(lh.get("blood_oxygen", "--")),
                "blood_glucose": str(lh.get("blood_glucose", "--")),
                "steps_today": str(lh.get("steps", "--")),
            },
            "adherence": payload.get("adherence_analysis", {}),
            "conditions": ["高血压", "2型糖尿病", "高脂血症"],
            "diet_table": [
                {"condition": "高血压", "principle": "低钠高钾", "recommend": "蔬菜、水果、全谷物", "avoid": "腌制食品、高盐调料"},
                {"condition": "2型糖尿病", "principle": "低GI、控制总量", "recommend": "荞麦、燕麦、绿叶菜", "avoid": "白米粥、含糖饮料"},
                {"condition": "高脂血症", "principle": "低脂高纤维", "recommend": "深海鱼、橄榄油、燕麦", "avoid": "动物内脏、油炸食品"},
            ],
            "weekly_meal_plan": [],
            "diet_tips": [
                {"icon": "🧂", "title": "控盐", "detail": "每日食盐不超过5克，用醋和香料代替盐调味"},
                {"icon": "🍚", "title": "主食搭配", "detail": "粗细粮搭配，糙米、燕麦替代部分白米"},
                {"icon": "🚶", "title": "餐后运动", "detail": "餐后30分钟散步15-20分钟，有助控制血糖"},
                {"icon": "💤", "title": "规律作息", "detail": "每晚11点前入睡，减少睡前看手机"},
            ],
            "reasoning": "基于设备信号和患者档案进行离线规则评估。",
            "guardrail": "本报告由 AI 健康管家生成，仅供参考。如有不适请及时就医。",
        },
    }


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------

def analyze_signals(payload: dict) -> tuple[str, str, str, list[str]]:
    """Returns (scenario, status, triage, risk_tags)."""
    anomalies = payload.get("signals", {}).get("anomalies", [])
    lh = payload.get("latest_health", {})
    user_msg = payload.get("latest_user_message", "")
    outlier_symptoms = payload.get("outlier_analysis", {}).get("symptoms", [])

    combined = " ".join([user_msg, *anomalies, *[str(s) for s in outlier_symptoms]])
    emergency_kw = ["危象", "急性", "骤升", "骤降", "严重", "胸闷", "胸痛", "头晕",
                     "晕倒", "跌倒", "呼吸困难", "意识不清"]

    if any(kw in combined for kw in emergency_kw):
        return "emergency", "critical", "emergency", [a for a in anomalies] or ["紧急信号"]

    bp = lh.get("blood_pressure", "")
    if bp:
        try:
            sbp = int(str(bp).split("/")[0])
            if sbp > 180:
                return "emergency", "critical", "emergency", anomalies or ["血压危象"]
        except (ValueError, IndexError):
            pass

    hr = lh.get("heart_rate")
    if hr and (hr > 120 or hr < 40):
        return "emergency", "critical", "urgent", anomalies or ["心率异常"]

    if not anomalies or all(a in ("暂无明确异常", "暂无异常") for a in anomalies):
        steps = lh.get("steps", 0)
        if steps and steps >= 4000:
            return "positive", "stable", "non_urgent", []
        return "adherence", "stable", "non_urgent", anomalies

    return "adherence", "at_risk", "semi_urgent", anomalies


# ---------------------------------------------------------------------------
# Scenarios (conversation + payload)
# ---------------------------------------------------------------------------

def _base_payload() -> dict:
    return {
        "meta": {"user_id": "P-20260509-001", "session_id": "", "intent": "medical_dialog", "lang": "zh", "current_time": ""},
        "memory": {"patient_long_term_profile": "", "recent_health_dynamics": ""},
        "signals": {"start_ts": "", "end_ts": "", "summary_text": "", "anomalies": []},
        "latest_health": {},
        "adherence_analysis": {"statuses": [], "preferences": [], "interventions": [], "suggestions": []},
        "outlier_analysis": {"symptoms": [], "triage": None, "patient_suggestions": [], "doctor_suggestions": []},
        "location": {"current": {"lat": 39.9042, "lon": 116.4074, "record_at": ""}, "records": []},
        "latest_user_message": "",
        "recent_dialog_summary": "",
    }


SCENARIOS = {
    "adherence": {
        "label": "定期随访 — Adherence Check-in",
        "desc": "每2-3天常规随访：活动量下降、血压波动 → 营养/运动/睡眠指导",
        "conversation": [
            ("🤖 健康助手", "王叔叔，您好！三天没见了，想跟您聊聊最近的情况。您这几天感觉怎么样？"),
            ("👤 患 者", "唉，我最近几天没怎么出门，感觉有点累，晚上也睡不太好。"),
            ("🤖 健康助手", "我看到您的手环数据，最近步数确实少了些，血压也有点波动。药都有按时吃吗？"),
            ("👤 患 者", "药倒是按时吃了，就是不太想动，腿有点没劲。"),
            ("🤖 健康助手", "明白了。我来帮您看看最近的数据，给您出一份健康建议，同时也给您的医生发一份报告。"),
        ],
        "patch": {
            "memory": {
                "patient_long_term_profile": "王建国，男，72岁。诊断：高血压（10年）、2型糖尿病（5年）、高脂血症。长期用药：氨氯地平 5mg qd、二甲双胍 500mg bid、阿托伐他汀 20mg qn。独居，喜欢面食。",
                "recent_health_dynamics": "近一周血压稍有波动（135-152mmHg），血糖控制尚可。活动量下降，日均步数从3200步降至1800步。睡眠质量一般，每晚5-6小时。",
            },
            "signals": {
                "summary_text": "近7天设备数据：血压波动偏大，活动量持续下降，心率正常范围，血氧正常。",
                "anomalies": ["血压波动增大", "活动量持续下降"],
            },
            "latest_health": {"blood_pressure": "148/90", "heart_rate": 74, "blood_oxygen": 96, "blood_glucose": 7.1, "steps": 1500},
            "adherence_analysis": {
                "statuses": ["用药依从性良好", "饮食控制一般", "运动量不足", "睡眠质量一般"],
                "preferences": ["偏好面食", "不喜欢剧烈运动"],
                "interventions": ["建议简化运动方案", "加强饮食指导", "关注睡眠"],
                "suggestions": ["每日步行目标调整为3000步", "少盐少油饮食", "睡前减少看电视"],
            },
            "latest_user_message": "我最近几天没怎么出门，感觉有点累，晚上也睡不太好。",
            "recent_dialog_summary": "上次随访3天前，患者表示按时服药但运动减少。",
        },
    },
    "emergency": {
        "label": "紧急信号触发 — Emergency Triage",
        "desc": "异常信号：血压 185/110、胸闷头晕 → 紧急分诊 → 通知医生",
        "conversation": [
            ("⚠️ 系 统", "异常信号检测：血压 185/110 mmHg 超过危险阈值，触发紧急分诊协议。"),
            ("🤖 健康助手", "王叔叔，我收到了您手环的紧急警报，您的血压非常高。请问您现在是否感到胸痛或者呼吸困难？"),
            ("👤 患 者", "我头很晕，胸口闷得慌，今天早上忘了吃降压药。"),
            ("🤖 健康助手", "好的，请您先坐下来，不要活动。我正在为您联系医生并查询最近的医院。请保持电话畅通。"),
            ("🚑 系 统", "已触发紧急协议：查询附近急诊科 → 通知主治医生 → 通知社区工作者。正在生成紧急分诊报告。"),
        ],
        "patch": {
            "memory": {
                "patient_long_term_profile": "王建国，男，72岁。诊断：高血压（10年）、2型糖尿病（5年）、高脂血症。长期用药：氨氯地平 5mg qd、二甲双胍 500mg bid、阿托伐他汀 20mg qn。独居，无家属在身边。",
                "recent_health_dynamics": "今日凌晨血压飙升至185/110mmHg，触发高血压警报。患者反映头晕、胸闷。近一周血压控制不佳，多次超过160mmHg。",
            },
            "signals": {
                "summary_text": "紧急警报：血压185/110mmHg，超过危险阈值。心率偏快95bpm。患者自述胸闷头晕。",
                "anomalies": ["血压危象", "心率偏快", "患者自述胸闷头晕"],
            },
            "latest_health": {"blood_pressure": "185/110", "heart_rate": 95, "blood_oxygen": 93, "blood_glucose": 8.5, "steps": 200},
            "adherence_analysis": {
                "statuses": ["疑似漏服降压药"], "preferences": [],
                "interventions": ["紧急评估"], "suggestions": ["立即联系医生"],
            },
            "outlier_analysis": {
                "symptoms": ["胸闷", "头晕", "乏力"], "triage": "urgent",
                "patient_suggestions": ["请坐下休息"], "doctor_suggestions": ["紧急随访"],
            },
            "latest_user_message": "我头很晕，胸口闷得慌，今天早上忘了吃降压药。",
        },
    },
    "positive": {
        "label": "正向反馈 — Positive Reinforcement",
        "desc": "指标稳定、运动达标 → 鼓励 + 常规报告",
        "conversation": [
            ("🤖 健康助手", "王叔叔，您好呀！看您最近手环的数据，各项指标都不错，真棒！"),
            ("👤 患 者", "我这几天感觉不错，每天都出去走了一圈，昨天还去了社区活动中心。"),
            ("🤖 健康助手", "太好了！您这周每天走了快5000步，血压也控制得很好。多跟大家聊聊天对身心都有好处。"),
            ("👤 患 者", "是啊，认识了几个老伙伴，约好了一起下棋。"),
            ("🤖 健康助手", "真好！我帮您出一份健康报告，您继续保持这个节奏就很棒了！"),
        ],
        "patch": {
            "memory": {
                "patient_long_term_profile": "王建国，男，72岁。诊断：高血压（10年）、2型糖尿病（5年）、高脂血症。长期用药：氨氯地平 5mg qd、二甲双胍 500mg bid、阿托伐他汀 20mg qn。独居，近期状态改善。",
                "recent_health_dynamics": "近一周血压控制良好（125-135mmHg），血糖稳定。步数恢复至日均4500步，睡眠改善。患者情绪积极，主动参加社区活动。",
            },
            "signals": {
                "summary_text": "近7天数据良好：血压稳定，心率正常，活动量达标，睡眠改善。",
                "anomalies": [],
            },
            "latest_health": {"blood_pressure": "132/82", "heart_rate": 68, "blood_oxygen": 97, "blood_glucose": 6.5, "steps": 4800},
            "adherence_analysis": {
                "statuses": ["用药依从性良好", "饮食控制改善", "运动量达标", "睡眠改善"],
                "preferences": ["喜欢面食", "开始喜欢散步"],
                "interventions": [], "suggestions": ["继续保持", "可以尝试全谷物面食"],
            },
            "latest_user_message": "我这几天感觉不错，每天都出去走了一圈，昨天还去了社区活动中心。",
            "recent_dialog_summary": "上次随访患者状态已有改善，建议继续保持。",
        },
    },
}


def build_scenario_payload(scenario_key: str) -> dict:
    s = SCENARIOS[scenario_key]
    payload = _base_payload()
    _deep_merge(payload, s["patch"])
    return payload


def _deep_merge(base: dict, patch: dict):
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ---------------------------------------------------------------------------
# Skill execution pipeline
# ---------------------------------------------------------------------------

def run_skill_pipeline(skill_dir: Path, payload: dict, offline_only: bool = False) -> dict:
    skill = load_skill(skill_dir)
    name = skill["name"]
    print(f"\n  {'─' * 46}")
    print(f"  Skill: {name}")
    print(f"  {'─' * 46}")

    # Phase 1: pre_llm
    if skill["pre_llm"] and skill["pre_llm"].is_file():
        print(f"  [1/3] Running pre_llm ...")
        r = run_script(skill["pre_llm"], json.dumps(payload, ensure_ascii=False, default=str), skill["dir"])
        if r["ok"]:
            try:
                payload["script_data"] = json.loads(r["stdout"])
            except json.JSONDecodeError:
                pass
        else:
            print(f"  [WARN] pre_llm failed: {r['stderr'][:200]}")
    else:
        print(f"  [1/3] pre_llm: 无")

    # Phase 2: LLM
    llm_result = None
    if not offline_only:
        print(f"  [2/3] Calling LLM ...")
        t0 = time.perf_counter()
        prompt = build_skill_prompt(skill, payload)
        raw = call_llm(prompt)
        elapsed = int((time.perf_counter() - t0) * 1000)
        if raw:
            llm_result = extract_json(raw)
        if llm_result:
            if "message" not in llm_result:
                llm_result = {"message": "报告已生成", "structured_output": llm_result}
            elif "structured_output" not in llm_result:
                llm_result = {"message": llm_result.get("message", "报告已生成"), "structured_output": llm_result}
            print(f"    LLM done ({elapsed}ms)")

    if llm_result is None:
        print(f"  [2/3] Offline fallback")
        _, status, triage, risk_tags = analyze_signals(payload)
        if name == "doctor-report":
            llm_result = _offline_doctor(payload, status, triage, risk_tags)
        else:
            llm_result = _offline_patient(payload, status, risk_tags)

    # Phase 3: post_llm (render HTML)
    html_output = None
    if skill["post_llm"] and skill["post_llm"].is_file():
        print(f"  [3/3] Running post_llm (HTML) ...")
        post_input = {"payload": payload, "llm_result": llm_result}
        r = run_script(skill["post_llm"], json.dumps(post_input, ensure_ascii=False, default=str), skill["dir"])
        if r["ok"]:
            try:
                post_data = json.loads(r["stdout"])
                so = post_data.get("structured_output", {})
                if "html" in so:
                    html_output = so["html"]
                    llm_result.setdefault("structured_output", {}).update(so)
                    print(f"    HTML: {len(html_output)} chars")
            except json.JSONDecodeError:
                print(f"  [WARN] post_llm output not valid JSON")
                if r["stderr"]:
                    print(f"    stderr: {r['stderr'][:200]}")
        else:
            print(f"  [WARN] post_llm failed: {r['stderr'][:300]}")
    else:
        print(f"  [3/3] post_llm: 无")

    return {"name": name, "llm_result": llm_result, "html": html_output}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    load_env()

    parser = argparse.ArgumentParser(description="Solo Elderly Skill Orchestrator")
    parser.add_argument("--scenario", choices=["emergency", "adherence", "positive", "auto"],
                        default="auto", help="Scenario (default: auto-detect)")
    parser.add_argument("--input", type=str, help="Custom skill input JSON path")
    parser.add_argument("--offline-only", action="store_true", help="Skip LLM, use rule-based fallback")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open HTML")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # ── Header ──
    print()
    print("=" * 60)
    print("  Solo Elderly Skill — Orchestrator")
    print("  信号触发 → 对话 → 医生报告 + 患者报告")
    print("=" * 60)

    # ── 1. Build payload ──
    if args.input:
        print(f"\n📄 Loading input: {args.input}")
        with open(args.input, "r", encoding="utf-8") as f:
            payload = json.load(f)
        scenario_key, status, triage, risk_tags = analyze_signals(payload)
        print(f"🔍 信号分析 → 场景: {scenario_key.upper()}")
        scenario_data = SCENARIOS.get(scenario_key, SCENARIOS["adherence"])
    elif args.scenario != "auto":
        scenario_key = args.scenario
        scenario_data = SCENARIOS[scenario_key]
        payload = build_scenario_payload(scenario_key)
    else:
        scenario_key = "adherence"
        scenario_data = SCENARIOS[scenario_key]
        payload = build_scenario_payload(scenario_key)
        detected, *_ = analyze_signals(payload)
        if detected != scenario_key and detected in SCENARIOS:
            scenario_key = detected
            scenario_data = SCENARIOS[scenario_key]
            payload = build_scenario_payload(scenario_key)
        print(f"🔍 信号分析 → 场景: {scenario_key.upper()}")

    # Fill timestamps
    payload["meta"]["current_time"] = payload["meta"].get("current_time") or now_iso
    payload["meta"]["session_id"] = payload["meta"].get("session_id") or f"orch_{scenario_key}"
    loc = payload.get("location", {}).get("current", {})
    if loc and not loc.get("record_at"):
        loc["record_at"] = now_iso

    print(f"\n📋 {scenario_data['label']}")
    print(f"   {scenario_data['desc']}")

    # ── 2. Conversation ──
    print(f"\n{'━' * 60}")
    print("  💬 对话过程")
    print(f"{'━' * 60}")
    for role, text in scenario_data.get("conversation", []):
        print(f"\n  {role}:")
        print(f"  {text}")

    # ── 3. Run both skills ──
    print(f"\n{'━' * 60}")
    print("  📊 生成报告")
    print(f"{'━' * 60}")

    doctor = run_skill_pipeline(DOCTOR_SKILL_DIR, json.loads(json.dumps(payload, default=str)), offline_only=args.offline_only)
    patient = run_skill_pipeline(PATIENT_SKILL_DIR, json.loads(json.dumps(payload, default=str)), offline_only=args.offline_only)

    # ── 4. Save outputs ──
    saved = []
    if doctor["html"]:
        p = OUTPUT_DIR / "doctor_report.html"
        p.write_text(doctor["html"], encoding="utf-8")
        saved.append(("🏥 医生端分诊报告", p))
    if patient["html"]:
        p = OUTPUT_DIR / "patient_report.html"
        p.write_text(patient["html"], encoding="utf-8")
        saved.append(("💚 患者端健康报告", p))

    full = {
        "scenario": scenario_key,
        "timestamp": now_iso,
        "payload": payload,
        "doctor_result": doctor["llm_result"],
        "patient_result": patient["llm_result"],
    }
    jp = OUTPUT_DIR / "orchestrator_output.json"
    jp.write_text(json.dumps(full, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # ── 5. Summary ──
    print(f"\n{'━' * 60}")
    print("  ✅ 完成")
    print(f"{'━' * 60}")
    print(f"\n  📁 JSON:  {jp}")
    for label, path in saved:
        print(f"  {label}: {path}")

    if not args.no_browser and saved:
        print(f"\n  正在打开浏览器 ...")
        for _, path in saved:
            webbrowser.open(path.as_uri())

    print()


if __name__ == "__main__":
    main()
