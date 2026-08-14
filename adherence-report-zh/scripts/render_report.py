#!/usr/bin/env python3
"""
post_llm script for adherence-report-zh skill.

Reads {"payload": {...}, "llm_result": {...}} from stdin.
Renders a patient-facing adherence HTML report (Chinese, Baidu Maps).
Writes JSON to stdout with structured_output.html.
"""

from __future__ import annotations

import json
import os
import re
import sys
from html import escape
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "report.html"
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
_TEACHER_ASSET_BASE = "assets/teacher"
_HERO_COMPANION_ASSET = f"{_TEACHER_ASSET_BASE}/hero-companion.png"
_INSIGHT_VISUAL_ASSET = f"{_TEACHER_ASSET_BASE}/insight-eggs.png"
_PROGRESS_TROPHY_ASSET = f"{_TEACHER_ASSET_BASE}/progress-trophy.png"
_PATIENT_HEAD_ASSET = f"{_TEACHER_ASSET_BASE}/patient-head-8.png"
_SUPPORT_PERSON_ASSET = f"{_TEACHER_ASSET_BASE}/support-person.png"
_JD_SEARCH_BASE = "https://search.jd.com/Search?keyword="
_HEMA_HOME_URL = "https://www.freshhema.com/"

try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

_STATUS_MAP = {
    "stable": ("bg-emerald-100 text-emerald-800", "✅", "状态良好"),
    "at_risk": ("bg-amber-100 text-amber-800", "⚠️", "需要关注"),
}

_COND_COLORS = {
    "高血压": "bg-rose-500",
    "2型糖尿病": "bg-amber-500",
    "糖尿病": "bg-amber-500",
    "高脂血症": "bg-orange-500",
    "冠心病": "bg-red-500",
    "化疗期间": "bg-purple-500",
    "Hypertension": "bg-rose-500",
    "Type 2 diabetes": "bg-amber-500",
    "Diabetes": "bg-amber-500",
    "Hyperlipidemia": "bg-orange-500",
    "Coronary artery disease": "bg-red-500",
}

_RISK_TAG_COLORS = {
    "心率": "bg-rose-50 text-rose-700 border-rose-200",
    "血压": "bg-rose-50 text-rose-700 border-rose-200",
    "血糖": "bg-amber-50 text-amber-700 border-amber-200",
    "活动": "bg-sky-50 text-sky-700 border-sky-200",
    "食欲": "bg-orange-50 text-orange-700 border-orange-200",
    "偏低": "bg-amber-50 text-amber-700 border-amber-200",
    "偏高": "bg-rose-50 text-rose-700 border-rose-200",
    "下降": "bg-orange-50 text-orange-700 border-orange-200",
    "漏服": "bg-rose-50 text-rose-700 border-rose-200",
    "heart rate": "bg-rose-50 text-rose-700 border-rose-200",
    "blood pressure": "bg-rose-50 text-rose-700 border-rose-200",
    "glucose": "bg-amber-50 text-amber-700 border-amber-200",
    "activity": "bg-sky-50 text-sky-700 border-sky-200",
    "appetite": "bg-orange-50 text-orange-700 border-orange-200",
}

_VITAL_DEFS = [
    ("blood_pressure", "血压", "mmHg", "💓"),
    ("heart_rate", "心率", "bpm", "❤️"),
    ("blood_oxygen", "血氧", "%", "🫁"),
    ("blood_glucose", "血糖", "mmol/L", "🩸"),
    ("steps_today", "今日步数", "步", "🚶"),
]

_REC_ICONS = ["💊", "🚶", "🫀", "🩸", "🧈", "🥗", "🧘", "💤"]
_CATEGORY_ICONS = {"medication": "💊", "diet": "🥗", "exercise": "🏃", "monitoring": "📋", "lifestyle": "🏠"}
_NUTRITION_CATEGORY_ICONS = {
    "low_salt": "🧂",
    "low_oil": "🥘",
    "protein": "🥚",
    "hydration": "🥤",
    "fiber": "🥬",
    "meal_rhythm": "🍽️",
}

_ADHERENCE_DIMENSIONS = [
    ("medication", "💊", "用药"),
    ("appetite", "🍽️", "食欲与饮食"),
    ("exercise", "🏃", "运动与活动"),
    ("monitoring", "📋", "健康监测"),
]

_FIELD_LABELS = {
    "issues": "问题",
    "adjustments": "调整建议",
    "cause_if_known": "可能原因",
    "suggestions": "建议",
    "barriers": "障碍",
    "plan": "计划",
    "gaps": "缺口",
}

_GOOD_STATUS_KEYWORDS = (
    "good", "on track", "compliant", "met", "adequate", "consistent",
    "良好", "达标", "按时", "充足", "稳定", "正常", "较好",
)


_AI_MSG_STYLES = {
    "good_news": {"icon": "🎉", "color": "bg-emerald-50 border-emerald-200", "title_color": "text-emerald-800"},
    "attention": {"icon": "⚠️", "color": "bg-amber-50 border-amber-200", "title_color": "text-amber-800"},
    "plan": {"icon": "📝", "color": "bg-blue-50 border-blue-200", "title_color": "text-blue-800"},
    "encouragement": {"icon": "💪", "color": "bg-purple-50 border-purple-200", "title_color": "text-purple-800"},
}


def _render_ai_message(so: dict) -> str:
    """Render AI message as always-visible sub-cards when structured sections are available."""
    sections = so.get("assistant_message_sections") or []

    if sections:
        html = ""
        for sec in sections:
            sec_type = sec.get("type", "")
            title = _localize_zh_text(sec.get("title", ""))
            content = _localize_zh_text(sec.get("content", ""))
            style = _AI_MSG_STYLES.get(
                sec_type,
                {"icon": "💬", "color": "bg-slate-50 border-slate-200", "title_color": "text-slate-800"},
            )

            html += (
                f'<div class="sub-card sub-card-static {style["color"]}">'
                f'<div class="sub-card-header" style="padding:12px 14px 8px">'
                f'<span class="sub-card-icon" style="font-size:1.2em">{style["icon"]}</span>'
                f'<div class="flex-1 min-w-0">'
                f'<div class="sub-card-value {style["title_color"]}" style="font-size:0.95em">{escape(title)}</div>'
                f'</div>'
                f'</div>'
                f'<div class="sub-card-body">'
                f'<div class="text-sm text-slate-700 leading-relaxed">{escape(content)}</div>'
                f'</div></div>'
            )
        return html

    plain = _localize_zh_text(so.get("assistant_message_patient") or "")
    if not plain:
        return ""
    preview = escape(plain[:70]) + ("..." if len(plain) > 70 else "")
    return (
        f'<div class="sub-card sub-card-static bg-slate-50 border-slate-200">'
        f'<div class="sub-card-header" style="padding:12px 14px 8px">'
        f'<span class="sub-card-icon" style="font-size:1.2em">💬</span>'
        f'<div class="flex-1 min-w-0">'
        f'<div class="sub-card-value" style="font-size:0.9em;font-weight:600;color:#334155">{preview}</div>'
        f'</div>'
        f'</div>'
        f'<div class="sub-card-body">'
        f'<div class="text-sm text-slate-700 leading-relaxed">{escape(plain)}</div>'
        f'</div></div>'
    )


def _render_escalation_banner(escalations: list[dict]) -> str:
    """Render prominent warning banners for triggered escalation rules."""
    if not escalations:
        return ""

    html = ""
    for esc in escalations:
        if esc["level"] == "critical":
            banner_cls = "bg-gradient-to-r from-rose-50 to-red-50 border-rose-300"
            icon = "🚨"
            title_cls = "text-rose-800"
            badge_cls = "bg-rose-600 text-white"
            badge_text = "紧急"
        else:
            banner_cls = "bg-gradient-to-r from-amber-50 to-orange-50 border-amber-300"
            icon = "⚠️"
            title_cls = "text-amber-800"
            badge_cls = "bg-amber-500 text-white"
            badge_text = "需关注"

        html += (
            f'<div class="rounded-xl border-2 {banner_cls} p-5 mb-3">'
            f'<div class="flex items-center gap-2 mb-2">'
            f'<span class="text-xl">{icon}</span>'
            f'<span class="text-sm font-bold {title_cls} flex-1">{escape(esc["title"])}</span>'
            f'<span class="px-2 py-0.5 rounded-full text-[10px] font-bold {badge_cls}">{badge_text}</span>'
            f'</div>'
            f'<p class="text-sm text-slate-700 leading-relaxed mb-3">{escape(esc["message"])}</p>'
            f'<div class="flex items-start gap-2 bg-white/70 rounded-lg p-3 border border-slate-200">'
            f'<span class="text-sm mt-0.5">💡</span>'
            f'<div class="text-xs text-slate-600 leading-relaxed">'
            f'<span class="font-semibold">建议：</span>{escape(esc["recommendation"])}'
            f'</div></div>'
            f'</div>'
        )
    return html


def _load_env() -> None:
    if _ENV_PATH.is_file():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


_ZH_PHRASE_REPLACEMENTS = [
    ("Margaret Chen, female, 71 years old.", "Margaret Chen，女性，71岁。"),
    ("Diagnosed with", "已诊断"),
    ("Post-surgery recovery", "术后恢复期"),
    ("knee replacement", "膝关节置换术"),
    ("weeks ago", "周前"),
    ("Lives alone, daughter visits weekly.", "独居，女儿每周探访一次。"),
    ("Over the past 14 days:", "过去14天："),
    ("appetite noticeably decreased", "食欲明显下降"),
    ("likely related to metformin side effects and post-surgery discomfort", "可能与二甲双胍副作用及术后不适有关"),
    ("Steps dropped from average 4,000/day to about 1,500/day.", "步数从日均4,000步下降到约1,500步。"),
    ("Blood pressure stable around 138/85.", "血压大致稳定在138/85左右。"),
    ("Blood glucose slightly elevated at 7.0-7.4 fasting.", "空腹血糖轻度偏高，约为7.0-7.4。"),
    ("Reports feeling tired and not wanting to eat much.", "近期容易疲劳，营养摄入意愿下降。"),
    ("Hypertension", "高血压"),
    ("hypertension", "高血压"),
    ("Type 2 diabetes", "2型糖尿病"),
    ("type 2 diabetes", "2型糖尿病"),
    ("Diabetes", "糖尿病"),
    ("diabetes", "糖尿病"),
    ("Hyperlipidemia", "高脂血症"),
    ("hyperlipidemia", "高脂血症"),
    ("Coronary artery disease", "冠心病"),
    ("coronary artery disease", "冠心病"),
    ("During chemotherapy", "化疗期间"),
    ("during chemotherapy", "化疗期间"),
    ("Current medications", "当前用药"),
    ("Medications", "用药"),
    ("blood pressure", "血压"),
    ("heart rate", "心率"),
    ("blood oxygen", "血氧"),
    ("blood glucose", "血糖"),
    ("glucose", "血糖"),
    ("Activity level declining", "活动量下降"),
    ("Low activity level", "活动量偏低"),
    ("No home exits in 5 days", "连续5天未外出"),
    ("Appetite decreased", "食欲下降"),
    ("Glucose monitoring gaps", "血糖监测有缺口"),
    ("Mostly on track", "基本稳定"),
    ("Decreased", "下降"),
    ("Below target", "低于目标"),
    ("Needs improvement", "需要加强"),
    ("Skipped metformin twice due to nausea after meals", "曾因进食后恶心，二甲双胍漏服两次"),
    ("Consider taking metformin with food or asking your doctor about extended-release formulation", "可考虑改为随餐服用二甲双胍，或与医生讨论是否调整为缓释剂型"),
    ("Likely metformin-related nausea combined with post-surgery fatigue and reduced activity", "可能与二甲双胍引起的恶心、术后疲劳及活动减少共同相关"),
    ("Try smaller, more frequent meals. Warm soups and soft foods may be easier to tolerate.", "可尝试少量多次的营养补充，温热流质或软质食物通常更容易耐受。"),
    ("Knee pain from recent surgery limits walking distance and duration", "近期手术后的膝部疼痛限制了步行距离和时长"),
    ("Start with 10-minute seated exercises twice daily. Add short walks (5 min) as tolerated.", "可先从每日两次10分钟坐姿练习开始，再根据耐受情况加入5分钟短距离步行。"),
    ("Missed glucose checks on 3 days. Blood pressure monitoring is consistent.", "有3天漏测血糖，血压监测相对稳定。"),
    ("Missed 血糖 checks on 3 days. Blood pressure monitoring is consistent.", "有3天漏测血糖，血压监测相对稳定。"),
    ("Small & frequent", "少量多次"),
    ("Medication timing", "用药时机"),
    ("Gentle foods first", "先选择温和易耐受的食物"),
    ("Stay hydrated", "注意补水"),
    ("When appetite is low, eat 5-6 small meals rather than 3 large ones. Even a few bites help.", "当营养摄入意愿下降时，可将三餐分成5到6次少量补充，即使只吃几口也有帮助。"),
    ("Take metformin in the middle of eating (not on an empty stomach) to reduce nausea.", "二甲双胍建议随餐服用，避免空腹，以减少恶心。"),
    ("Start with warm, soft foods like oatmeal, soups, and eggs when your stomach feels sensitive.", "胃部较敏感时，可优先选择燕麦粥、汤类、鸡蛋等温热软质食物。"),
    ("Sip water throughout the day. Warm herbal tea can also help with appetite and digestion.", "白天分次补水即可，温热花草茶也有助于改善食欲与消化。"),
    ("Margaret, since your appetite is lower right now, focus on nutrient-dense foods in smaller portions. Warm oatmeal, soft-boiled eggs, and broth-based soups are gentle on the stomach. Add a handful of nuts or a small piece of fruit as snacks between meals to keep your energy up.", "Margaret，您目前营养摄入意愿偏低，建议优先选择高营养密度、少量多次的饮食安排。温热燕麦粥、溏心蛋和清汤类食物对胃部更温和，两餐之间可加一小把坚果或少量水果，帮助维持体力。"),
    ("Margaret's adherence data over 14 days shows a clear pattern: medication compliance is good except for metformin-related nausea, appetite is reduced likely due to the combination of metformin side effects and post-surgery recovery, and activity levels have dropped significantly due to knee pain. The meal plan focuses on easy-to-digest, nutrient-dense options that address all three conditions while being gentle on her stomach.", "Margaret近14天的执行数据呈现出较清晰的模式：除二甲双胍相关恶心外，用药总体较稳定；营养摄入下降可能与药物副作用和术后恢复共同相关；活动量则因膝部疼痛明显减少。当前膳食计划优先选择易消化、营养密度高、同时兼顾三项慢病管理的方案。"),
    ("Low sodium, high potassium", "低钠、高钾"),
    ("Low GI, controlled portions", "低升糖指数、控制份量"),
    ("Low saturated fat, high fiber", "低饱和脂肪、高纤维"),
    ("Leafy greens, bananas, sweet potatoes, fish", "绿叶蔬菜、香蕉、红薯、鱼类"),
    ("Canned soups, deli meats, soy sauce, pickles", "罐头汤、加工肉类、酱油、腌制食品"),
    ("Oatmeal, lentils, non-starchy vegetables, nuts", "燕麦、扁豆、非淀粉类蔬菜、坚果"),
    ("White bread, sugary drinks, pastries, white rice", "白面包、含糖饮料、糕点、白米饭"),
    ("Salmon, olive oil, oats, almonds", "三文鱼、橄榄油、燕麦、杏仁"),
    ("Fried foods, butter, fatty meats, full-fat dairy", "油炸食品、黄油、高脂肉类、全脂乳制品"),
    ("Warm oatmeal with banana", "香蕉燕麦粥"),
    ("Soft-boiled egg", "溏心蛋"),
    ("Chicken broth with vegetables", "蔬菜鸡汤"),
    ("Whole wheat crackers", "全麦饼干"),
    ("Baked salmon fillet", "烤三文鱼"),
    ("Steamed broccoli", "清蒸西兰花"),
    ("Brown rice (small portion)", "糙米饭（小份）"),
    ("Greek yogurt with berries", "希腊酸奶配莓果"),
    ("Handful of almonds", "一小把杏仁"),
    ("Lentil soup", "扁豆汤"),
    ("Side salad with olive oil", "橄榄油蔬菜沙拉"),
    ("Grilled chicken breast", "烤鸡胸肉"),
    ("Roasted sweet potato", "烤红薯"),
    ("Sauteed spinach", "清炒菠菜"),
    ("Scrambled eggs on toast", "吐司炒蛋"),
    ("Sliced avocado", "牛油果切片"),
    ("Tuna salad (light mayo)", "金枪鱼沙拉（少酱）"),
    ("Apple slices", "苹果切片"),
    ("Turkey meatballs", "火鸡肉丸"),
    ("Quinoa pilaf", "藜麦饭"),
    ("Steamed green beans", "清蒸四季豆"),
    ("Low GI, gentle on stomach", "低升糖、对胃部更温和"),
    ("Lean protein boost", "补充优质蛋白"),
    ("Low sodium, hydrating", "低钠、帮助补水"),
    ("Slow-release carbs", "缓释碳水"),
    ("Heart-healthy omega-3", "有益心血管的Omega-3"),
    ("Potassium-rich", "富含钾"),
    ("High fiber whole grain", "高纤维全谷物"),
    ("Protein + low GI fruit", "蛋白质搭配低升糖水果"),
    ("Healthy fats, fiber", "健康脂肪与膳食纤维"),
    ("Low GI, high protein", "低升糖、高蛋白"),
    ("Heart-healthy fats", "有益心血管的脂肪来源"),
    ("Lean protein", "优质瘦蛋白"),
    ("Magnesium + potassium", "补充镁和钾"),
    ("Protein-rich start", "高蛋白开场"),
    ("Healthy monounsaturated fat", "富含健康单不饱和脂肪"),
    ("Omega-3 fatty acids", "富含Omega-3脂肪酸"),
    ("Fiber-rich, low GI snack", "高纤维、低升糖加餐"),
    ("Complete protein grain", "兼具完整蛋白的谷物"),
    ("Low sodium, high fiber", "低钠、高纤维"),
    ("This report was generated by an AI health assistant for information only. It is not medical advice. If you feel unwell, please contact your doctor or call emergency services. Always follow your clinician's instructions regarding medications and treatment.", "本报告由AI健康助手生成，仅供参考，不能替代专业医疗建议。如有不适，请及时联系医生或急救服务，并始终遵循临床医生关于用药和治疗的指导。"),
]


_ZH_MEDICATION_MAP = {
    "amlodipine": "氨氯地平",
    "metformin": "二甲双胍",
    "atorvastatin": "阿托伐他汀",
    "atorvastatin calcium": "阿托伐他汀钙",
    "aspirin": "阿司匹林",
    "clopidogrel": "氯吡格雷",
    "losartan": "氯沙坦",
    "valsartan": "缬沙坦",
    "lisinopril": "赖诺普利",
    "enalapril": "依那普利",
    "perindopril": "培哚普利",
    "telmisartan": "替米沙坦",
    "irbesartan": "厄贝沙坦",
    "olmesartan": "奥美沙坦",
    "metoprolol": "美托洛尔",
    "bisoprolol": "比索洛尔",
    "carvedilol": "卡维地洛",
    "nifedipine": "硝苯地平",
    "felodipine": "非洛地平",
    "hydrochlorothiazide": "氢氯噻嗪",
    "indapamide": "吲达帕胺",
    "spironolactone": "螺内酯",
    "torsemide": "托拉塞米",
    "rosuvastatin": "瑞舒伐他汀",
    "simvastatin": "辛伐他汀",
    "pravastatin": "普伐他汀",
    "ezetimibe": "依折麦布",
    "furosemide": "呋塞米",
    "digoxin": "地高辛",
    "warfarin": "华法林",
    "rivaroxaban": "利伐沙班",
    "apixaban": "阿哌沙班",
    "dabigatran": "达比加群",
    "nitroglycerin": "硝酸甘油",
    "isosorbide mononitrate": "单硝酸异山梨酯",
    "metoprolol succinate": "琥珀酸美托洛尔",
    "metoprolol tartrate": "酒石酸美托洛尔",
    "glimepiride": "格列美脲",
    "gliclazide": "格列齐特",
    "glyburide": "格列本脲",
    "glipizide": "格列吡嗪",
    "acarbose": "阿卡波糖",
    "pioglitazone": "吡格列酮",
    "sitagliptin": "西格列汀",
    "linagliptin": "利格列汀",
    "vildagliptin": "维格列汀",
    "saxagliptin": "沙格列汀",
    "empagliflozin": "恩格列净",
    "dapagliflozin": "达格列净",
    "canagliflozin": "卡格列净",
    "semaglutide": "司美格鲁肽",
    "dulaglutide": "度拉糖肽",
    "liraglutide": "利拉鲁肽",
    "insulin glargine": "甘精胰岛素",
    "insulin lispro": "赖脯胰岛素",
    "insulin aspart": "门冬胰岛素",
    "insulin detemir": "地特胰岛素",
    "omeprazole": "奥美拉唑",
    "esomeprazole": "埃索美拉唑",
    "pantoprazole": "泮托拉唑",
    "lansoprazole": "兰索拉唑",
    "rabeprazole": "雷贝拉唑",
    "famotidine": "法莫替丁",
    "sucralfate": "硫糖铝",
    "domperidone": "多潘立酮",
    "mosapride": "莫沙必利",
    "levothyroxine": "左甲状腺素",
    "allopurinol": "别嘌醇",
    "colchicine": "秋水仙碱",
    "gabapentin": "加巴喷丁",
    "pregabalin": "普瑞巴林",
    "sertraline": "舍曲林",
    "escitalopram": "艾司西酞普兰",
    "alprazolam": "阿普唑仑",
    "zolpidem": "唑吡坦",
    "acetaminophen": "对乙酰氨基酚",
    "paracetamol": "对乙酰氨基酚",
    "ibuprofen": "布洛芬",
    "naproxen": "萘普生",
    "diclofenac": "双氯芬酸",
    "celecoxib": "塞来昔布",
    "tramadol": "曲马多",
    "amoxicillin": "阿莫西林",
    "amoxicillin clavulanate": "阿莫西林克拉维酸",
    "azithromycin": "阿奇霉素",
    "clarithromycin": "克拉霉素",
    "levofloxacin": "左氧氟沙星",
    "cefuroxime": "头孢呋辛",
    "cefdinir": "头孢地尼",
    "omeprazole": "奥美拉唑",
}


_ZH_DOSING_MAP = {
    "qd": "每日1次",
    "bid": "每日2次",
    "tid": "每日3次",
    "qid": "每日4次",
    "qhs": "每晚1次",
    "qn": "每晚1次",
    "prn": "按需使用",
}


_ZH_FORMULATION_MAP = {
    "xr": "缓释",
    "er": "缓释",
    "sr": "缓释",
    "cr": "控释",
    "dr": "肠溶",
    "ir": "速释",
    "extended-release": "缓释",
    "extended release": "缓释",
    "sustained-release": "缓释",
    "sustained release": "缓释",
    "controlled-release": "控释",
    "controlled release": "控释",
    "delayed-release": "肠溶",
    "delayed release": "肠溶",
    "immediate-release": "速释",
    "immediate release": "速释",
    "tablet": "片",
    "tablets": "片",
    "capsule": "胶囊",
    "capsules": "胶囊",
    "cap": "胶囊",
    "tab": "片",
    "injection": "注射液",
    "injectable": "注射剂",
    "solution": "溶液",
    "oral solution": "口服溶液",
    "suspension": "混悬液",
    "oral suspension": "口服混悬液",
    "syrup": "糖浆",
    "cream": "乳膏",
    "ointment": "软膏",
    "gel": "凝胶",
    "patch": "贴剂",
    "spray": "喷雾剂",
    "drop": "滴剂",
    "drops": "滴剂",
}


def _localize_zh_text(text: str) -> str:
    if not text:
        return ""
    localized = re.sub(r"\s+", " ", str(text)).strip()
    if localized and not re.search(r"[\u4e00-\u9fff]", localized) and re.search(r"[ÃÂÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ]", localized):
        for encoding in ("latin-1", "cp1252"):
            try:
                repaired = localized.encode(encoding).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            if re.search(r"[\u4e00-\u9fff]", repaired):
                localized = repaired
                break
    for source, target in _ZH_PHRASE_REPLACEMENTS:
        localized = localized.replace(source, target)
    for source, target in sorted(_ZH_MEDICATION_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        localized = re.sub(rf"\b{re.escape(source)}\b", target, localized, flags=re.IGNORECASE)
    for source, target in sorted(_ZH_DOSING_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        localized = re.sub(rf"\b{re.escape(source)}\b", target, localized, flags=re.IGNORECASE)
    for source, target in sorted(_ZH_FORMULATION_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        localized = re.sub(rf"\b{re.escape(source)}\b", target, localized, flags=re.IGNORECASE)
    localized = re.sub(r"\((\d+)\s+years\)", r"（\1年）", localized)
    localized = re.sub(r"\((\d+)\s+year\)", r"（\1年）", localized)
    localized = re.sub(r"(\d+)\s+years old", r"\1岁", localized)
    localized = re.sub(r"\b(\d+(?:\.\d+)?)\s*mg\b", r"\1mg", localized, flags=re.IGNORECASE)
    localized = re.sub(r"\b(\d+(?:\.\d+)?)\s*ml\b", r"\1mL", localized, flags=re.IGNORECASE)
    localized = re.sub(r"([A-Za-z\u4e00-\u9fff]+)\s+缓释\s+片", r"\1缓释片", localized)
    localized = re.sub(r"([A-Za-z\u4e00-\u9fff]+)\s+控释\s+片", r"\1控释片", localized)
    localized = re.sub(r"([A-Za-z\u4e00-\u9fff]+)\s+肠溶\s+片", r"\1肠溶片", localized)
    localized = re.sub(r"([A-Za-z\u4e00-\u9fff]+)\s+片", r"\1片", localized)
    localized = re.sub(r"([A-Za-z\u4e00-\u9fff]+)\s+胶囊", r"\1胶囊", localized)
    localized = re.sub(r"([A-Za-z\u4e00-\u9fff]+)\s+注射液", r"\1注射液", localized)
    localized = re.sub(r"\s{2,}", " ", localized).strip()
    return localized


def _localize_zh_value(value: object) -> object:
    if isinstance(value, str):
        return _localize_zh_text(value)
    if isinstance(value, list):
        return [_localize_zh_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _localize_zh_value(item) for key, item in value.items()}
    return value


def _memory_archive_text(memory: dict) -> str:
    text = str(memory.get("archive") or "").strip()
    return _localize_zh_text(text).strip()


def _memory_recent_text(memory: dict) -> str:
    recent = memory.get("recent")
    direct_recent = str(memory.get("recent_health_dynamics") or "").strip()
    if isinstance(recent, dict):
        parts = [str(recent.get(key) or "").strip() for key in ("adherence", "outlier")]
        if direct_recent:
            parts.append(direct_recent)
        return "\n".join(part for part in parts if part)
    return direct_recent


_SIMPLIFIED_COMMUNICATION_KEYWORDS = (
    "认知", "记忆", "意识障碍", "痴呆", "阿尔茨", "谵妄", "说不清", "记不住", "多奈哌齐",
)
_HIGH_BURDEN_KEYWORDS = (
    "术后", "手术", "骨折", "疼痛", "化疗", "感染", "脓毒", "住院", "卧床", "呼吸困难", "意识障碍",
)
_RECENT_GUARDRAIL_NOTE = (
    "memory.recent 仅作为近期变化线索，页面已优先结合本次遵从记录、具体日期和客观指标整理，不把它当作单独医学结论。"
)


def _extract_numbers(value: object) -> list[float]:
    if value is None:
        return []
    cleaned = str(value).replace(",", "")
    return [float(part) for part in re.findall(r"\d+(?:\.\d+)?", cleaned)]


def _parse_iso_datetime(raw: object) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def _extract_patient_age(payload: dict, memory: dict) -> int | None:
    patient = payload.get("patient") or {}
    current_time = _parse_iso_datetime((payload.get("meta") or {}).get("current_time")) or datetime.now()
    if isinstance(patient, dict):
        birthday = _parse_iso_datetime(patient.get("birthday"))
        if birthday:
            age = current_time.year - birthday.year - ((current_time.month, current_time.day) < (birthday.month, birthday.day))
            if 0 < age < 120:
                return age

    archive_text = _memory_archive_text(memory)
    age_match = re.search(r"(\d{1,3})\s*岁", archive_text)
    if age_match:
        age = int(age_match.group(1))
        if 0 < age < 120:
            return age
    age_match = re.search(r"(\d{1,3})\s*years?\s*old", archive_text, flags=re.IGNORECASE)
    if age_match:
        age = int(age_match.group(1))
        if 0 < age < 120:
            return age
    return None


def _json_for_script(value: object) -> str:
    """Serialize JSON without allowing data to terminate an inline script."""
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _format_latest_health_value(key: str, value: object) -> str:
    if value in (None, ""):
        return ""
    if key == "blood_pressure" and isinstance(value, dict):
        sbp = value.get("sbp") or value.get("systolic")
        dbp = value.get("dbp") or value.get("diastolic")
        if sbp not in (None, "") and dbp not in (None, ""):
            return f"{sbp}/{dbp}"
    return str(value).strip()


def _latest_health_summary_from_payload(payload: dict) -> dict:
    latest = payload.get("latest_health") or {}
    if not isinstance(latest, dict):
        return {}

    summary = {}
    for key in ("blood_pressure", "heart_rate", "blood_oxygen", "blood_glucose"):
        value = _format_latest_health_value(key, latest.get(key))
        if value:
            summary[key] = value

    steps = latest.get("steps_today")
    if steps in (None, ""):
        steps = latest.get("steps")
    value = _format_latest_health_value("steps_today", steps)
    if value:
        summary["steps_today"] = value
    return summary


def _sanitize_latest_health_summary(so: dict, payload: dict) -> None:
    summary = _latest_health_summary_from_payload(payload)
    if summary:
        so["latest_health_summary"] = summary
        return
    if not summary:
        so.pop("latest_health_summary", None)


def _payload_has_blood_glucose(payload: dict) -> bool:
    latest = payload.get("latest_health") or {}
    if isinstance(latest, dict) and latest.get("blood_glucose") not in (None, ""):
        return True

    trends = payload.get("signal_trends") or {}
    if not isinstance(trends, dict):
        return False
    for window in trends.values():
        if not isinstance(window, dict):
            continue
        metrics = window.get("metrics") or {}
        if isinstance(metrics, dict) and metrics.get("blood_glucose"):
            return True
    return False


def _rewrite_guarded_text(text: str, *, has_blood_glucose: bool) -> str:
    replacements = [
        ("请补服漏服的降压药", "请按医嘱确认漏服降压药的处理方式"),
        ("补服漏服的降压药", "按医嘱确认漏服降压药的处理方式"),
        ("立即补服", "按医嘱确认漏服处理方式"),
        ("极可能是", "可能是"),
        ("高度相关", "可能相关"),
        ("直接诱因", "可能诱因"),
        ("直接原因", "可能原因"),
        ("可能直接导致", "可能导致"),
        ("直接导致", "可能导致"),
        ("很快会恢复", "逐步恢复"),
        ("立即停止食用", "先暂停"),
        ("立即转为", "下一餐先转为"),
        ("立即恢复", "下一餐先恢复"),
    ]
    if not has_blood_glucose:
        replacements.extend(
            [
                ("血糖和血压", "血压和主食节奏"),
                ("血压和血糖", "血压和主食节奏"),
                ("血糖控制", "主食管理"),
                ("平稳血糖", "让主食节奏更稳定"),
                ("稳定血糖", "保持主食节奏稳定"),
                ("血糖稳定", "主食节奏稳定"),
                ("影响血糖", "影响主食管理"),
                ("辅助控制血糖", "帮助规律活动"),
                ("低升糖", "主食较稳"),
                ("血糖", "主食管理"),
            ]
        )

    cleaned = text
    for source, target in replacements:
        cleaned = cleaned.replace(source, target)
    return cleaned


def _apply_output_guards(value: object, *, has_blood_glucose: bool) -> object:
    if isinstance(value, str):
        return _rewrite_guarded_text(value, has_blood_glucose=has_blood_glucose)
    if isinstance(value, list):
        return [_apply_output_guards(item, has_blood_glucose=has_blood_glucose) for item in value]
    if isinstance(value, dict):
        for key, item in list(value.items()):
            value[key] = _apply_output_guards(item, has_blood_glucose=has_blood_glucose)
        return value
    return value


def _sanitize_json_safe(value: object) -> object:
    if isinstance(value, str):
        return re.sub(r"[\ud800-\udfff]", "\ufffd", value)
    if isinstance(value, list):
        return [_sanitize_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {
            _sanitize_json_safe(key) if isinstance(key, str) else key: _sanitize_json_safe(item)
            for key, item in value.items()
        }
    return value


def _adherence_status_label(value: object) -> str:
    raw = str(value or "").strip().lower()
    return {
        "adherent": "已执行",
        "compliant": "已执行",
        "good": "已执行",
        "partial": "部分执行",
        "partially_adherent": "部分执行",
        "non_adherent": "未执行",
        "missed": "未执行",
    }.get(raw, str(value or "待观察"))


def _merge_adherence_payload(so: dict, payload: dict) -> None:
    adherence_payload = payload.get("adherence_analysis") or {}
    if not isinstance(adherence_payload, dict):
        return

    category_map = {
        "medication": "medication",
        "diet": "appetite",
        "appetite": "appetite",
        "exercise": "exercise",
        "activity": "exercise",
        "monitoring": "monitoring",
    }
    field_map = {
        "medication": "issues",
        "appetite": "issues",
        "exercise": "barriers",
        "monitoring": "gaps",
    }

    target = so.get("adherence_analysis")
    if not isinstance(target, dict):
        target = {}

    statuses = adherence_payload.get("statuses") or []
    if isinstance(statuses, list):
        for item in statuses:
            if not isinstance(item, dict):
                continue
            context = item.get("context") or {}
            category = category_map.get(str(context.get("category") or "").strip().lower())
            if not category:
                continue
            output = item.get("output_json")
            if isinstance(output, dict):
                text = str(output.get("text") or "").strip()
            else:
                text = str(output or "").strip()
            if not text:
                continue
            dim = target.get(category)
            if not isinstance(dim, dict):
                dim = {}
            dim.setdefault("status", _adherence_status_label(context.get("overall_status")))
            dim.setdefault(field_map[category], text)
            target[category] = dim

    if target:
        target.setdefault("period", "本次遵从回访")
        so["adherence_analysis"] = target

    suggestions = adherence_payload.get("suggestions") or []
    if not isinstance(suggestions, list):
        return
    recs = so.get("recommendations")
    if isinstance(recs, list) and recs:
        return
    if not isinstance(recs, list):
        recs = []
    existing = {
        str(item.get("text") if isinstance(item, dict) else item).strip()
        for item in recs
    }
    for item in suggestions:
        if isinstance(item, dict):
            output = item.get("output_json")
        else:
            output = item
        text = _clean_recommendation_text(output.get("text") if isinstance(output, dict) else output or "")
        if not text or text in existing:
            continue
        recs.insert(0, {
            "text": text,
            "reason": "来自本次遵从回访的结构化建议。",
            "category": "medication" if "药" in text else "lifestyle",
        })
        existing.add(text)
    if recs:
        so["recommendations"] = recs


def _format_short_date(raw: object) -> str:
    dt = _parse_iso_datetime(raw)
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%d")


def _status_bucket(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"adherent", "compliant", "good", "已执行"}:
        return "good"
    if raw in {"partial", "partially_adherent", "部分执行"}:
        return "mixed"
    if raw in {"non_adherent", "missed", "未执行"}:
        return "needs_attention"
    label = _localize_zh_text(str(value or ""))
    if any(token in label for token in ("良好", "稳定", "达标", "按时")):
        return "good"
    if any(token in label for token in ("部分", "偶尔", "一般")):
        return "mixed"
    if any(token in label for token in ("未", "下降", "偏低", "需要加强", "缺口")):
        return "needs_attention"
    return "neutral"


def _status_category_text(bucket: str) -> tuple[str, str]:
    mapping = {
        "good": ("继续保持", "本次做得不错，值得继续坚持。"),
        "mixed": ("这次还可以再稳一点", "已经有基础了，再把细节补齐会更好。"),
        "needs_attention": ("这次先补上关键一步", "先把最容易漏掉的那一步补回来。"),
        "neutral": ("这次继续观察", "先保持记录，方便下次更准确比较。"),
    }
    return mapping.get(bucket, mapping["neutral"])


def _recent_bucket_from_clue(text: str) -> str:
    clue = _localize_zh_text(str(text or "")).lower()
    if not clue:
        return "neutral"
    good_tokens = ("规律", "连续", "稳定", "良好", "每日步行", "按时", "严格执行", "恢复")
    alert_tokens = ("反复", "高油", "高盐", "卧床", "极低", "下降", "漏", "缺口", "未")
    if any(token in clue for token in good_tokens) and not any(token in clue for token in ("反复", "波动")):
        return "good"
    if any(token in clue for token in alert_tokens):
        return "needs_attention"
    if any(token in clue for token in ("波动", "有时", "偶尔", "反复")):
        return "mixed"
    return "neutral"


def _build_longitudinal_comparison_note(current_bucket: str, recent_bucket: str) -> tuple[str, str]:
    if current_bucket == "good":
        if recent_bucket in {"mixed", "needs_attention"}:
            return ("结合近期记录线索看，这次更稳了，做得很好，继续坚持。", "good")
        return ("这次延续得不错，做得很好，继续坚持。", "good")
    if current_bucket == "mixed":
        if recent_bucket == "good":
            return ("结合近期记录线索看，这次有一点波动，不过您已经有基础，慢慢补回来就好。", "mixed")
        if recent_bucket == "needs_attention":
            return ("结合近期记录线索看，这次已经在往回拉，先把这一小步做稳就很好。", "mixed")
        return ("这一步还在调整中，能做到一部分也值得肯定。", "mixed")
    if current_bucket == "needs_attention":
        if recent_bucket == "good":
            return ("结合近期记录线索看，这次有点松，不过不用一下子补很多，先把关键一步补回来就很好。", "alert")
        if recent_bucket == "mixed":
            return ("这一步最近都比较容易被打断，但只要先补回最关键的一步，就是进步。", "alert")
        return ("这一步最近一直最难，坚持一点点就是在往前走。", "alert")
    return ("这次先继续观察，慢慢把节奏做稳就好。", "neutral")


def _longitudinal_tone_classes(tone: str) -> str:
    return {
        "good": "bg-emerald-50 text-emerald-700 border-emerald-200",
        "mixed": "bg-amber-50 text-amber-700 border-amber-200",
        "alert": "bg-rose-50 text-rose-700 border-rose-200",
    }.get(tone, "bg-slate-50 text-slate-600 border-slate-200")


def _recent_dimension_score(current_bucket: str, recent_bucket: str) -> int:
    base_map = {
        "good": 86,
        "mixed": 72,
        "needs_attention": 60,
        "neutral": 68,
    }
    score = base_map.get(current_bucket, 68)
    if current_bucket == "good" and recent_bucket in {"mixed", "needs_attention"}:
        score += 4
    elif current_bucket == "mixed" and recent_bucket == "needs_attention":
        score += 3
    elif current_bucket == "mixed" and recent_bucket == "good":
        score -= 2
    elif current_bucket == "needs_attention" and recent_bucket == "good":
        score -= 4
    elif current_bucket == "needs_attention" and recent_bucket == "mixed":
        score -= 2
    return max(52, min(94, score))


def _bucket_reference_score(bucket: str) -> int:
    return {
        "good": 82,
        "mixed": 70,
        "needs_attention": 58,
        "neutral": 66,
    }.get(bucket, 66)


def _recent_score_band(score: int) -> str:
    if score >= 84:
        return "稳步保持"
    if score >= 70:
        return "还在找回节奏"
    return "先补关键一步"


def _next_target_score(score: int) -> int:
    if score < 68:
        return 72
    if score < 84:
        return 84
    return 92


def _score_delta_meta(delta: int) -> tuple[str, str]:
    if delta >= 8:
        return (f"↗ 较近段时间 +{delta}", "#10b981")
    if delta >= 3:
        return (f"↗ 比之前稳了 {delta} 分", "#22c55e")
    if delta <= -8:
        return (f"↘ 比之前少了 {abs(delta)} 分", "#f43f5e")
    if delta <= -3:
        return (f"↘ 比之前松了 {abs(delta)} 分", "#fb7185")
    return ("→ 和前段时间接近", "#64748b")


def _build_recent_score_copy(category: str, current_bucket: str, recent_bucket: str) -> tuple[str, str]:
    copy_map = {
        "medication": {
            "good": ("这段时间吃药整体在稳住，做得很好。", "继续把药和固定时间点绑在一起，按现在的节奏保持。"),
            "mixed": ("这段时间吃药偶尔会被打断，但您已经在努力维持。", "先把最容易漏的那一次药和一顿固定的饭绑在一起。"),
            "needs_attention": ("这段时间吃药这一步最容易被打断。", "今天先把下一次药按时吃上，就已经是在往前走。"),
            "neutral": ("这段时间吃药情况还需要继续观察。", "先把下一次服药记录清楚，后面会更容易判断。"),
        },
        "appetite": {
            "good": ("这段时间营养照顾得比之前更稳，值得鼓励。", "继续优先蛋白质和容易入口的小份食物，把这个节奏守住。"),
            "mixed": ("这段时间饮食有时做得到、有时会被状态影响，这很常见。", "不用追求一下子吃很多，先把下一餐吃稳就很好。"),
            "needs_attention": ("这段时间营养这一步最需要被温柔地照顾。", "今天先多补一份蛋白质或加餐，比强迫自己吃很多更重要。"),
            "neutral": ("这段时间营养情况还需要继续观察。", "先把最容易入口的一餐准备好，身体会慢慢跟上。"),
        },
        "exercise": {
            "good": ("这段时间活动节奏在慢慢找回来，做得不错。", "继续保持温和、能坚持的活动量，不用一下子加很多。"),
            "mixed": ("这段时间运动有波动，但愿意动起来本身就很重要。", "先把今天最容易做到的 5 到 10 分钟活动完成。"),
            "needs_attention": ("这段时间活动最容易被疲劳或不舒服打断。", "今天先从最轻的一小段活动开始，哪怕只走一会儿也算进步。"),
            "neutral": ("这段时间活动情况还需要继续观察。", "先从身体最能接受的一小段活动开始。"),
        },
    }
    category_copy = copy_map.get(category, copy_map["exercise"])
    headline, next_step = category_copy.get(current_bucket, category_copy["neutral"])
    if current_bucket == "good" and recent_bucket in {"mixed", "needs_attention"}:
        headline = headline.replace("这段时间", "和前段时间相比，这段时间")
    elif current_bucket == "needs_attention" and recent_bucket == "good":
        headline = headline.replace("这段时间", "和前段时间相比，这段时间")
    return headline, next_step


def _build_recent_overall_summary(scores: list[dict]) -> dict:
    valid_scores = [int(item.get("score")) for item in scores if isinstance(item, dict) and item.get("score") not in (None, "")]
    if not valid_scores:
        return {}
    previous_scores = [int(item.get("previous_score")) for item in scores if isinstance(item, dict) and item.get("previous_score") not in (None, "")]
    target_scores = [int(item.get("target_score")) for item in scores if isinstance(item, dict) and item.get("target_score") not in (None, "")]

    average_score = round(sum(valid_scores) / len(valid_scores))
    previous_average = round(sum(previous_scores) / len(previous_scores)) if previous_scores else average_score
    target_average = round(sum(target_scores) / len(target_scores)) if target_scores else _next_target_score(average_score)
    delta = average_score - previous_average
    delta_label, delta_color = _score_delta_meta(delta)
    good_labels = [
        _localize_zh_text(str(item.get("label") or "")).replace("坚持度", "")
        for item in scores
        if isinstance(item, dict) and str(item.get("tone") or "") == "good"
    ]
    focus_labels = [
        _localize_zh_text(str(item.get("label") or "")).replace("坚持度", "")
        for item in scores
        if isinstance(item, dict) and str(item.get("tone") or "") == "alert"
    ]

    if average_score >= 84:
        summary = "最近整体节奏在稳住，已经有不少地方做得很好。"
    elif average_score >= 70:
        summary = "最近整体已经有基础了，不用一下子做到最好，先把关键几步做稳就行。"
    else:
        summary = "最近这段时间辛苦了，先把最关键的一小步做回来，整体节奏就会慢慢跟上。"

    if good_labels and focus_labels:
        coaching = f"{'、'.join(good_labels[:2])}已经比较稳了，{'、'.join(focus_labels[:2])}先各补一小步就很好。"
    elif good_labels:
        coaching = f"{'、'.join(good_labels[:2])}已经在帮您稳住节奏，继续按现在的方式保持。"
    elif focus_labels:
        coaching = f"这几天先优先照顾{'、'.join(focus_labels[:2])}，一次只调整一小步就可以。"
    else:
        coaching = "先抓住您今天最容易做到的一步，慢慢往前走就很好。"

    return {
        "score": average_score,
        "previous_score": previous_average,
        "target_score": target_average,
        "delta": delta,
        "delta_label": delta_label,
        "delta_color": delta_color,
        "summary": summary,
        "coaching": coaching,
    }


def _summarize_recent_clue(line: str, category: str) -> str:
    text = re.sub(r"\*\*", "", str(line or "")).strip(" -：:")
    if not text:
        return ""

    if category == "exercise":
        if any(token in text for token in ("步行", "散步", "跑步", "运动", "活动")):
            return "近期记忆线索里多次出现步行或日常活动的记录。"
        if "卧床" in text:
            return "近期记忆线索提示活动量一度很低。"
    if category == "appetite":
        if any(token in text for token in ("清淡", "全麦", "蔬菜", "控盐")) and any(token in text for token in ("拉面", "汉堡", "高油", "高盐")):
            return "近期记忆线索提示饮食有做得好的时候，也有反复。"
        if any(token in text for token in ("清淡", "全麦", "蔬菜", "控盐")):
            return "近期记忆线索里多次提到清淡和控盐的饮食安排。"
        if any(token in text for token in ("拉面", "汉堡", "高油", "高盐", "反复")):
            return "近期记忆线索提示饮食还会偶尔偏油偏咸。"
    if category == "medication":
        if any(token in text for token in ("用药", "胰岛素", "华法林", "降压药", "口服")):
            return "近期记忆线索里持续出现了家庭用药管理的信息。"
    if category == "monitoring":
        if any(token in text for token in ("血压", "监测", "测量", "记录")):
            return "近期记忆线索里有连续监测或记录的提示。"
    return ""


def _clean_recommendation_text(value: object) -> str:
    text = _localize_zh_text(str(value or "")).strip()
    if text.lower().startswith("priority-"):
        text = text.split("-", 1)[1].strip()
    return text


def _extract_archive_conditions(memory: dict) -> list[str]:
    text = _memory_archive_text(memory)
    condition_order = [
        ("糖尿病", "糖尿病"),
        ("高血压", "高血压"),
        ("冠心病", "冠心病"),
        ("心房颤动", "心房颤动"),
        ("高脂血症", "高脂血症"),
        ("骨折", "术后康复"),
        ("手术", "术后康复"),
    ]
    found: list[str] = []
    for keyword, label in condition_order:
        if keyword in text and label not in found:
            found.append(label)
    return found


def _extract_archive_section(archive_text: str, *titles: str) -> str:
    if not archive_text:
        return ""
    for title in titles:
        pattern = rf"【{re.escape(title)}】(.*?)(?=【[^】]+】|$)"
        match = re.search(pattern, archive_text, flags=re.S)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return ""


def _clean_recent_memory_line(line: str) -> str:
    text = re.sub(r"\*\*", "", str(line or "")).strip(" -：:")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _simplify_medication_name(value: str) -> str:
    text = re.sub(r"^[、,，;；\s]+", "", str(value or "").strip())
    text = re.sub(r"^(平素长期用药包括|长期用药包括|平素用药包括|包括|先后使用|后转为|给予|另予|并加用|加用|使用)", "", text)
    text = re.sub(r"（.*?）|\(.*?\)", "", text)
    text = re.sub(r"\s+\d+(?:\.\d+)?\s*(?:mg|g|ml|u|iu|ug|μg).*$", "", text, flags=re.I)
    text = re.sub(r"\s+(?:qd|bid|tid|qid|q\d+h|po|iv|ivgtt|ih|im|皮下注射|静脉滴注).*$", "", text, flags=re.I)
    text = re.sub(r"[，,。；;].*$", "", text)
    return text.strip(" ：:。；;，,")


def _extract_medication_tags_from_archive(archive_text: str) -> list[str]:
    if not archive_text:
        return []
    sections = [
        _extract_archive_section(archive_text, "平素/长期用药", "长期用药", "平素用药"),
        _extract_archive_section(archive_text, "住院医嘱", "当前治疗", "治疗经过"),
    ]
    keywords = (
        "胰岛素", "华法林", "氨氯地平", "缬沙坦", "依诺肝素", "美托洛尔", "阿托伐他汀", "瑞舒伐他汀",
        "多奈哌齐", "雷贝拉唑", "亚胺培南", "万古霉素", "奥马环素", "伏立康唑", "ADC", "化疗",
    )
    tags: list[str] = []
    seen: set[str] = set()
    for section in sections:
        if not section:
            continue
        candidates = re.split(r"[；;]", section)
        for candidate in candidates:
            cleaned = _simplify_medication_name(candidate)
            if not cleaned:
                continue
            if not any(keyword in cleaned for keyword in keywords):
                continue
            if cleaned in seen:
                continue
            seen.add(cleaned)
            tags.append(cleaned)
    return tags[:6]


def _pick_recent_treatment_line(memory: dict, theme_kind: str) -> str:
    recent_text = str(((memory.get("recent") or {}).get("adherence")) or "").strip()
    if not recent_text:
        return ""
    keyword_map = {
        "oncology_adc": ("ADC", "化疗", "输液", "治疗", "靶向", "免疫"),
        "oncology_chemo": ("化疗", "输液", "治疗", "肿瘤", "放疗"),
        "surgery_recovery": ("术后", "恢复", "卧床", "活动", "疼痛"),
        "infection_recovery": ("住院强化", "居家维持", "抗感染", "胰岛素", "用药方案"),
        "chronic_medication": ("用药", "胰岛素", "华法林", "降压药", "监测"),
        "general_recovery": ("治疗", "用药", "恢复"),
    }
    for raw_line in recent_text.splitlines():
        line = _clean_recent_memory_line(raw_line)
        if not line:
            continue
        if any(token in line for token in keyword_map.get(theme_kind, ())):
            return line
    return ""


def _extract_archive_conditions(memory: dict) -> list[str]:
    text = _memory_archive_text(memory)
    if not text:
        return []

    normalized = re.sub(r"\s+", "", text).lower()
    condition_order = [
        (("\u7cd6\u5c3f\u75c5", "diabetes", "type2diabetes", "type 2 diabetes"), "\u7cd6\u5c3f\u75c5"),
        (("\u9ad8\u8840\u538b", "hypertension"), "\u9ad8\u8840\u538b"),
        (("\u51a0\u5fc3\u75c5", "coronaryarterydisease", "coronary artery disease", "cad"), "\u51a0\u5fc3\u75c5"),
        (("\u5fc3\u623f\u98a4\u52a8", "\u623f\u98a4", "atrialfibrillation", "atrial fibrillation", "af"), "\u5fc3\u623f\u98a4\u52a8"),
        (("\u9ad8\u8102\u8840\u75c7", "\u9ad8\u8102\u8840\u75c5", "hyperlipidemia", "dyslipidemia"), "\u9ad8\u8102\u8840\u75c7"),
        (("\u9aa8\u6298", "\u624b\u672f", "\u672f\u540e", "\u7f6e\u6362\u672f", "post-surgery", "post surgery", "surgery"), "\u672f\u540e\u5eb7\u590d"),
    ]

    found: list[str] = []
    for keywords, label in condition_order:
        if any(keyword.replace(" ", "").lower() in normalized for keyword in keywords) and label not in found:
            found.append(label)
    return found


def _extract_archive_section(archive_text: str, *titles: str) -> str:
    if not archive_text:
        return ""
    for title in titles:
        pattern = rf"\u3010{re.escape(title)}\u3011(.*?)(?=\u3010[^\u3011]+\u3011|$)"
        match = re.search(pattern, archive_text, flags=re.S)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return ""


def _extract_treatment_cycle_badge(*texts: str) -> str:
    merged = " ".join(str(text or "") for text in texts if text)
    if not merged:
        return ""
    cycle_match = re.search(r"第\s*(\d+)\s*周期", merged, flags=re.I)
    day_match = re.search(r"第\s*(\d+)\s*天", merged, flags=re.I)
    if not cycle_match:
        cycle_match = re.search(r"\bcycle\s*(\d+)\b", merged, flags=re.I)
    if not day_match:
        day_match = re.search(r"\bday\s*(\d+)\b", merged, flags=re.I)

    parts = []
    if cycle_match:
        parts.append(f"第 {cycle_match.group(1)} 周期")
    if day_match:
        parts.append(f"第 {day_match.group(1)} 天")
    return " ".join(parts)


def _build_treatment_education(
    theme_kind: str,
    current_items: dict[str, dict],
    theme_title: str,
    medication_tags: list[str] | None = None,
) -> dict:
    medication_status = _localize_zh_text(str((current_items.get("medication") or {}).get("status_label") or "")).strip()
    appetite_text = _localize_zh_text(str((current_items.get("appetite") or {}).get("text") or "")).strip()
    monitoring_text = _localize_zh_text(str((current_items.get("monitoring") or {}).get("text") or "")).strip()
    monitoring_status = _localize_zh_text(str((current_items.get("monitoring") or {}).get("status_label") or "")).strip()
    medication_tags = [str(tag).strip() for tag in (medication_tags or []) if str(tag).strip()]
    primary_med_tag = medication_tags[0] if medication_tags else ""

    meta = {
        "oncology_adc": {
            "icon": "💜",
            "title": "为什么这几天更要照顾食欲和体力？",
            "body": "在 ADC 治疗主题下，页面会优先提醒输注后几天更容易影响胃口、睡眠和体力，所以建议会更强调补蛋白、补水和把任务做轻一点。",
            "tip": "今天更适合先把吃得下、睡得稳、活动不过量这三件事守住。",
            "page_badge": "1/3",
            "visual_asset": _SUPPORT_PERSON_ASSET,
            "visual_label": "治疗教育",
        },
        "oncology_chemo": {
            "icon": "🧬",
            "title": "为什么治疗后几天会更强调恢复？",
            "body": "围绕化疗或肿瘤治疗的主题里，页面会把营养、睡眠、体力和感染防护放在更前面，而不是只列通用慢病建议。",
            "tip": "如果这几天胃口一般，就先用更小份、更容易入口的食物把蛋白和主食节奏补回来。",
            "page_badge": "1/3",
            "visual_asset": _SUPPORT_PERSON_ASSET,
            "visual_label": "治疗教育",
        },
        "surgery_recovery": {
            "icon": "🩺",
            "title": "为什么术后更强调蛋白和慢慢活动？",
            "body": "术后恢复主题会把伤口恢复、体力回升和活动递进放在一起看，所以建议通常会同时强调补蛋白和循序渐进地走动。",
            "tip": "今天不用追求做很多，能把吃饭、短距离活动和休息节奏做稳就很有价值。",
            "page_badge": "1/2",
            "visual_asset": _SUPPORT_PERSON_ASSET,
            "visual_label": "恢复教育",
        },
        "infection_recovery": {
            "icon": "🛡️",
            "title": "为什么现在更重视规律用药和家庭记录？",
            "body": "这个阶段已经从住院强化支持慢慢转到居家维持，接下来更靠按时用药、观察精神食欲和补齐家庭监测来判断恢复是不是稳住了。",
            "tip": "如果今天能把用药、吃饭和监测三件事都留下一条清楚记录，下次报告就会更贴近真实恢复情况。",
            "page_badge": "1/2",
            "visual_asset": _SUPPORT_PERSON_ASSET,
            "visual_label": "恢复教育",
        },
        "chronic_medication": {
            "icon": "📅",
            "title": "为什么长期管理更看重节奏？",
            "body": "在长期用药主题里，比一次做很多更重要的是把服药、吃饭、活动和监测放进同一个日常节奏里，这样更容易长期坚持。",
            "tip": "把最容易忘的那一步固定到每天同一时间，通常比临时补救更有效。",
            "page_badge": "1/2",
            "visual_asset": _SUPPORT_PERSON_ASSET,
            "visual_label": "用药教育",
        },
        "general_recovery": {
            "icon": "✨",
            "title": "为什么建议会围绕当前治疗来写？",
            "body": "先把治疗背景放在前面，才能让后面的饮食、活动和监测建议更像是为这个病人当前阶段定制，而不是通用模板。",
            "tip": "今天先抓住最贴近当前阶段的 2 到 3 个重点，会比同时改很多事更容易做到。",
            "page_badge": "1/1",
            "visual_asset": _SUPPORT_PERSON_ASSET,
            "visual_label": "恢复教育",
        },
    }
    card = dict(meta.get(theme_kind) or meta["general_recovery"])
    if medication_status and theme_kind in {"infection_recovery", "chronic_medication"}:
        card["tip"] = f"本次回访里的用药状态是“{medication_status}”，接下来更适合继续把服药节奏和家庭记录守住。"
    if monitoring_status == "未执行" or "未测" in monitoring_text:
        card["tip"] = "今天尤其值得先把家庭监测补上，因为这能帮助更早发现恢复是否平稳。"
    if appetite_text and any(token in appetite_text for token in ("半饱", "吃不下", "胃口", "食欲")):
        card["tip"] = "如果今天胃口一般，先别追求吃很多，优先选更容易入口、能补到蛋白质的小份食物。"
    card["theme_title"] = theme_title
    if medication_tags:
        card["medication_line"] = f"这张说明会优先围绕您当前涉及的治疗/药物：{'、'.join(medication_tags[:3])}。"
    elif theme_title:
        card["medication_line"] = f"这张说明会优先围绕您当前的治疗主题“{theme_title}”来讲。"
    else:
        card["medication_line"] = "这张说明会优先围绕您当前正在经历的治疗和恢复阶段来讲。"
    if primary_med_tag:
        if theme_kind == "oncology_adc":
            card["title"] = f"\u4e3a\u4ec0\u4e48 {primary_med_tag} \u6cbb\u7597\u540e\u66f4\u5bb9\u6613\u75b2\u52b3\u548c\u80c3\u53e3\u6ce2\u52a8\uff1f"
        elif theme_kind == "oncology_chemo":
            card["title"] = f"\u4e3a\u4ec0\u4e48\u56f4\u7ed5 {primary_med_tag} \u7684\u6cbb\u7597\u671f\u66f4\u8981\u5148\u987e\u597d\u8425\u517b\u548c\u4f53\u529b\uff1f"
        elif theme_kind == "chronic_medication":
            card["title"] = f"\u4e3a\u4ec0\u4e48\u56f4\u7ed5 {primary_med_tag} \u7684\u957f\u671f\u7ba1\u7406\u66f4\u770b\u91cd\u6bcf\u5929\u8282\u594f\uff1f"
    elif theme_title and theme_kind == "general_recovery":
        card["title"] = f"\u4e3a\u4ec0\u4e48\u73b0\u5728\u8981\u56f4\u7ed5\u201c{theme_title}\u201d\u6765\u5b89\u6392\u5efa\u8bae\uff1f"
    card["feedback_item_name"] = str(card.get("title") or theme_title or "\u75be\u75c5\u6559\u80b2")
    card["feedback_prompt"] = "\u8fd9\u6bb5\u89e3\u91ca\u5bf9\u60a8\u7406\u89e3\u73b0\u5728\u7684\u6cbb\u7597\u548c\u6062\u590d\u6709\u6ca1\u6709\u5e2e\u52a9\uff1f"
    card["feedback_positive_label"] = "\u6709\u5e2e\u52a9"
    card["feedback_positive_active_label"] = "\u5df2\u8bb0\u4e0b"
    card["feedback_negative_label"] = "\u4e0d\u6e05\u695a"
    card["feedback_negative_active_label"] = "\u5df2\u8bb0\u4e0b"
    return card


def _build_treatment_theme(payload: dict, so: dict) -> dict:
    memory = payload.get("memory") or {}
    archive_text = _memory_archive_text(memory)
    recent_text = _memory_recent_text(memory)
    if not archive_text and not recent_text:
        return {}
    if not archive_text:
        archive_text = recent_text

    archive_conditions = _extract_archive_conditions(memory)
    current_items = _collect_current_adherence_items(payload, so)
    admission_section = _extract_archive_section(archive_text, "本次就诊/入院事件", "本次就诊", "入院事件")
    order_section = _extract_archive_section(archive_text, "住院医嘱", "当前治疗", "治疗经过")
    long_term_section = _extract_archive_section(archive_text, "平素/长期用药", "长期用药", "平素用药")
    med_tags = _extract_medication_tags_from_archive(archive_text)

    archive_all = " ".join(part for part in (archive_text, admission_section, order_section, long_term_section) if part)
    archive_all_lower = archive_all.lower()
    current_event_text = " ".join(part for part in (admission_section, order_section) if part) or archive_all
    current_event_lower = current_event_text.lower()
    if "adc" in current_event_lower or "抗体药物偶联" in current_event_text:
        theme_kind = "oncology_adc"
    elif any(token in current_event_text for token in ("化疗", "放疗", "肿瘤", "癌", "靶向", "免疫治疗")):
        theme_kind = "oncology_chemo"
    elif any(token in current_event_text for token in ("感染", "脓毒", "住院", "高热", "抗感染")):
        theme_kind = "infection_recovery"
    elif any(token in current_event_text for token in ("术后", "手术", "骨折手术", "切除术")) or (
        not current_event_text and any(token in archive_all for token in ("术后", "手术", "骨折手术", "切除术"))
    ):
        theme_kind = "surgery_recovery"
    elif med_tags or any(label in archive_conditions for label in ("糖尿病", "高血压", "心房颤动")):
        theme_kind = "chronic_medication"
    else:
        theme_kind = "general_recovery"

    theme_meta = {
        "oncology_adc": {
            "eyebrow": "治疗旅程",
            "badge": "ADC 治疗",
            "title": "ADC 治疗进行中",
            "summary": "更适合把输注后反应、体力变化和营养恢复单独拎出来看。",
            "stage_label": "当前阶段",
            "stage_value": "围绕本轮 ADC 治疗做恢复和日常管理",
            "gradient": "linear-gradient(135deg, #7c3aed 0%, #8b5cf6 55%, #c4b5fd 100%)",
            "accent": "#ede9fe",
            "icon": "💜",
            "art": "💉",
        },
        "oncology_chemo": {
            "eyebrow": "治疗旅程",
            "badge": "化疗主题",
            "title": "治疗后的恢复窗口",
            "summary": "把近期用药、食欲、活动和不适感受放在同一个治疗背景下看，会更贴近病人的真实体验。",
            "stage_label": "当前阶段",
            "stage_value": "围绕近期化疗 / 肿瘤治疗做恢复管理",
            "gradient": "linear-gradient(135deg, #7c3aed 0%, #a855f7 55%, #e9d5ff 100%)",
            "accent": "#f3e8ff",
            "icon": "🧬",
            "art": "🩸",
        },
        "surgery_recovery": {
            "eyebrow": "恢复阶段",
            "badge": "术后康复",
            "title": "术后恢复正在推进",
            "summary": "这类页面更适合把体力恢复、活动递进和日常用药放在一起呈现。",
            "stage_label": "当前阶段",
            "stage_value": "从术后保护逐步转向恢复体力和日常功能",
            "gradient": "linear-gradient(135deg, #0f766e 0%, #14b8a6 55%, #99f6e4 100%)",
            "accent": "#ccfbf1",
            "icon": "🩺",
            "art": "🦴",
        },
        "infection_recovery": {
            "eyebrow": "治疗主题",
            "badge": "住院后恢复",
            "title": "感染住院后的恢复管理",
            "summary": "这时不只看症状，也要把住院阶段的强化治疗、出院后的长期用药和恢复节奏串起来看。",
            "stage_label": "当前阶段",
            "stage_value": "从住院强化支持逐步转向居家维持",
            "gradient": "linear-gradient(135deg, #2563eb 0%, #4f46e5 55%, #bfdbfe 100%)",
            "accent": "#dbeafe",
            "icon": "🛡️",
            "art": "🏥",
        },
        "chronic_medication": {
            "eyebrow": "治疗主题",
            "badge": "长期管理",
            "title": "居家维持用药阶段",
            "summary": "把慢病、长期用药和每天最容易执行的步骤放在一个模块里，病人会更容易理解自己现在要做什么。",
            "stage_label": "当前阶段",
            "stage_value": "以长期用药、饮食和监测的稳定执行为主",
            "gradient": "linear-gradient(135deg, #0f766e 0%, #16a34a 55%, #bbf7d0 100%)",
            "accent": "#dcfce7",
            "icon": "📅",
            "art": "💊",
        },
        "general_recovery": {
            "eyebrow": "治疗主题",
            "badge": "当前重点",
            "title": "当前治疗与恢复重点",
            "summary": "把正在经历的治疗背景放在前面，后面的建议就不会显得像通用模板。",
            "stage_label": "当前阶段",
            "stage_value": "围绕当前治疗和恢复安排日常计划",
            "gradient": "linear-gradient(135deg, #475569 0%, #64748b 55%, #cbd5e1 100%)",
            "accent": "#e2e8f0",
            "icon": "✨",
            "art": "🧭",
        },
    }
    meta = theme_meta[theme_kind]

    medication_status = _localize_zh_text(str((current_items.get("medication") or {}).get("status_label") or "")).strip()
    appetite_status = _localize_zh_text(str((current_items.get("appetite") or {}).get("status_label") or "")).strip()
    monitoring_status = _localize_zh_text(str((current_items.get("monitoring") or {}).get("status_label") or "")).strip()
    recent_line = _pick_recent_treatment_line(memory, theme_kind)

    focus_points: list[str] = []
    if med_tags:
        focus_points.append(f"当前会反复涉及的用药包括：{'、'.join(med_tags[:4])}。")
    if medication_status:
        focus_points.append(f"本次回访里的用药执行状态为“{medication_status}”，适合把服药节奏继续稳住。")
    if appetite_status:
        focus_points.append(f"营养相关记录目前是“{appetite_status}”，治疗恢复期更需要把蛋白和主食节奏守住。")
    if monitoring_status:
        focus_points.append(f"监测状态目前是“{monitoring_status}”，越在治疗恢复阶段，越需要把家庭记录补齐。")
    if theme_kind == "infection_recovery":
        focus_points.insert(0, "住院阶段的重点更多在抗感染、循环/呼吸支持和代谢管理；回家后更看重稳定执行。")
    elif theme_kind in {"oncology_adc", "oncology_chemo"}:
        focus_points.insert(0, "这类治疗主题更适合突出输注后几天的食欲、体力、睡眠和感染风险，而不是只列通用建议。")
    elif theme_kind == "surgery_recovery":
        focus_points.insert(0, "术后主题更适合突出疼痛、活动递进和蛋白补充之间的关系。")
    elif theme_kind == "chronic_medication":
        focus_points.insert(0, "慢病长期管理更需要把药物、吃饭和监测放在同一个日常节奏里。")
    focus_points = focus_points[:3]

    objective_bits: list[str] = []
    if long_term_section:
        objective_bits.append(f"长期用药：{long_term_section[:120]}")
    if order_section:
        objective_bits.append(f"住院/治疗记录：{order_section[:120]}")
    if admission_section:
        objective_bits.append(f"本次事件背景：{admission_section[:120]}")
    evidence = objective_bits[:2]
    source = "objective"
    if recent_line:
        recent_evidence = recent_line
        if theme_kind == "infection_recovery":
            recent_evidence = "近期线索提示住院强化治疗后，后续已逐步过渡到居家维持用药与日常管理。"
        evidence.append(f"近期线索：{recent_evidence}（来自 memory.recent，仅作变化线索）")
        source = "objective_plus_recent"

    cycle_badge = _extract_treatment_cycle_badge(current_event_text, _memory_recent_text(memory))
    if not cycle_badge:
        fallback_badges = {
            "infection_recovery": "住院恢复期",
            "surgery_recovery": "恢复递进期",
            "chronic_medication": "长期维持期",
            "general_recovery": "当前恢复期",
        }
        cycle_badge = fallback_badges.get(theme_kind, "")

    education = _build_treatment_education(theme_kind, current_items, meta["title"], med_tags)

    return {
        "kind": theme_kind,
        "eyebrow": meta["eyebrow"],
        "badge": meta["badge"],
        "title": meta["title"],
        "summary": meta["summary"],
        "stage_label": meta["stage_label"],
        "stage_value": meta["stage_value"],
        "gradient": meta["gradient"],
        "accent": meta["accent"],
        "icon": meta["icon"],
        "art": meta["art"],
        "cycle_badge": cycle_badge,
        "medication_tags": med_tags,
        "focus_points": focus_points,
        "evidence": evidence,
        "source": source,
        "education": education,
    }


def _extract_payload_suggestion_texts(payload: dict) -> list[str]:
    suggestions = ((payload.get("adherence_analysis") or {}).get("suggestions")) or []
    texts: list[str] = []
    for item in suggestions:
        output = item.get("output_json") if isinstance(item, dict) else item
        text = _clean_recommendation_text(output.get("text") if isinstance(output, dict) else output or "")
        if text:
            texts.append(text)
    return texts


def _resource_location_label(payload: dict) -> str:
    location = payload.get("location") or {}
    loc = location.get("current") or {}
    for key in ("district", "city", "region", "name"):
        value = str(loc.get(key) or "").strip()
        if value:
            return value[:12]
    address = str(loc.get("address") or "").strip()
    if address:
        for sep in (",", "/", "|"):
            if sep in address:
                address = address.split(sep)[0].strip()
        return address[:12]
    return "按当前位置"


def _build_local_resource_items(payload: dict, so: dict) -> list[dict]:
    archive_conditions = _extract_archive_conditions(payload.get("memory") or {})
    current_items = _collect_current_adherence_items(payload, so)
    monitoring_bucket = _status_bucket((current_items.get("monitoring") or {}).get("status"))
    exercise_bucket = _status_bucket((current_items.get("exercise") or {}).get("status"))

    items: list[dict] = []
    has_chronic_metabolic_need = any(label in archive_conditions for label in ("糖尿病", "高血压", "冠心病"))
    items.append({
        "id": "hospital",
        "icon": "🏥",
        "icon_secondary": "🩺",
        "tone": "blue",
        "eyebrow": "身体不舒服时，先帮您把就近医疗点找出来",
        "accent": "门诊与医院支持",
        "avatars": ["👨‍⚕️", "🏥"],
        "availability": "可导航",
        "title": "医院 / 门诊",
        "copy": "如果最近需要复诊、开药、抽血复查，或者身体有点不舒服，我们可以先从附近医院和门诊慢慢看起。",
        "badge": "医疗支持",
        "subbadge": "优先就近",
        "meta_time": "适合复诊、复查或突然不适时优先查看",
        "meta_place": "综合医院、专科门诊、便民门诊",
        "meta_distance": "建议先看 20 分钟内可到达的点",
        "query": "附近医院 门诊",
        "search_keyword": "医院",
        "action": "查看附近医院",
        "examples": ["综合医院门诊", "专科诊所", "急诊 / 发热门诊"],
        "map_copy": "我先陪您看看附近医院和门诊，这样复诊、开药，或者突然不舒服时都会更安心一些。",
        "results_title": "附近可去的医院和门诊",
        "results_copy": "这里会优先放离您比较近、现在去起来更省力的医院和门诊点位。",
    })
    items.append({
        "id": "grocery",
        "icon": "🥗",
        "icon_secondary": "🥛" if has_chronic_metabolic_need else "🥬",
        "tone": "peach",
        "eyebrow": "想把营养补上来，可以先从这些地方看看",
        "accent": "营养师支持",
        "avatars": ["👩‍⚕️", "🧑‍🍳"],
        "availability": "可预约",
        "title": "营养门诊 / 生鲜采购",
        "copy": (
            "如果您正想把饮食、稳糖和控盐这些问题理一理，这类营养支持通常会更有帮助，尤其适合有糖尿病或高血压背景的人。"
            if has_chronic_metabolic_need
            else "如果最近蛋白、正餐或胃口恢复得还不太稳，我们可以一起看看营养门诊和附近买食材更方便的地方。"
        ),
        "badge": "饮食支持",
        "subbadge": "轻负担",
        "meta_time": "建议白天安排，30-45 分钟更轻松",
        "meta_place": "营养门诊、社区健康中心、生鲜超市",
        "meta_distance": "优先筛选离家 3 公里内",
        "query": "营养门诊 生鲜超市 社区健康中心",
        "search_keyword": "超市",
        "action": "查看采购点",
        "examples": ["医院营养门诊", "社区健康中心", "生鲜超市 / 商店"],
        "map_copy": "我先把附近买食材更方便的点放在这里，也方便您把营养补给一点点落实下来。",
        "results_title": "附近可去的营养门诊和采购点",
        "results_copy": "这里会放营养门诊、生鲜超市和更方便采购食材的地方，方便您挑一个最顺手的。",
    })
    if monitoring_bucket == "needs_attention":
        items.append({
            "id": "pharmacy",
            "icon": "🩺",
            "icon_secondary": "💊",
            "tone": "blue",
            "eyebrow": "顺路补一次，也是在帮自己稳住节奏",
            "accent": "药师支持",
            "avatars": ["👨‍⚕️", "💊"],
            "availability": "推荐",
            "title": "社区药房 / 血压监测点",
            "copy": "如果这几天监测有点容易漏掉，也没关系，我们先找一个顺路、容易到的地方，把这个习惯慢慢补回来。",
            "badge": "监测支持",
            "subbadge": "推荐",
            "meta_time": "适合办事顺路时补测，不用单独跑一趟",
            "meta_place": "社区药房、门诊大厅或便民监测点",
            "meta_distance": "建议先看 15 分钟步行范围",
            "query": "社区药房 血压测量",
            "search_keyword": "药房",
            "action": "找最近的点",
            "examples": ["社区药房", "便民监测点", "慢病续方点"],
            "map_copy": "如果最近监测或取药有点跟不上，我先帮您看看顺路的药房和监测点，做起来会轻松一些。",
            "results_title": "附近可去的药房和监测点",
            "results_copy": "这里会优先放顺路、好到达的药房和便民监测点，方便您选一个最不费力的。",
        })
    else:
        items.append({
            "id": "pharmacy",
            "icon": "💊",
            "icon_secondary": "🩺",
            "tone": "blue",
            "eyebrow": "常用药和监测点，我先帮您放在一起看",
            "accent": "药房支持",
            "avatars": ["💊", "👨‍⚕️"],
            "availability": "常用",
            "title": "药房 / 监测点",
            "copy": "平时想补药、测血压，或者找一个顺路能补测的地方，都可以先从附近药房和便民点慢慢挑。",
            "badge": "监测支持",
            "subbadge": "顺路就行",
            "meta_time": "适合顺路补药或补测",
            "meta_place": "社区药房、门诊大厅或监测便民点",
            "meta_distance": "建议先看 15 分钟步行范围",
            "query": "社区药房 血压测量",
            "search_keyword": "药房",
            "action": "找最近的点",
            "examples": ["社区药房", "便民监测点", "慢病续方点"],
            "map_copy": "我先把附近药房和监测点放在这里，补药、复测或者顺路打卡都会更方便一些。",
            "results_title": "附近可去的药房和监测点",
            "results_copy": "这里会优先放顺路、好到达的药房和便民监测点，方便您选一个最不费力的。",
        })
    items.append({
        "id": "activity",
        "icon": "🧘",
        "icon_secondary": "🌿",
        "tone": "mint",
        "eyebrow": "慢慢来就很好，我们先找轻一点的活动点",
        "accent": "低强度活动",
        "avatars": ["🧑", "🌿"],
        "availability": "低强度",
        "title": "轻柔活动课程 / 康复散步点",
        "copy": (
            "把活动放在离家近、压力小一点的地方，通常会更容易坚持，也更适合恢复期慢慢把活动量拉回来。"
            if exercise_bucket in {"needs_attention", "mixed"} or "术后康复" in archive_conditions
            else "如果您想把活动继续稳住，我们可以先从这些低强度课程或轻松步道开始，不用一下子给自己太大压力。"
        ),
        "badge": "低强度",
        "subbadge": "更容易坚持",
        "meta_time": "适合饭后或下午安排 10-20 分钟",
        "meta_place": "公园步道、社区活动室或康复课程",
        "meta_distance": "先从离家近、容易往返的点开始",
        "query": "附近公园 步道 轻柔活动",
        "search_keyword": "公园",
        "action": "查看课程",
        "examples": ["公园步道", "社区活动室", "康复课程点"],
        "map_copy": "我先把附近更轻松、压力更小的活动点放在这里，方便您一点点把节奏找回来。",
        "results_title": "附近适合去的活动和康复点",
        "results_copy": "这里会放公园步道、社区活动室和低强度康复活动点，您可以先挑一个最容易开始的。",
    })
    items.append({
        "id": "support",
        "icon": "🤝",
        "icon_secondary": "💬",
        "tone": "lavender",
        "eyebrow": "如果有人一起走这段路，心里通常会轻松一点",
        "accent": "病友陪伴",
        "avatars": ["🧑‍🦳", "🧑"],
        "availability": "可线上参加",
        "title": "病友支持小组 / 健康讲座",
        "copy": "如果您想听听别人是怎么一步步坚持饮食和日常管理的，也可以看看病友支持小组或社区讲座，不用一个人扛着。",
        "badge": "陪伴支持",
        "subbadge": "线上线下都可",
        "meta_time": "适合每周参加 1 次，压力不会太大",
        "meta_place": "医院患者教育、社区讲座或线上支持群",
        "meta_distance": "也可以先看线上活动，再决定是否线下参加",
        "query": "病友支持小组 健康讲座",
        "search_keyword": "健康讲座",
        "action": "报名参加",
        "examples": ["病友支持小组", "患者教育讲座", "线上支持群"],
        "map_copy": "如果您想听听别人的经验、给自己多一点陪伴，我也把附近讲座和支持小组放在这里了。",
        "results_title": "附近可参加的讲座和支持小组",
        "results_copy": "这里会放线下讲座和病友小组，您可以慢慢看看，哪一种更适合现在的自己。",
    })
    return items[:5]


def _extract_food_keywords_from_suggestions(texts: list[str]) -> list[str]:
    mappings = [
        ("鱼", "鱼"),
        ("豆腐", "豆腐"),
        ("鸡蛋", "鸡蛋"),
        ("酸奶", "无糖酸奶"),
        ("燕麦", "燕麦"),
        ("牛奶", "牛奶"),
    ]
    found: list[str] = []
    for text in texts:
        if any(token in text for token in ("提醒", "监测", "服用", "血压", "手表", "药")):
            continue
        for token, label in mappings:
            if token in text and label not in found:
                found.append(label)
    return found


def _build_shopping_groups(payload: dict, so: dict) -> list[dict]:
    meal_plan = so.get("weekly_meal_plan") or []
    archive_conditions = _extract_archive_conditions(payload.get("memory") or {})
    current_items = _collect_current_adherence_items(payload, so)
    suggestion_foods = _extract_food_keywords_from_suggestions(_extract_payload_suggestion_texts(payload))
    diet_text = _localize_zh_text(str((current_items.get("appetite") or {}).get("text") or ""))
    token_map = [
        (("oatmeal", "燕麦"), ["燕麦", "香蕉"]),
        (("egg", "鸡蛋"), ["鸡蛋"]),
        (("broth", "soup", "汤"), ["鸡胸肉", "番茄", "西葫芦"]),
        (("cracker", "全麦面包", "whole wheat"), ["全麦面包"]),
        (("salmon", "三文鱼"), ["三文鱼"]),
        (("broccoli", "西兰花"), ["西兰花"]),
        (("brown rice", "糙米"), ["糙米"]),
        (("yogurt", "酸奶"), ["无糖酸奶"]),
        (("berries", "莓"), ["蓝莓"]),
        (("almond", "坚果"), ["即食坚果"]),
        (("lentil", "扁豆"), ["扁豆"]),
        (("salad", "生菜", "沙拉"), ["生菜", "黄瓜"]),
        (("olive oil", "橄榄油"), ["橄榄油"]),
        (("chicken breast", "鸡胸"), ["鸡胸肉"]),
        (("sweet potato", "红薯"), ["红薯"]),
        (("spinach", "菠菜"), ["菠菜"]),
        (("tofu", "豆腐"), ["豆腐"]),
        (("soy milk", "豆浆"), ["无糖豆浆"]),
        (("milk", "牛奶"), ["牛奶"]),
        (("corn", "玉米"), ["玉米"]),
        (("avocado", "牛油果"), ["牛油果"]),
        (("tuna", "金枪鱼"), ["金枪鱼"]),
        (("green beans", "四季豆"), ["四季豆"]),
    ]

    week_ingredients: list[str] = []
    if isinstance(meal_plan, list):
        for day in meal_plan:
            if not isinstance(day, dict):
                continue
            for meal_key in ("breakfast", "lunch", "dinner", "snacks", "snack"):
                entries = day.get(meal_key) or []
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    name = _localize_zh_text(str(entry.get("name") or "")).lower()
                    if not name:
                        continue
                    for keywords, ingredients in token_map:
                        if any(keyword in name for keyword in keywords):
                            week_ingredients.extend(ingredients)

    fallback_core = [item for item in ["鸡蛋", "豆腐", "鱼", "无糖酸奶"] if item in suggestion_foods or item in {"鸡蛋", "豆腐"}]
    if "半饱" in diet_text or "吃不下" in diet_text:
        fallback_core = ["鸡蛋", "嫩豆腐", "无糖酸奶", "鱼"]
    if not week_ingredients:
        week_ingredients.extend(fallback_core or ["鸡蛋", "豆腐", "鱼", "无糖酸奶"])
        week_ingredients.extend(["番茄", "黄瓜", "西兰花", "菠菜"])
        if "糖尿病" in archive_conditions:
            week_ingredients.extend(["燕麦", "糙米", "全麦面包", "玉米"])
        week_ingredients.extend(["即食坚果", "牛奶", "香蕉"])

    unique_week_items = list(dict.fromkeys(item for item in week_ingredients if item))
    fresh_candidates = ["鸡蛋", "嫩豆腐", "豆腐", "三文鱼", "鱼", "鸡胸肉", "无糖酸奶", "牛奶", "蓝莓", "香蕉", "番茄", "黄瓜", "西兰花", "菠菜", "生菜", "西葫芦", "四季豆"]
    pantry_candidates = ["燕麦", "糙米", "全麦面包", "扁豆", "玉米", "即食坚果", "橄榄油", "无糖豆浆", "红薯"]

    fresh_items = [item for item in fresh_candidates if item in unique_week_items]
    pantry_items = [item for item in pantry_candidates if item in unique_week_items]

    if "高血压" in archive_conditions and "芹菜" not in fresh_items:
        fresh_items.append("芹菜")
    if "糖尿病" in archive_conditions:
        for item in ("燕麦", "糙米"):
            if item not in pantry_items:
                pantry_items.append(item)

    substitute_items: list[str] = []
    if any(item in unique_week_items for item in ("三文鱼", "鱼", "金枪鱼")):
        substitute_items.append("鱼类不方便时可改鸡胸肉 / 豆腐")
    if any(item in unique_week_items for item in ("无糖酸奶", "牛奶", "无糖豆浆")):
        substitute_items.append("奶类吃不下时可改无糖豆浆 / 温牛奶")
    if any(item in unique_week_items for item in ("糙米", "全麦面包", "燕麦", "玉米", "红薯")):
        substitute_items.append("主食可在燕麦 / 糙米 / 玉米 / 红薯之间轮换")
    if any(item in unique_week_items for item in ("西兰花", "菠菜", "生菜", "四季豆", "黄瓜")):
        substitute_items.append("绿叶菜买不到时可在菠菜 / 西兰花 / 四季豆之间替换")
    if not substitute_items:
        substitute_items.append("如果当天胃口不好，先保留蛋白质和一份主食，蔬菜可换成更容易入口的种类。")

    fresh_items = fresh_items[:8] or ["鸡蛋", "豆腐", "无糖酸奶", "西兰花", "菠菜", "香蕉"]
    pantry_items = pantry_items[:8] or ["燕麦", "糙米", "全麦面包", "即食坚果", "橄榄油"]

    return [
        {
            "title": "先买 3 天鲜食",
            "copy": "围绕这周餐单里最容易变质、最影响当天吃不吃得下的食材先备 3 天量，更适合盒马这类即时补货。",
            "items": fresh_items,
            "primary_label": "盒马补这组",
            "secondary_label": "复制鲜食清单",
        },
        {
            "title": "一次备 7 天基础",
            "copy": "这些是本周三餐里反复会用到的基础食材，适合一次性在京东先下单备着。",
            "items": pantry_items,
            "primary_label": "京东买基础",
            "secondary_label": "复制基础清单",
        },
        {
            "title": "本周可替代食材",
            "copy": "不用按 21 餐死板采购。如果某样买不到、吃不下或当天状态不好，可以优先这样替换。",
            "items": substitute_items[:4],
            "primary_label": "",
            "secondary_label": "",
            "actions": False,
        },
    ]


def _jd_search_url(items: list[str]) -> str:
    query = " ".join(item for item in items if item)
    return _JD_SEARCH_BASE + quote(query)


def _fallback_meal_item(name: str, icon: str, reason: str) -> dict:
    return {
        "name": name,
        "icon": icon,
        "adc_reason": reason,
        "benefit": reason,
    }


def _build_fallback_weekly_meal_plan(payload: dict, so: dict) -> list[dict]:
    archive_conditions = _extract_archive_conditions(payload.get("memory") or {})
    current_items = _collect_current_adherence_items(payload, so)
    appetite_text = _localize_zh_text(str((current_items.get("appetite") or {}).get("text") or ""))
    light_mode = any(token in appetite_text for token in ("半饱", "吃不下", "胃口", "没什么食欲"))
    diabetes = "糖尿病" in archive_conditions
    hypertension = "高血压" in archive_conditions

    breakfast_pool = [
        (
            _fallback_meal_item("燕麦鸡蛋羹", "🥣", "容易入口，也能补一点蛋白质，适合需要稳糖和恢复体力的时候。"),
            _fallback_meal_item("无糖酸奶", "🥛", "加餐负担小，适合胃口一般时先补一点。"),
        ),
        (
            _fallback_meal_item("全麦面包配水煮蛋", "🍞", "主食更稳一点，鸡蛋能补蛋白，适合糖尿病和恢复期。"),
            _fallback_meal_item("温牛奶", "🥛", "更容易接受，也适合作为早晨的小补充。"),
        ),
        (
            _fallback_meal_item("玉米和鸡蛋", "🌽", "主食量更容易控制，也能帮助上午保持体力。"),
            _fallback_meal_item("无糖豆浆", "🥛", "清淡、顺口，适合早餐补充植物蛋白。"),
        ),
    ]
    lunch_pool = [
        (
            _fallback_meal_item("清蒸鱼", "🐟", "优先补充蛋白质，也比重油做法更适合控盐。"),
            _fallback_meal_item("西兰花", "🥦", "清淡、纤维足，适合稳糖和控制整体油盐。"),
            _fallback_meal_item("糙米饭", "🍚", "比精白米更适合控制餐后波动。"),
        ),
        (
            _fallback_meal_item("番茄豆腐", "🍅", "软一点、好入口，也能补充蛋白和蔬菜。"),
            _fallback_meal_item("黄瓜木耳", "🥗", "做法简单，适合清淡饮食。"),
            _fallback_meal_item("玉米半根", "🌽", "主食量更容易控制。"),
        ),
        (
            _fallback_meal_item("鸡胸肉丝炒芹菜", "🍗", "蛋白质足，也适合高血压背景下控制盐分。"),
            _fallback_meal_item("清炒菠菜", "🥬", "补充蔬菜，做法也容易清淡。"),
            _fallback_meal_item("燕麦饭", "🍚", "更适合做成稳一点的主食搭配。"),
        ),
    ]
    dinner_pool = [
        (
            _fallback_meal_item("嫩豆腐蒸蛋", "🍲", "晚上尽量选软一点、轻一点，也方便补蛋白。"),
            _fallback_meal_item("清炒西葫芦", "🥒", "负担小，适合晚餐别太油。"),
        ),
        (
            _fallback_meal_item("清炖鱼片", "🐟", "恢复期更适合清淡烹调，也有利于补充优质蛋白。"),
            _fallback_meal_item("番茄菜花", "🍅", "容易搭配主菜，也方便做得清淡。"),
        ),
        (
            _fallback_meal_item("鸡蛋豆腐汤", "🍜", "如果晚饭胃口一般，可以先从好入口的蛋白汤类开始。"),
            _fallback_meal_item("凉拌黄瓜", "🥒", "清爽、准备简单，也适合控制盐油。"),
        ),
    ]

    if light_mode:
        dinner_pool = [
            (
                _fallback_meal_item("鸡蛋羹", "🍮", "胃口一般时先吃得下更重要，鸡蛋羹更容易入口。"),
                _fallback_meal_item("嫩豆腐", "🧈", "软一些、负担小，也能补一点蛋白。"),
            ),
            (
                _fallback_meal_item("鱼片蔬菜汤", "🍲", "汤类更容易接受，也能同时补充蛋白和水分。"),
                _fallback_meal_item("番茄", "🍅", "酸甜更顺口一点。"),
            ),
            (
                _fallback_meal_item("无糖酸奶", "🥛", "如果正餐吃不下，可以先从加餐补一点。"),
                _fallback_meal_item("香蕉半根", "🍌", "先补点能量，比完全不吃更好。"),
            ),
        ]

    days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    plans: list[dict] = []
    for idx, day in enumerate(days):
        breakfast = list(breakfast_pool[idx % len(breakfast_pool)])
        lunch = list(lunch_pool[idx % len(lunch_pool)])
        dinner = list(dinner_pool[idx % len(dinner_pool)])
        if hypertension:
            lunch.append(_fallback_meal_item("清炒芹菜", "🥬", "高血压背景下，尽量把菜做清淡一点、少盐一点。"))
        if diabetes and idx % 2 == 0:
            breakfast.append(_fallback_meal_item("坚果小把", "🥜", "加餐量少一点，更适合作为稳糖时的小补充。"))
        plans.append({
            "day": day,
            "breakfast": breakfast,
            "lunch": lunch,
            "dinner": dinner,
        })
    return plans


def _ensure_full_weekly_meal_plan(payload: dict, so: dict) -> list[dict]:
    raw_plan = so.get("weekly_meal_plan") or []
    fallback = _build_fallback_weekly_meal_plan(payload, so)
    if not isinstance(raw_plan, list) or not raw_plan:
        return fallback

    normalized: list[dict] = []
    for idx in range(7):
        source = raw_plan[idx] if idx < len(raw_plan) and isinstance(raw_plan[idx], dict) else {}
        fallback_day = fallback[idx % len(fallback)] if fallback else {}
        normalized.append({
            "day": str(fallback_day.get("day") or f"第{idx + 1}天"),
            "breakfast": source.get("breakfast") if isinstance(source.get("breakfast"), list) and source.get("breakfast") else list(fallback_day.get("breakfast") or []),
            "lunch": source.get("lunch") if isinstance(source.get("lunch"), list) and source.get("lunch") else list(fallback_day.get("lunch") or []),
            "dinner": source.get("dinner") if isinstance(source.get("dinner"), list) and source.get("dinner") else list(fallback_day.get("dinner") or []),
        })
    return normalized


def _build_fallback_nutrition_priorities(payload: dict, so: dict) -> list[dict]:
    archive_conditions = _extract_archive_conditions(payload.get("memory") or {})
    current_items = _collect_current_adherence_items(payload, so)
    appetite_text = _localize_zh_text(str((current_items.get("appetite") or {}).get("text") or ""))
    priorities = [
        {
            "title": "先把蛋白质补上",
            "action": "今天优先准备鸡蛋、豆腐、鱼、无糖酸奶这类更容易吃进去的蛋白质。",
            "reason": "恢复体力、减少疲劳时，蛋白质通常比花样更多更重要。",
            "category": "protein",
            "icon": "🥚",
        },
        {
            "title": "主食先求稳一点",
            "action": "主食可以优先选燕麦、糙米、玉米、全麦面包，先把量控制稳。",
            "reason": "如果有糖尿病或血糖波动，这类主食更适合日常管理。",
            "category": "low_oil",
            "icon": "🌾",
        },
        {
            "title": "做法尽量清淡",
            "action": "先用蒸、煮、炖，少油少盐，比复杂菜式更容易长期坚持。",
            "reason": "有高血压背景时，清淡做法更适合作为基础策略。",
            "category": "low_salt",
            "icon": "🥬",
        },
    ]
    if any(token in appetite_text for token in ("半饱", "吃不下", "胃口", "没什么食欲")):
        priorities.insert(0, {
            "title": "胃口一般时先吃得下",
            "action": "今天不要求吃很多，先从鸡蛋羹、嫩豆腐、酸奶、汤类这种更顺口的开始。",
            "reason": "完全吃不下时，先保证能入口的小份补充，比硬撑着吃复杂菜更现实。",
            "category": "hydration",
            "icon": "🍲",
        })
    if "糖尿病" not in archive_conditions:
        priorities = [item for item in priorities if item.get("title") != "主食先求稳一点"] + [{
            "title": "蔬菜先备够",
            "action": "番茄、黄瓜、西兰花这类容易做的蔬菜，可以多备一点。",
            "reason": "比起追求复杂搭配，先把蔬菜吃进去更重要。",
            "category": "protein",
            "icon": "🥗",
        }]
    return priorities[:4]


def _build_fallback_nutrition_advice(payload: dict, so: dict) -> str:
    archive_conditions = _extract_archive_conditions(payload.get("memory") or {})
    current_items = _collect_current_adherence_items(payload, so)
    appetite_text = _localize_zh_text(str((current_items.get("appetite") or {}).get("text") or ""))
    parts = []
    if any(token in appetite_text for token in ("半饱", "吃不下", "胃口", "没什么食欲")):
        parts.append("这几天饮食上先不用追求吃很多，先选更容易入口、能补到蛋白质的小份食物。")
    if "糖尿病" in archive_conditions:
        parts.append("主食更建议分散到三餐里，优先选燕麦、糙米、玉米、全麦面包这类更稳一点的搭配。")
    if "高血压" in archive_conditions:
        parts.append("做法尽量以蒸、煮、炖为主，先把盐和重口味收一收，会比额外追求补品更实用。")
    if not parts:
        parts.append("这周饮食上先抓住三件事：补蛋白、做清淡、主食别忽多忽少。")
    return "".join(parts)


def _extract_recent_clues(memory: dict) -> dict[str, str]:
    text = str(((memory.get("recent") or {}).get("adherence")) or "").strip()
    if not text:
        return {}

    category_keywords = {
        "medication": ("用药", "服药", "药", "胰岛素", "华法林", "降压药"),
        "appetite": ("饮食", "食欲", "进食", "营养", "主食", "清淡", "控盐", "拉面", "汉堡"),
        "exercise": ("运动", "步行", "跑步", "活动", "步数", "卧床", "散步"),
        "monitoring": ("血压", "血氧", "心率", "监测", "测量", "记录"),
    }

    clues: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("-"):
            continue
        for category, keywords in category_keywords.items():
            if category in clues:
                continue
            if any(keyword in line for keyword in keywords):
                summary = _summarize_recent_clue(line, category)
                if summary:
                    clues[category] = summary
    return clues


def _collect_current_adherence_items(payload: dict, so: dict) -> dict[str, dict]:
    category_map = {
        "medication": "medication",
        "diet": "appetite",
        "appetite": "appetite",
        "exercise": "exercise",
        "activity": "exercise",
        "monitoring": "monitoring",
    }
    current: dict[str, dict] = {}
    statuses = ((payload.get("adherence_analysis") or {}).get("statuses")) or []
    if isinstance(statuses, list):
        for item in statuses:
            if not isinstance(item, dict):
                continue
            context = item.get("context") or {}
            category = category_map.get(str(context.get("category") or "").strip().lower())
            if not category:
                continue
            output = item.get("output_json")
            text = str(output.get("text") if isinstance(output, dict) else output or "").strip()
            created_at = item.get("created_at")
            current[category] = {
                "status": context.get("overall_status") or "",
                "status_label": _adherence_status_label(context.get("overall_status")),
                "text": text,
                "date": _format_short_date(created_at),
            }

    adh = so.get("adherence_analysis") or {}
    for category in ("medication", "appetite", "exercise", "monitoring"):
        dim = adh.get(category)
        if not isinstance(dim, dict):
            continue
        entry = current.setdefault(category, {})
        entry.setdefault("status", dim.get("status") or "")
        entry.setdefault("status_label", _localize_zh_text(str(dim.get("status") or "")))
        detail_text = ""
        for key in ("issues", "adjustments", "cause_if_known", "suggestions", "barriers", "plan", "gaps"):
            value = str(dim.get(key) or "").strip()
            if value:
                detail_text = value
                break
        entry.setdefault("text", detail_text)
    return current


def _build_patient_profile(payload: dict, so: dict) -> dict:
    memory = payload.get("memory") or {}
    archive_text = _memory_archive_text(memory)
    recent_text = _memory_recent_text(memory)
    age = _extract_patient_age(payload, memory)

    reasons: list[str] = []
    communication_mode = "standard"
    tone_style = "direct_practical"
    context_key = "stable_routine"

    keyword_text = f"{archive_text}\n{recent_text}"
    has_cognitive_burden = any(keyword in keyword_text for keyword in _SIMPLIFIED_COMMUNICATION_KEYWORDS)
    has_high_burden = any(keyword in keyword_text for keyword in _HIGH_BURDEN_KEYWORDS)
    has_surgery_context = any(keyword in archive_text for keyword in ("术后", "手术", "骨折"))
    self_management_keywords = (
        "规律监测", "连续监测", "记录血压", "晨起血压", "每日步行", "跑步", "严格执行",
        "控盐", "全麦", "分餐", "按时", "戴手表", "测量", "居家维持",
    )
    self_management_score = sum(1 for keyword in self_management_keywords if keyword in keyword_text)

    if age is not None:
        if age >= 75:
            reasons.append(f"年龄约 {age} 岁，优先用更短句、更少步骤的表达。")
        elif age >= 65:
            reasons.append(f"年龄约 {age} 岁，表达上更适合先给清楚步骤，再补必要说明。")
        else:
            reasons.append(f"年龄约 {age} 岁，可以保留更多自我管理细节。")
    if has_cognitive_burden:
        reasons.append("背景信息里出现了认知或记忆负担线索，适合减少复杂表述。")
    if has_high_burden:
        reasons.append("近期疾病负担较重，建议把信息收束到最关键的 2 到 3 点。")
    if self_management_score >= 2:
        reasons.append("近期记录里能看到连续记录或主动管理线索，可以保留更多原因解释和细节。")

    if has_cognitive_burden or (age is not None and age >= 75):
        communication_mode = "simplified"
        tone_style = "gentle_patient"
        context_key = "cognitive_decline" if has_cognitive_burden else "stable_routine"
    elif has_high_burden or has_surgery_context or (age is not None and age >= 65):
        communication_mode = "standard"
        tone_style = "warm_encouraging"
        if has_high_burden:
            context_key = "feeling_unwell"
        elif has_surgery_context:
            context_key = "post_surgery_recovering"
    elif (age is not None and age <= 60 and not has_high_burden and self_management_score >= 2) or self_management_score >= 3:
        communication_mode = "detailed"
        tone_style = "direct_practical"
        context_key = "stable_routine"

    if communication_mode == "simplified":
        summary = "这份报告会尽量用短句、少术语，先说最重要的事情。"
        persona_label = "简明陪伴版"
    elif communication_mode == "standard":
        summary = "这份报告会先告诉患者现在该做什么，再补一层必要原因，避免信息太多。"
        persona_label = "标准行动版"
    else:
        summary = "这份报告会保留更多原因说明，方便患者理解为什么要这样做。"
        persona_label = "详细管理版"

    if not reasons:
        reasons.append("当前可用背景信息有限，先按常规慢病管理的标准行动版表达。")

    return {
        "age": age,
        "communication_mode": communication_mode,
        "persona_label": persona_label,
        "summary": summary,
        "reasons": reasons[:3],
        "tone_style": tone_style,
        "context_key": context_key,
    }


def _augment_structured_output(so: dict, payload: dict) -> dict:
    profile = so.get("patient_profile")
    if not isinstance(profile, dict) or not profile:
        profile = _build_patient_profile(payload, so)
        so["patient_profile"] = profile

    conditions = so.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        so["conditions"] = _extract_archive_conditions(payload.get("memory") or {})

    treatment_theme = so.get("treatment_theme")
    if not isinstance(treatment_theme, dict) or not treatment_theme:
        treatment_theme = _build_treatment_theme(payload, so)
        if treatment_theme:
            so["treatment_theme"] = treatment_theme

    current_items = _collect_current_adherence_items(payload, so)
    recent_clues = _extract_recent_clues(payload.get("memory") or {})
    highlights = so.get("longitudinal_highlights")
    if not isinstance(highlights, list) or not highlights:
        highlights = []
        category_labels = {
            "medication": "用药",
            "appetite": "饮食与营养",
            "exercise": "运动与活动",
            "monitoring": "健康监测",
        }
        for category in ("medication", "appetite", "exercise", "monitoring"):
            item = current_items.get(category) or {}
            if not item:
                continue
            bucket = _status_bucket(item.get("status") or item.get("status_label"))
            title, closing = _status_category_text(bucket)
            current_fact = _localize_zh_text(str(item.get("text") or "").strip())
            recent_fact = recent_clues.get(category) or ""
            summary_parts = []
            if current_fact:
                summary_parts.append(f"这次回访里，{current_fact}")
            else:
                summary_parts.append(f"这次回访里，{category_labels[category]}记录为{_localize_zh_text(str(item.get('status_label') or '待观察'))}。")
            summary_parts.append(closing)
            evidence_bits = []
            if item.get("date"):
                evidence_bits.append(f"本次记录日期：{item['date']}")
            if current_fact:
                evidence_bits.append(f"本次事实：{current_fact}")
            if recent_fact:
                evidence_bits.append("近期线索：来自 memory.recent 的候选行为变化")
            highlights.append(
                {
                    "category": category,
                    "title": f"{category_labels[category]}：{title}",
                    "summary": " ".join(summary_parts),
                    "evidence": "；".join(evidence_bits),
                    "source": "objective_plus_recent" if recent_fact else "objective",
                }
            )
        if highlights:
            so["longitudinal_highlights"] = highlights[:4]
    if isinstance(so.get("longitudinal_highlights"), list):
        enriched_highlights = []
        for item in (so.get("longitudinal_highlights") or [])[:4]:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "")
            current_item = current_items.get(category) or {}
            recent_fact = recent_clues.get(category) or ""
            current_bucket = _status_bucket(current_item.get("status") or current_item.get("status_label"))
            recent_bucket = _recent_bucket_from_clue(recent_fact)
            comparison_note, comparison_tone = _build_longitudinal_comparison_note(current_bucket, recent_bucket)
            next_item = dict(item)
            next_item.setdefault("comparison_note", comparison_note)
            next_item.setdefault("comparison_tone", comparison_tone)
            enriched_highlights.append(next_item)
        if enriched_highlights:
            so["longitudinal_highlights"] = enriched_highlights

    if not isinstance(so.get("recent_adherence_scores"), list) or not so.get("recent_adherence_scores"):
        score_labels = {
            "medication": "吃药坚持度",
            "appetite": "营养坚持度",
            "exercise": "运动坚持度",
        }
        recent_scores = []
        for category in ("medication", "appetite", "exercise"):
            item = current_items.get(category) or {}
            current_bucket = _status_bucket(item.get("status") or item.get("status_label"))
            recent_fact = recent_clues.get(category) or ""
            recent_bucket = _recent_bucket_from_clue(recent_fact)
            score = _recent_dimension_score(current_bucket, recent_bucket)
            previous_score = _bucket_reference_score(recent_bucket)
            target_score = _next_target_score(score)
            delta = score - previous_score
            delta_label, delta_color = _score_delta_meta(delta)
            headline, next_step = _build_recent_score_copy(category, current_bucket, recent_bucket)
            comparison_note, comparison_tone = _build_longitudinal_comparison_note(current_bucket, recent_bucket)
            recent_scores.append(
                {
                    "category": category,
                    "label": score_labels[category],
                    "score": score,
                    "band": _recent_score_band(score),
                    "status_label": _localize_zh_text(str(item.get("status_label") or "待观察")),
                    "headline": headline,
                    "next_step": next_step,
                    "tone": "good" if score >= 84 else "mixed" if score >= 70 else "alert",
                    "previous_score": previous_score,
                    "target_score": target_score,
                    "delta": delta,
                    "delta_label": delta_label,
                    "delta_color": delta_color,
                    "comparison_note": comparison_note if recent_fact else "",
                    "comparison_tone": comparison_tone if recent_fact else "neutral",
                }
            )
        so["recent_adherence_scores"] = recent_scores

    reasoning = _localize_zh_text(str(so.get("reasoning") or "")).strip()
    if _RECENT_GUARDRAIL_NOTE not in reasoning and recent_clues:
        so["reasoning"] = (reasoning + " " + _RECENT_GUARDRAIL_NOTE).strip()

    guardrail = _localize_zh_text(str(so.get("guardrail") or "")).strip()
    if _RECENT_GUARDRAIL_NOTE not in guardrail:
        so["guardrail"] = (guardrail + " " + _RECENT_GUARDRAIL_NOTE).strip()

    return profile


def _render_vitals(summary: dict) -> str:
    if not summary:
        return ""

    metrics = [
        ("blood_pressure", "血压", "🩺", "90-120 / 60-80 mmHg"),
        ("heart_rate", "心率", "🫀", "60-100 bpm"),
        ("blood_oxygen", "血氧", "🫁", "95-100%"),
        ("blood_glucose", "血糖", "🧪", "3.9-7.8 mmol/L"),
        ("steps_today", "今日步数", "👟", "建议 6000-10000 步/日"),
    ]

    cards = []
    for key, label, icon, normal_range in metrics:
        raw_value = summary.get(key)
        if raw_value in (None, ""):
            continue

        status = "good"
        note = "您的数据整体平稳，继续保持当前的健康习惯。"
        numbers = _extract_numbers(raw_value)

        if key == "blood_pressure" and len(numbers) >= 2:
            systolic, diastolic = numbers[0], numbers[1]
            if systolic >= 140 or diastolic >= 90:
                status = "alert"
                note = "您的血压偏高，建议减少盐分摄入、规律监测，并按医嘱复诊。"
            elif systolic > 120 or diastolic > 80:
                status = "caution"
                note = "您的血压略高，近期注意休息、少盐饮食，并持续观察。"
            elif systolic < 90 or diastolic < 60:
                status = "caution"
                note = "您的血压偏低，如伴头晕乏力，请及时联系医生。"
            else:
                note = "您的血压在正常范围内，非常健康，继续保持。"
        elif key == "heart_rate" and numbers:
            value = numbers[0]
            if value < 50 or value > 110:
                status = "alert"
                note = "您的心率波动较明显，若伴胸闷、心悸或不适，请尽快联系医生。"
            elif value < 60 or value > 100:
                status = "caution"
                note = "您的心率略偏离常见范围，建议结合休息、情绪和近期活动继续观察。"
            else:
                note = "您的心率处于常见健康范围，当前状态不错。"
        elif key == "blood_oxygen" and numbers:
            value = numbers[0]
            if value < 93:
                status = "alert"
                note = "您的血氧偏低，如有气短、胸闷或乏力，请尽快联系医生。"
            elif value < 95:
                status = "caution"
                note = "您的血氧略低，建议减少剧烈活动并持续监测。"
            else:
                note = "您的血氧在正常范围内，呼吸状态较稳定。"
        elif key == "blood_glucose" and numbers:
            value = numbers[0]
            if value < 3.9 or value > 11:
                status = "alert"
                note = "您的血糖偏离较明显，建议尽快复测，并按医嘱调整饮食或用药。"
            elif value > 7.8:
                status = "caution"
                note = "您的血糖略高，近期可优先选择清淡、低糖、规律分餐。"
            else:
                note = "您的血糖在参考范围内，继续保持规律饮食与监测。"
        elif key == "steps_today" and numbers:
            value = numbers[0]
            if value < 3000:
                status = "caution"
                note = "今天活动量偏少，若身体允许，可分次增加轻度步行。"
            elif value < 6000:
                status = "caution"
                note = "今天活动量还有提升空间，循序渐进会更容易坚持。"
            else:
                note = "今天的活动量不错，继续维持规律运动节奏。"

        cards.append(
            f'<div class="hero-vital-card {status}">'
            f'<div class="hero-vital-top">'
            f'<div><div class="hero-vital-label">{label}</div><div class="hero-vital-value">{escape(str(raw_value))}</div></div>'
            f'<div class="hero-vital-icon">{icon}</div>'
            f'</div>'
            f'<div class="hero-vital-range">参考范围 {escape(normal_range)}</div>'
            f'<div class="hero-vital-note">{escape(note)}</div>'
            f'</div>'
        )

    if not cards:
        return ""

    return (
        '<section class="hero-vitals">'
        '<div class="flex items-center justify-between gap-3 mb-3">'
        '<div>'
        '<div class="text-sm font-bold text-slate-900">您最新的健康情况</div>'
        '<div class="text-xs text-slate-500 mt-1">先看看这里，就能快速知道今天身体的大致状态。</div>'
        '</div>'
        '<div class="text-xl">📊</div>'
        '</div>'
        f'<div class="hero-vitals-grid">{"".join(cards)}</div>'
        '</section>'
    )


def _render_condition_badges(conditions: list[str]) -> str:
    parts = []
    for c in conditions:
        color = _COND_COLORS.get(c, "bg-slate-500")
        parts.append(
            f'<span class="condition-chip inline-block {color} text-white px-3 py-1 '
            f'rounded-full text-xs font-semibold">{escape(_localize_zh_text(c))}</span>'
        )
    return "\n".join(parts)


def _render_risk_tags(tags: list[str]) -> str:
    if not tags:
        return (
            '<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
            'border bg-emerald-50 text-emerald-700 border-emerald-200">暂无重大风险</span>'
        )
    parts = []
    for tag in tags:
        cls = "bg-slate-50 text-slate-600 border-slate-200"
        tag_lower = tag.lower()
        for kw, c in _RISK_TAG_COLORS.items():
            if kw.lower() in tag_lower or kw in tag:
                cls = c
                break
        parts.append(
            f'<span class="inline-block px-3 py-1 rounded-full text-xs '
            f'font-medium border {cls}">{escape(_localize_zh_text(tag))}</span>'
        )
    return "\n".join(parts)


def _render_recommendations(recs: list) -> str:
    if not recs:
        return '<div class="text-sm text-slate-400">暂无具体建议</div>'
    parts = []
    for i, r in enumerate(recs):
        if isinstance(r, dict):
            text = _localize_zh_text(r.get("text", ""))
            reason = _localize_zh_text(r.get("reason", ""))
            category = r.get("category", "")
            icon = _CATEGORY_ICONS.get(category, _REC_ICONS[i % len(_REC_ICONS)])
        else:
            text = _localize_zh_text(str(r))
            reason = ""
            icon = _REC_ICONS[i % len(_REC_ICONS)]
        safe_text = escape(text, quote=True)
        feedback_key = escape(f"-1-rec-{text}", quote=True)
        reason_html = ""
        if reason:
            reason_html = (
                f'<div class="text-xs text-emerald-700 mt-1.5 leading-relaxed italic '
                f'bg-emerald-50 rounded px-2 py-1 border-l-2 border-emerald-300">'
                f'💬 {escape(reason)}</div>'
            )
        parts.append(
            f'<div class="bg-emerald-50 rounded-lg p-3 border border-emerald-100 meal-card">'
            f'<div class="flex items-start gap-3">'
            f'<span class="text-base mt-0.5">{icon}</span>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="text-sm text-slate-700 leading-relaxed font-medium">{escape(text)}</div>'
            f'{reason_html}</div>'
            f'<div class="flex flex-col gap-1 flex-shrink-0">'
            f'<button class="feedback-btn feedback-action feedback-action-positive like" title="喜欢" '
            f'data-day-idx="-1" data-meal-type="rec" data-item-name="{safe_text}" '
            f'data-feedback-key="{feedback_key}" data-feedback-type="like" aria-pressed="false" '
            f'onclick="saveLikeFromButton(this)">'
            f"<span class=\"feedback-action-dot\">✓</span>适合我</button>"
            f'<button class="feedback-btn feedback-action feedback-action-negative" title="不适合" '
            f'data-day-idx="-1" data-meal-type="rec" data-item-name="{safe_text}" '
            f'data-feedback-key="{feedback_key}" data-feedback-type="dislike" aria-pressed="false" '
            f'onclick="showFeedbackModalFromButton(this)">'
            f"<span class=\"feedback-action-dot\">−</span>不适合</button>"
            f'</div></div></div>'
        )
    return "\n".join(parts)


def _render_reasoning(reasoning: str) -> str:
    if not reasoning:
        return ""
    return (
        '<div class="mt-4 pt-3 border-t border-slate-100">'
        '<div class="text-[11px] text-slate-400 uppercase tracking-wide font-medium mb-1.5">'
        "评估依据</div>"
        f'<div class="text-xs text-slate-600 bg-slate-50 rounded-lg p-3 leading-relaxed">{escape(_localize_zh_text(reasoning))}</div>'
        '</div>'
    )


def _field_label(key: str) -> str:
    return _FIELD_LABELS.get(key, key.replace("_", " "))


def _render_adherence_dimension(icon: str, title: str, dim: dict) -> str:
    status = _localize_zh_text(dim.get("status") or "")
    detail_keys = [k for k in dim if k != "status"]
    if not status and not detail_keys:
        return ""

    is_good = any(kw in status.lower() or kw in status for kw in _GOOD_STATUS_KEYWORDS)
    status_cls = (
        "bg-emerald-50 text-emerald-700 border-emerald-200"
        if is_good
        else "bg-amber-50 text-amber-700 border-amber-200"
    )

    html = (
        f'<div class="bg-slate-50 rounded-lg p-4 border border-slate-100">'
        f'<div class="flex items-center gap-2 mb-2">'
        f'<span class="text-base">{icon}</span>'
        f'<span class="text-sm font-semibold text-slate-800">{title}</span>'
        f'</div>'
    )
    if status:
        html += (
            f'<span class="inline-block px-3 py-1 rounded-full text-xs font-medium '
            f'border {status_cls} mb-2">{escape(status)}</span>'
        )
    for key in detail_keys:
        val = dim[key]
        if val:
            label = _field_label(key)
            html += (
                f'<div class="text-xs text-slate-600 mt-1">'
                f'<span class="font-medium text-slate-500">{label}：</span> {escape(_localize_zh_text(str(val)))}'
                f'</div>'
            )
    html += '</div>'
    return html


def _render_adherence(adh: dict) -> str:
    """Render adherence details (used inside card-details toggle)."""
    if not adh:
        return ""

    period = adh.get("period") or ""
    cards = []
    for key, icon, title in _ADHERENCE_DIMENSIONS:
        dim = adh.get(key)
        if isinstance(dim, dict):
            card = _render_adherence_dimension(icon, title, dim)
            if card:
                cards.append(card)

    if not cards and not period:
        return ""

    inner = ""
    if period:
        inner += (
            f'<div class="text-xs text-slate-500 font-medium uppercase tracking-wide mb-3">'
            f'统计周期：{escape(period)}</div>'
        )
    if cards:
        inner += f'<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">{"".join(cards)}</div>'
    return inner


def _render_memory_overview(memory: dict) -> str:
    return ""


def _render_memory(memory: dict) -> str:
    return _render_memory_overview(memory)


def _stringify_compact(value: object) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return _localize_zh_text(value)
    if isinstance(value, list):
        parts = []
        for item in value[:4]:
            text = _stringify_compact(item)
            if text:
                parts.append(text)
        return "；".join(parts)
    if isinstance(value, dict):
        parts = []
        for key, val in value.items():
            text = _stringify_compact(val)
            if text:
                parts.append(f"{_field_label(key)}：{text}")
        return "；".join(parts)
    return _localize_zh_text(str(value))


def _extract_medications(profile: str) -> list[str]:
    if not profile:
        return []

    segment = ""
    patterns = [
        r"Medications?\s*:\s*([^\.]+)",
        r"Current medications?\s*:\s*([^\.]+)",
        r"用药[:：]\s*([^。]+)",
        r"正在服用[:：]\s*([^。]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, profile, flags=re.IGNORECASE)
        if match:
            segment = match.group(1).strip()
            break

    if not segment:
        return []

    seen = set()
    meds = []
    for raw in re.split(r"[;,，；]\s*", segment):
        item = raw.strip(" .。")
        if not item:
            continue
        norm = item.lower()
        if norm in seen:
            continue
        seen.add(norm)
        meds.append(_localize_zh_text(item))
    return meds[:5]


def _render_personalized_context(so: dict, payload: dict, memory: dict) -> str:
    evidence_items = so.get("personalized_evidence") or []
    cards: list[str] = []

    if evidence_items:
        category_meta = {
            "history": ("🧾", "病史重点"),
            "surgery": ("🩺", "手术与恢复"),
            "medication": ("💊", "当前用药"),
            "lab": ("🧪", "最近检查"),
            "symptom": ("⚠️", "近期症状"),
            "monitoring": ("📈", "监测变化"),
        }
        for item in evidence_items[:4]:
            if not isinstance(item, dict):
                continue
            category = item.get("category") or ""
            icon, label = category_meta.get(category, ("🎯", "个性化依据"))
            title = _localize_zh_text(item.get("title") or label)
            evidence = _localize_zh_text(item.get("evidence") or "")
            why_it_matters = _localize_zh_text(item.get("why_it_matters") or item.get("implication") or "")
            body = ""
            if evidence:
                body += f'<div class="text-sm text-slate-700 leading-relaxed">{escape(evidence)}</div>'
            if why_it_matters:
                body += (
                    '<div class="mt-3 text-xs text-slate-600 bg-slate-50 rounded-xl px-3 py-2 leading-relaxed border border-slate-200">'
                    f'所以这里会更强调：{escape(why_it_matters)}</div>'
                )
            if body:
                cards.append(
                    '<div class="sub-card sub-card-static">'
                    '<div class="sub-card-header">'
                    f'<span class="sub-card-icon">{icon}</span>'
                    '<div class="flex-1 min-w-0">'
                    f'<div class="sub-card-label">{escape(label)}</div>'
                    f'<div class="sub-card-value">{escape(title)}</div>'
                    '</div>'
                    '</div>'
                    f'<div class="sub-card-body">{body}</div>'
                    '</div>'
                )
        return "".join(cards)

    conditions = so.get("conditions") or []
    latest_summary = so.get("latest_health_summary") or {}
    adherence = so.get("adherence_analysis") or {}

    history_chips = []
    if conditions:
        history_chips.extend(conditions[:3])

    if history_chips:
        implication_parts = []
        if any(c in {"高血压", "Hypertension"} for c in conditions):
            implication_parts.append("营养安排会特别强调少盐")
        if any(c in {"2型糖尿病", "糖尿病", "Type 2 diabetes", "Diabetes"} for c in conditions):
            implication_parts.append("也会提醒规律分餐和减少精制糖")
        history_chip_html = "".join(
            f'<span class="context-chip">{escape(_localize_zh_text(chip))}</span>'
            for chip in history_chips[:4]
        )

        cards.append(
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">🧾</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">病史重点</div>'
            '<div class="sub-card-value">这次建议会先围绕您的基础病和恢复阶段</div>'
            '</div>'
            '</div>'
            '<div class="sub-card-body">'
            f'<div class="flex flex-wrap gap-2 mb-3">{history_chip_html}</div>'
            + (
                '<div class="text-xs text-slate-600 bg-slate-50 rounded-xl px-3 py-2 leading-relaxed border border-slate-200">'
                f'所以这里会更强调：{escape("；".join(implication_parts))}</div>'
                if implication_parts else ""
            )
            + '</div></div>'
        )

    med_issue = _stringify_compact((adherence.get("medication") or {}).get("issues"))
    med_adjustment = _stringify_compact((adherence.get("medication") or {}).get("adjustments"))

    if med_issue:
        med_body = ""
        if med_issue:
            med_body += f'<div class="text-sm text-slate-700 leading-relaxed">目前记录里提到：{escape(med_issue)}</div>'
        if med_adjustment:
            med_body += (
                '<div class="mt-3 text-xs text-slate-600 bg-slate-50 rounded-xl px-3 py-2 leading-relaxed border border-slate-200">'
                f'所以这里会更强调：{escape(med_adjustment)}</div>'
            )
        elif "恶心" in med_issue or "nausea" in med_issue.lower():
            med_body += (
                '<div class="mt-3 text-xs text-slate-600 bg-slate-50 rounded-xl px-3 py-2 leading-relaxed border border-slate-200">'
                '所以这里会更强调：少量多餐、温热软一点的食物，以及把不适和医生继续对上。</div>'
            )

        cards.append(
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">💊</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">当前用药</div>'
            '<div class="sub-card-value">用药情况和身体反应会直接影响营养建议</div>'
            '</div>'
            '</div>'
            f'<div class="sub-card-body">{med_body}</div>'
            '</div>'
        )

    metric_bits = []
    metric_labels = {
        "blood_pressure": "血压",
        "heart_rate": "心率",
        "blood_oxygen": "血氧",
        "blood_glucose": "血糖",
        "steps_today": "步数",
    }
    for key in ("blood_pressure", "blood_glucose", "steps_today", "heart_rate", "blood_oxygen"):
        value = latest_summary.get(key)
        if value not in (None, ""):
            metric_bits.append(f'{metric_labels.get(key, key)} {value}')

    monitoring_gap = _stringify_compact((adherence.get("monitoring") or {}).get("gaps"))
    recent_focus = []
    if metric_bits:
        recent_focus.append("最近记录：" + "，".join(metric_bits[:3]))
    if monitoring_gap:
        recent_focus.append("监测提醒：" + monitoring_gap)

    if recent_focus:
        implication = []
        if any("血糖" in bit for bit in metric_bits):
            implication.append("营养安排会更强调规律分餐")
        if any("步数" in bit for bit in metric_bits):
            implication.append("活动建议会更温和、循序渐进")
        if monitoring_gap:
            implication.append("也会提醒把监测补齐")

        cards.append(
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">📈</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">最近指标</div>'
            '<div class="sub-card-value">不是泛泛建议，而是结合您最近几天的真实记录</div>'
            '</div>'
            '</div>'
            '<div class="sub-card-body">'
            + "".join(f'<div class="text-sm text-slate-700 leading-relaxed mb-2">{escape(line)}</div>' for line in recent_focus[:3])
            + (
                '<div class="text-xs text-slate-600 bg-slate-50 rounded-xl px-3 py-2 leading-relaxed border border-slate-200">'
                f'所以这里会更强调：{escape("；".join(implication))}</div>'
                if implication else ""
            )
            + '</div></div>'
        )

    return "".join(cards)


def _render_patient_profile(profile: dict) -> str:
    if not isinstance(profile, dict) or not profile:
        return ""

    label = _localize_zh_text(str(profile.get("persona_label") or "个性化模式"))
    summary = _localize_zh_text(str(profile.get("summary") or ""))
    reasons = profile.get("reasons") or []
    mode = str(profile.get("communication_mode") or "")
    if mode == "simplified":
        chip = "简洁优先"
        chip_cls = "bg-rose-50 text-rose-700 border-rose-200"
    elif mode == "standard":
        chip = "行动优先"
        chip_cls = "bg-amber-50 text-amber-700 border-amber-200"
    else:
        chip = "细节优先"
        chip_cls = "bg-blue-50 text-blue-700 border-blue-200"

    reason_html = "".join(
        (
            '<div class="text-sm text-slate-600 leading-relaxed bg-white rounded-xl px-3 py-2 border border-slate-200">'
            f'{escape(_localize_zh_text(str(reason)))}'
            '</div>'
        )
        for reason in reasons[:3]
        if str(reason).strip()
    )
    if not reason_html and not summary:
        return ""

    return (
        '<div class="sub-card sub-card-static">'
        '<div class="sub-card-header">'
        '<span class="sub-card-icon">🧭</span>'
        '<div class="flex-1 min-w-0">'
        '<div class="sub-card-label">沟通分流</div>'
        f'<div class="sub-card-value" data-style-meta="label">{escape(label)}</div>'
        '</div>'
        f'<span class="inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold {chip_cls}" data-style-meta="chip">{escape(chip)}</span>'
        '</div>'
        '<div class="sub-card-body">'
        + (
            f'<div class="text-sm text-slate-700 leading-relaxed mb-3" data-copy-key="profile_card_summary">{escape(summary)}</div>'
            if summary else ""
        )
        + reason_html
        + '</div></div>'
    )


def _build_profile_copy(profile: dict) -> dict:
    mode = str((profile or {}).get("communication_mode") or "standard").strip() or "standard"
    copies = {
        "simplified": {
            "hero_tagline": "今天先记住最重要的 2 到 3 件事。",
            "home_subtitle": "先看最重要的状态和今天最该做的事。",
            "plan_subtitle": "按顺序把今天最重要的几件事做好就可以。",
            "nutrition_subtitle": "只看今天最值得优先照顾的饮食重点。",
            "trend_subtitle": "先看最关键的变化，再决定今天要不要调整节奏。",
            "why_subtitle": "用更少的信息解释为什么要这样做。",
            "profile_card_summary": "这类表达会先抓最重要的两三件事，用更短句、少步骤的方式呈现。",
            "profile_desc": "先按年龄、认知负担和近期疾病压力，决定这次更适合更短句、更少步骤的表达。",
            "treatment_desc": "把药物、治疗阶段和今天更该关注的点单独拎出来，减少理解负担。",
            "context_desc": "先把最关键的病史、用药和指标放前面，不展开太多术语。",
            "guidance_desc": "先说最值得留意的重点，不一次塞太多信息。",
            "recommendations_desc": "这些是今天最适合先完成的小步骤。",
            "plan_focus_desc": "先把今天最值得优先完成的 2 到 3 件事做好。",
            "longitudinal_desc": "只抓最关键的变化，方便继续保持。",
            "adherence_desc": "先看今天哪几件事做到了、哪件事容易漏。",
            "trend_story_desc": "滑动曲线，先看最关键的变化就可以。",
            "trend_compare_desc": "先看最近一段时间最明显的变化，再决定下一步。",
            "nutrition_priority_desc": "只看今天最重要的饮食重点。",
            "nutrition_diet_desc": "先看和现在最相关、最需要记住的饮食边界。",
            "nutrition_advice_desc": "先从最容易做到的营养安排开始。",
            "nutrition_tips_desc": "都是能直接用得上的小提醒。",
            "cuisine_desc": "如果愿意，也可以选几种平时更容易接受的口味。",
            "meal_desc": "给您一些更省心的早、中、晚餐参考。",
        },
        "standard": {
            "hero_tagline": "先看状态，再做今天最关键的几步。",
            "home_subtitle": "先看今天的状态、执行情况和下一步重点。",
            "plan_subtitle": "先按顺序把今天最值得做的几件事完成。",
            "nutrition_subtitle": "查看适合今天的饮食重点和餐食建议。",
            "trend_subtitle": "查看近期变化，再决定下一步怎么调得更合适。",
            "why_subtitle": "了解每条建议与您近期情况的关系。",
            "profile_card_summary": "这类表达会先告诉您现在该做什么，再补一层必要原因，读起来更平衡。",
            "profile_desc": "先按年龄、认知负担和近期疾病压力，决定这次更适合的表达方式。",
            "treatment_desc": "把药物、治疗阶段和今天更该关注的点单独拎出来看，会更贴近病人的真实处境。",
            "context_desc": "先把您的病史、当前用药和最近指标放在前面，后面的建议会更容易看懂。",
            "guidance_desc": "结合您最近的感受，整理出现在最值得留意的重点。",
            "recommendations_desc": "这些是现在更适合您去做的小步骤。",
            "plan_focus_desc": "聚焦关键行动，改善今天的健康状态。",
            "longitudinal_desc": "把这次回访和近期记录线索放在一起看，更容易知道哪里值得继续保持。",
            "adherence_desc": "看看最近用药、营养、活动和监测情况。",
            "trend_story_desc": "滑动曲线，查看每天或每周的平均记录。",
            "trend_compare_desc": "先看最近一段时间的变化，再决定下一步怎么调得更合适。",
            "nutrition_priority_desc": "根据今天的饮食和回访情况整理。",
            "nutrition_diet_desc": "先看和当前慢病/用药最相关的饮食边界。",
            "nutrition_advice_desc": "先看这段时间哪些营养安排更适合您。",
            "nutrition_tips_desc": "都是些更容易用得上的小提醒。",
            "cuisine_desc": "选一些您平时更喜欢的口味，后面的膳食建议会更贴近您。",
            "meal_desc": "给您一些这周更容易参考的早、中、晚餐搭配。",
        },
        "detailed": {
            "hero_tagline": "先看状态、变化和依据，再调整今天的计划。",
            "home_subtitle": "先看今天的状态、执行情况、关键变化和最新生命体征。",
            "plan_subtitle": "把今天要做什么和为什么这样做放在一起看。",
            "nutrition_subtitle": "查看饮食重点、餐食建议和背后的原因。",
            "trend_subtitle": "查看关键变化、趋势依据和下一步要重点跟进的方向。",
            "why_subtitle": "了解每条建议与您近期情况、病史和治疗阶段的关系。",
            "profile_card_summary": "这类表达会保留更多背景、变化依据和管理细节，方便逐条细看。",
            "profile_desc": "先按年龄、认知负担和近期疾病压力，决定这次是否保留更多原因说明和管理细节。",
            "treatment_desc": "把药物、治疗阶段和今天更该关注的点单独拎出来，并补充背后的考虑。",
            "context_desc": "先把病史、当前用药、最近指标和变化依据放在前面，方便后面逐条理解。",
            "guidance_desc": "结合最近记录和恢复阶段，整理出现在最值得留意的重点和原因。",
            "recommendations_desc": "这些是现在更适合您去做的小步骤，也会尽量补上为什么。",
            "plan_focus_desc": "把行动重点和为什么要这样做放在一起看，更方便调整今天的计划。",
            "longitudinal_desc": "把这次回访和近期记录线索放在一起看，更容易判断哪些做法值得继续坚持。",
            "adherence_desc": "把最近用药、营养、活动和监测情况放在一起看。",
            "trend_story_desc": "滑动曲线，查看每天或每周的平均记录和变化方向。",
            "trend_compare_desc": "先看最近一段时间的变化，再结合趋势判断下一步怎么调得更合适。",
            "nutrition_priority_desc": "根据今天的饮食、近期记录和恢复阶段整理。",
            "nutrition_diet_desc": "先看和当前慢病、用药及恢复阶段最相关的饮食边界。",
            "nutrition_advice_desc": "先看这段时间哪些营养安排更适合您，以及为什么。",
            "nutrition_tips_desc": "这些小提醒会尽量补上使用场景和原因。",
            "cuisine_desc": "选一些您平时更喜欢的口味，后面的膳食建议会尽量参考您的偏好。",
            "meal_desc": "给您一些这周更容易参考的早、中、晚餐搭配，并保留更多解释。",
        },
    }
    return copies.get(mode, copies["standard"])


def _build_profile_style_meta() -> dict:
    return {
        "simplified": {
            "label": "简明陪伴版",
            "chip": "简洁优先",
            "description": "句子更短、步骤更少，先告诉您今天最值得先做的事。",
            "preview_note": "适合想先抓重点、暂时不想看太多解释的时候。",
        },
        "standard": {
            "label": "标准行动版",
            "chip": "行动优先",
            "description": "保留重点说明和下一步行动，读起来更平衡。",
            "preview_note": "适合大多数日常健康管理和规律随访场景。",
        },
        "detailed": {
            "label": "详细管理版",
            "chip": "细节优先",
            "description": "会保留更多原因、背景和管理细节，方便细看。",
            "preview_note": "适合愿意看更完整依据和更细管理信息的时候。",
        },
    }


def _render_longitudinal_highlights(so: dict) -> str:
    highlights = so.get("longitudinal_highlights") or []
    if not isinstance(highlights, list) or not highlights:
        return ""

    icon_map = {
        "medication": "💊",
        "appetite": "🥣",
        "exercise": "🚶",
        "monitoring": "🩺",
    }
    cards: list[str] = []
    for item in highlights[:4]:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "")
        title = _localize_zh_text(str(item.get("title") or "近期变化"))
        summary = _localize_zh_text(str(item.get("summary") or ""))
        evidence = _localize_zh_text(str(item.get("evidence") or ""))
        comparison_note = _localize_zh_text(str(item.get("comparison_note") or ""))
        comparison_tone = str(item.get("comparison_tone") or "neutral")
        if not summary:
            continue
        body = ""
        if comparison_note:
            body += (
                f'<div class="mb-3 inline-flex items-center rounded-full border px-3 py-1.5 text-xs font-semibold '
                f'{_longitudinal_tone_classes(comparison_tone)}">{escape(comparison_note)}</div>'
            )
        body += f'<div class="text-sm text-slate-700 leading-relaxed">{escape(summary)}</div>'
        if evidence:
            body += (
                '<div class="mt-3 text-xs text-slate-600 bg-slate-50 rounded-xl px-3 py-2 leading-relaxed border border-slate-200">'
                f'{escape(evidence)}</div>'
            )
        cards.append(
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            f'<span class="sub-card-icon">{icon_map.get(category, "📈")}</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">纵向比较</div>'
            f'<div class="sub-card-value">{escape(title)}</div>'
            '</div>'
            '</div>'
            f'<div class="sub-card-body">{body}</div>'
            '</div>'
        )
    return "".join(cards)


def _ai_insight_card_meta(category: str, bucket: str, previous_score: int | None = None, current_score: int | None = None) -> tuple[str, str, str]:
    meta = {
        "medication": {
            "good": ("💊", "吃药节奏更稳了", "good"),
            "mixed": ("💊", "吃药有一点波动", "mixed"),
            "needs_attention": ("💊", "用药这一步容易被打断", "alert"),
            "neutral": ("💊", "用药变化还在观察", "neutral"),
        },
        "appetite": {
            "good": ("🐣", "营养补得更稳了", "good"),
            "mixed": ("🥣", "营养这一步在找回节奏", "mixed"),
            "needs_attention": ("🍗", "蛋白和营养补得还不够", "alert"),
            "neutral": ("🥣", "营养变化还在观察", "neutral"),
        },
        "exercise": {
            "good": ("💪", "体力正在慢慢恢复", "good"),
            "mixed": ("💪", "体力正在慢慢恢复", "mixed"),
            "needs_attention": ("🥱", "活动量比前几天少了", "alert"),
            "neutral": ("💪", "体力正在慢慢恢复", "neutral"),
        },
        "monitoring": {
            "good": ("🩺", "监测做得更稳了", "good"),
            "mixed": ("🩺", "监测还在慢慢补齐", "mixed"),
            "needs_attention": ("📋", "监测这一步还有缺口", "alert"),
            "neutral": ("🩺", "监测变化还在观察", "neutral"),
        },
    }
    category_meta = meta.get(category, meta["exercise"])
    if category == "exercise" and previous_score not in (None, "") and current_score not in (None, ""):
        try:
            if int(current_score) >= int(previous_score):
                return ("💪", "体力正在慢慢恢复", "good" if int(current_score) >= 72 else "mixed")
        except (TypeError, ValueError):
            pass
    return category_meta.get(bucket, category_meta["neutral"])


def _short_ai_insight_detail(category: str, bucket: str, current_fact: str, summary: str) -> str:
    fact = _localize_zh_text(current_fact or summary).strip()
    fact = fact.replace("这次回访里，", "").replace("本次事实：", "").strip()
    if category == "medication":
        return "这次吃药整体稳住了，恶心相关漏服还是要留意。" if bucket == "good" else "这次吃药还是会被恶心或作息打断。"
    if category == "appetite":
        return "这几天蛋白和正餐补得偏少，容易影响体力。" if bucket == "needs_attention" else "这几天营养在慢慢找回节奏。"
    if category == "exercise":
        return "最近活动量还容易受疼痛和疲劳影响。" if bucket == "needs_attention" else "最近活动和体力有在慢慢往回走。"
    if category == "monitoring":
        return "这几天监测还没完全补齐，后面更容易漏。"
    if fact:
        return fact[:34] + ("…" if len(fact) > 34 else "")
    return "这一步最近有变化，值得继续留意。"


def _build_ai_insight_memory_line(category: str, so: dict, payload: dict) -> str:
    recent_text = _localize_zh_text(str(((payload.get("memory") or {}).get("recent_health_dynamics")) or "")).strip()
    if category == "medication":
        return "我记得您之前提过，吃药后会有些恶心，所以这次能稳住已经很不容易。"
    if category == "appetite":
        return "我记得您这段时间胃口一直不太好，所以营养这一步更需要慢慢补。"
    if category == "exercise":
        return "我记得您最近活动容易受膝盖和疲劳影响，所以能慢慢找回节奏就很好。"
    if category == "monitoring":
        return "我记得您前几天监测容易断掉，所以这一步先补回来就很重要。"
    if recent_text:
        return recent_text[:46] + ("…" if len(recent_text) > 46 else "")
    return _build_supportive_note(so, payload)


def _render_home_longitudinal_recap(so: dict, payload: dict) -> str:
    highlights = so.get("longitudinal_highlights") or []
    if not isinstance(highlights, list) or not highlights:
        return ""
    current_items = _collect_current_adherence_items(payload, so)
    recent_scores = {
        str(item.get("category") or ""): item
        for item in (so.get("recent_adherence_scores") or [])
        if isinstance(item, dict)
    }
    cards: list[str] = []
    for item in highlights[:3]:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "")
        current_item = current_items.get(category) or {}
        bucket = _status_bucket(current_item.get("status") or current_item.get("status_label"))
        score_item = recent_scores.get(category) or {}
        delta_label = _localize_zh_text(str(score_item.get("delta_label") or "")).strip()
        previous_score = score_item.get("previous_score")
        current_score = score_item.get("score")
        icon, title, tone_key = _ai_insight_card_meta(category, bucket, previous_score, current_score)
        summary = _localize_zh_text(str(item.get("summary") or "")).strip()
        comparison_note = _localize_zh_text(str(item.get("comparison_note") or "")).strip()
        comparison_tone = str(item.get("comparison_tone") or tone_key or "neutral")
        current_fact = _localize_zh_text(str(current_item.get("text") or "")).strip()
        if not comparison_note and not summary:
            continue
        compare_line = ""
        if previous_score not in (None, "") and current_score not in (None, ""):
            compare_line = f"最近 {previous_score} → {current_score} 分"
        detail_line = _short_ai_insight_detail(category, bucket, current_fact, summary)
        footer_line = _build_ai_insight_memory_line(category, so, payload)
        delta_html = f'<div class="ai-insight-delta">{escape(delta_label)}</div>' if delta_label else ""
        compare_html = f'<div class="ai-insight-copy">{escape(compare_line)}</div>' if compare_line else ""
        detail_html = f'<div class="ai-insight-copy">{escape(detail_line)}</div>' if detail_line else ""
        footer_html = (
            f'<div class="ai-insight-memory {_longitudinal_tone_classes(comparison_tone)}">{escape(footer_line)}</div>'
            if footer_line
            else ""
        )
        cards.append(
            '<div class="ai-insight-card">'
            + '<div class="ai-insight-top">'
            + f'<div class="ai-insight-icon">{icon}</div>'
            + '<div class="min-w-0 flex-1">'
            + f'<div class="ai-insight-title">{escape(title)}</div>'
            + delta_html
            + '</div>'
            + '</div>'
            + '<div class="ai-insight-body">'
            + compare_html
            + detail_html
            + footer_html
            + '</div>'
            + '</div>'
        )
    if not cards:
        return ""
    return (
        '<section class="journey-card ai-insight-panel">'
        '<div class="ai-insight-head">'
        '<div class="ai-insight-bot">🤖</div>'
        '<div>'
        '<div class="insight-eyebrow">AI 洞察</div>'
        '<div class="journey-section-title">我发现了一些值得关注的变化</div>'
        '<div class="journey-section-copy">把这次回访和前一段时间放在一起看，哪些在变好、哪些还需要补一步，会更容易看清楚。</div>'
        '</div>'
        '</div>'
        f'<div class="ai-insight-list">{"".join(cards)}</div>'
        '</section>'
    )


_CONDITION_CONTEXTS = {
    "feeling_unwell": {
        "show_sections": {"header", "escalation", "ai_message", "guidance", "vitals", "meal_plan", "guardrail"},
        "tone_override": "gentle_patient",
        "header_greeting": "我们在这里陪着您",
        "guidance_emphasis": "rest",
    },
    "post_chemotherapy": {
        "show_sections": {"header", "escalation", "ai_message", "guidance", "vitals", "recommendations", "nutrition", "meal_plan", "cuisine", "diet_tips", "submit", "guardrail"},
        "tone_override": "gentle_patient",
        "header_greeting": "您已经做得很好",
        "guidance_emphasis": "nutrition",
    },
    "post_surgery_recovering": {
        "show_sections": {"header", "escalation", "ai_message", "memory", "guidance", "vitals", "adherence", "recommendations", "nutrition", "diet_table", "cuisine", "meal_plan", "diet_tips", "map", "submit", "guardrail"},
        "tone_override": None,
        "header_greeting": "您好！",
        "guidance_emphasis": None,
    },
    "chronic_pain_flare": {
        "show_sections": {"header", "escalation", "ai_message", "guidance", "vitals", "recommendations", "meal_plan", "guardrail"},
        "tone_override": "gentle_patient",
        "header_greeting": "今天辛苦了",
        "guidance_emphasis": "rest",
    },
    "low_mood_isolated": {
        "show_sections": {"header", "ai_message", "guidance", "vitals", "recommendations", "nutrition", "meal_plan", "cuisine", "map", "diet_tips", "submit", "guardrail"},
        "tone_override": "warm_encouraging",
        "header_greeting": "您不是一个人",
        "guidance_emphasis": "exercise",
    },
    "cognitive_decline": {
        "show_sections": {"header", "ai_message", "guidance", "vitals", "meal_plan", "guardrail"},
        "tone_override": "gentle_patient",
        "header_greeting": "今天请记住这些",
        "guidance_emphasis": "monitoring",
    },
    "caregiver_absent": {
        "show_sections": {"header", "escalation", "ai_message", "guidance", "vitals", "recommendations", "meal_plan", "map", "guardrail"},
        "tone_override": "warm_encouraging",
        "header_greeting": "您的日常关心",
        "guidance_emphasis": None,
    },
    "medication_adjustment": {
        "show_sections": {"header", "ai_message", "guidance", "vitals", "recommendations", "nutrition", "meal_plan", "diet_tips", "submit", "guardrail"},
        "tone_override": "authority_based",
        "header_greeting": "照护团队的重要提醒",
        "guidance_emphasis": "monitoring",
    },
    "high_fall_risk": {
        "show_sections": {"header", "escalation", "ai_message", "guidance", "vitals", "recommendations", "meal_plan", "map", "guardrail"},
        "tone_override": "warm_encouraging",
        "header_greeting": "今天先把安全放第一",
        "guidance_emphasis": "exercise",
    },
    "stable_routine": {
        "show_sections": {"header", "escalation", "ai_message", "memory", "guidance", "vitals", "adherence", "risk_tags", "recommendations", "reasoning", "nutrition", "diet_table", "cuisine", "meal_plan", "diet_tips", "map", "submit", "guardrail"},
        "tone_override": None,
        "header_greeting": "您好！",
        "guidance_emphasis": None,
    },
}

_FULL_SECTIONS = _CONDITION_CONTEXTS["stable_routine"]["show_sections"]


_TONE_STYLES = {
    "warm_encouraging": {
        "icon": "💚",
        "title": "为什么这对您重要",
        "border_color": "border-emerald-200",
        "header_color": "text-emerald-800",
        "summary_bg": "bg-emerald-50 border-l-4 border-emerald-400",
        "tip_why_color": "text-emerald-700",
    },
    "direct_practical": {
        "icon": "📋",
        "title": "健康要点",
        "border_color": "border-blue-200",
        "header_color": "text-blue-800",
        "summary_bg": "bg-blue-50 border-l-4 border-blue-400",
        "tip_why_color": "text-blue-700",
    },
    "authority_based": {
        "icon": "👨\u200d⚕️",
        "title": "照护团队建议",
        "border_color": "border-indigo-200",
        "header_color": "text-indigo-800",
        "summary_bg": "bg-indigo-50 border-l-4 border-indigo-400",
        "tip_why_color": "text-indigo-700",
    },
    "gentle_patient": {
        "icon": "🌸",
        "title": "给您的温和提醒",
        "border_color": "border-rose-200",
        "header_color": "text-rose-800",
        "summary_bg": "bg-rose-50 border-l-4 border-rose-300",
        "tip_why_color": "text-rose-700",
    },
}


def _render_health_guidance(guidance: dict, conditions: list[str], tone_profile: dict = None) -> str:
    """Render health guidance as always-visible sub-cards with distinct topics."""
    if not guidance and not conditions:
        return ""

    summary = ""
    tips = []
    if isinstance(guidance, dict):
        summary = _localize_zh_text(guidance.get("summary") or "")
        tips = guidance.get("tips") or []
    elif isinstance(guidance, str):
        summary = _localize_zh_text(guidance)

    if not summary and not tips and not conditions:
        return ""

    tone_type = (tone_profile or {}).get("style") or "warm_encouraging"
    style = _TONE_STYLES.get(tone_type, _TONE_STYLES["warm_encouraging"])
    patient_name = (tone_profile or {}).get("preferred_name") or ""

    html = ""
    if patient_name:
        html += (
            f'<div class="text-xs text-slate-500 mb-2">'
            f'为 <span class="font-semibold">{escape(patient_name)}</span> 个性化整理</div>'
        )
    if summary:
        html += (
            f'<div class="leading-relaxed mb-3 {style["summary_bg"]} '
            f'rounded-lg p-4" style="font-size:0.95em">'
            f'{escape(summary)}</div>'
        )

    guidance_icons = {"protein": "🥩", "low_salt": "🧂", "low_oil": "🫒",
                      "hydration": "💧", "fiber": "🌾", "exercise": "🚶",
                      "rest": "😴", "monitoring": "📋"}

    for tip in tips:
        if isinstance(tip, dict):
            icon = guidance_icons.get(tip.get("category", ""), "💡")
            text = _localize_zh_text(tip.get("text", ""))
            why = _localize_zh_text(tip.get("why", ""))
        else:
            icon = "💡"
            text = _localize_zh_text(str(tip))
            why = ""

        body_html = ""
        if why:
            body_html = (
                f'<div class="text-sm {style["tip_why_color"]} leading-relaxed italic">'
                f'→ {escape(why)}</div>'
            )

        html += (
            f'<div class="sub-card sub-card-static">'
            f'<div class="sub-card-header">'
            f'<span class="sub-card-icon">{icon}</span>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="sub-card-value" style="font-size:0.95em">{escape(text)}</div>'
            f'</div>'
            f'</div>'
        )
        if body_html:
            html += f'<div class="sub-card-body">{body_html}</div>'
        html += '</div>'

    return html


def _render_diet_table(diet_table: list[dict]) -> str:
    if not diet_table:
        return ""
    rows = ""
    for item in diet_table:
        rows += (
            f'<tr>'
            f'<td class="px-4 py-3 font-medium text-slate-800">{escape(_localize_zh_text(item.get("condition", "")))}</td>'
            f'<td class="px-4 py-3 text-slate-600">{escape(_localize_zh_text(item.get("principle", "")))}</td>'
            f'<td class="px-4 py-3 text-emerald-700">{escape(_localize_zh_text(item.get("recommend", "")))}</td>'
            f'<td class="px-4 py-3 text-rose-600">{escape(_localize_zh_text(item.get("avoid", "")))}</td>'
            f'</tr>'
        )
    return (
        '<div class="overflow-x-auto rounded-xl border border-slate-200 bg-white">'
        '<table class="w-full text-sm">'
        '<thead><tr class="bg-slate-50">'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">疾病</th>'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">原则</th>'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">推荐</th>'
        '<th class="px-4 py-2 text-left text-xs font-semibold text-slate-500">避免</th>'
        '</tr></thead>'
        f'<tbody class="divide-y divide-slate-100">{rows}</tbody>'
        '</table></div>'
    )


def _render_diet_tips(tips: list[dict]) -> str:
    """Render each diet tip as an always-visible sub-card."""
    if not tips:
        return ""

    html = ""
    for tip in tips:
        title = _localize_zh_text(tip.get("title", ""))
        detail = _localize_zh_text(tip.get("detail", ""))
        icon = tip.get("icon", "💡")
        safe_title = escape(title).replace("'", "&#39;")

        body_html = ""
        if detail:
            body_html = (
                f'<div class="text-sm text-slate-600 leading-relaxed mb-2">{escape(detail)}</div>'
                f'<div class="feedback-actions" style="flex-direction:row;flex-wrap:wrap">'
                f'<button class="feedback-btn like" title="有帮助" data-day-idx="-1" data-meal-type="tip" '
                f'data-item-name="{safe_title}" data-default-label="适合我" data-active-label="已选择" '
                f'onclick="saveLikeFromButton(this)">适合我</button>'
                f'<button class="feedback-btn feedback-skip" title="不适合我" data-day-idx="-1" data-meal-type="tip" '
                f'data-item-name="{safe_title}" data-default-label="不适合" data-active-label="已跳过" '
                f'onclick="showFeedbackModalFromButton(this)">不适合</button>'
                f'</div>'
            )

        html += (
            f'<div class="sub-card sub-card-static">'
            f'<div class="sub-card-header">'
            f'<span class="sub-card-icon">{icon}</span>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="sub-card-value" style="font-size:0.92em">{escape(title)}</div>'
            f'</div>'
            f'</div>'
        )
        if body_html:
            html += f'<div class="sub-card-body">{body_html}</div>'
        html += '</div>'

    return html


def _render_map_section(
    ai_msg_hospital: str,
    ai_msg_park: str,
    patient_lat: float,
    patient_lon: float,
) -> str:
    lat = patient_lat if patient_lat is not None else 39.9042
    lon = patient_lon if patient_lon is not None else 116.4074

    hosp_js = json.dumps(ai_msg_hospital, ensure_ascii=False)
    park_js = json.dumps(ai_msg_park, ensure_ascii=False)

    css = (
        "<style>"
        "#bmap{width:100%;height:100%}"
        "#locate-btn{position:absolute;bottom:12px;right:12px;z-index:999;width:38px;height:38px;"
        "border-radius:50%;border:none;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,0.2);"
        "cursor:pointer;font-size:1.1em;display:flex;align-items:center;justify-content:center}"
        "#locate-btn:active{transform:scale(0.92)}"
        ".map-toggle{display:flex;margin-top:10px;background:#f1f5f9;border-radius:10px;padding:3px}"
        ".map-toggle button{flex:1;padding:8px 0;border:none;background:transparent;border-radius:8px;"
        "font-size:0.85em;font-weight:600;color:#94a3b8;cursor:pointer;transition:all 0.25s}"
        ".map-toggle button.active{background:linear-gradient(135deg,#42a5f5,#1e88e5);color:#fff;"
        "box-shadow:0 2px 8px rgba(30,136,229,0.3)}"
        ".map-toggle button.active.park-mode{background:linear-gradient(135deg,#66bb6a,#43a047);"
        "box-shadow:0 2px 8px rgba(67,160,71,0.3)}"
        ".map-place{display:flex;align-items:center;gap:10px;background:#f8fafc;border-radius:10px;"
        "padding:12px;margin-top:8px;cursor:pointer;border:2px solid transparent;transition:all 0.15s}"
        ".map-place:active{transform:scale(0.98)}"
        ".map-place.focused{border-color:#1e88e5;box-shadow:0 2px 10px rgba(30,136,229,0.15)}"
        ".map-place.focused.park-mode{border-color:#43a047;box-shadow:0 2px 10px rgba(67,160,71,0.15)}"
        ".map-place-icon{width:34px;height:34px;border-radius:8px;display:flex;align-items:center;"
        "justify-content:center;font-size:1em;flex-shrink:0}"
        ".map-place-icon.hospital{background:#e3f2fd}"
        ".map-place-icon.park{background:#e8f5e9}"
        ".map-place-nav{flex-shrink:0;width:30px;height:30px;border-radius:50%;border:none;"
        "background:#1e88e5;color:#fff;font-size:0.9em;cursor:pointer;display:flex;align-items:center;"
        "justify-content:center;box-shadow:0 2px 6px rgba(30,136,229,0.35)}"
        ".map-place-nav.park-mode{background:#43a047;box-shadow:0 2px 6px rgba(67,160,71,0.35)}"
        ".map-place-nav:active{transform:scale(0.9)}"
        ".map-dist{font-size:0.75em;font-weight:700;padding:3px 8px;border-radius:16px;"
        "white-space:nowrap;flex-shrink:0}"
        ".map-dist.hospital{background:#e3f2fd;color:#1565c0}"
        ".map-dist.park{background:#e8f5e9;color:#2e7d32}"
        "</style>"
    )

    html = (
        '<section class="journey-card nearby-support-card">'
        '<div class="journey-section-title">附近支持</div>'
        '<div class="journey-section-copy">查看当前位置附近的医院和公园。</div>'
        '<p class="text-sm text-slate-600 mb-3" id="ai-map-text">' + ai_msg_hospital + "</p>"
        '<div class="rounded-2xl overflow-hidden border border-slate-200 relative" style="height:240px">'
        '<div id="bmap"></div>'
        '<button id="locate-btn" title="回到我的位置">📍</button>'
        "</div>"
        '<div class="map-toggle">'
        '<button class="active" id="btn-hospital" onclick="switchMapMode(\'hospital\')">🏥 附近医院</button>'
        '<button id="btn-park" onclick="switchMapMode(\'park\')">🌳 附近公园</button>'
        "</div>"
        '<div id="map-cards"></div>'
        "</section>"
    )

    js_template = r"""<script>
(function() {
  var bmap = new BMap.Map("bmap");
  bmap.enableScrollWheelZoom(true);
  var userPoint = new BMap.Point(__FALLBACK_LON__, __FALLBACK_LAT__);
  var mapMode = 'hospital';
  var mapMarkers = [];
  var mapCards = [];
  var mapRoute = null;
  var userOverlays = [];
  var AI_MAP_TEXT = { hospital: __HOSP_MSG__, park: __PARK_MSG__ };

  document.getElementById('locate-btn').addEventListener('click', function() {
    if (userPoint) { bmap.panTo(userPoint); bmap.setZoom(15); }
  });

  var USER_ICON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28">'
    + '<circle cx="14" cy="14" r="13" fill="#4285f4" fill-opacity="0.2" stroke="#4285f4" stroke-width="1"/>'
    + '<circle cx="14" cy="14" r="7" fill="#4285f4" stroke="#fff" stroke-width="2.5"/>'
    + '</svg>';
  var USER_ICON = new BMap.Icon(
    'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(USER_ICON_SVG),
    new BMap.Size(28, 28),
    { anchor: new BMap.Size(14, 14) }
  );

  function addUserOverlays() {
    userOverlays.forEach(function(o) { bmap.removeOverlay(o); });
    userOverlays = [];
    var marker = new BMap.Marker(userPoint, { icon: USER_ICON });
    bmap.addOverlay(marker);
    userOverlays.push(marker);
    var label = new BMap.Label('\u60a8\u5728\u8fd9\u91cc', {
      position: userPoint,
      offset: new BMap.Size(16, -8)
    });
    label.setStyle({
      background:'#4285f4',color:'#fff',border:'none',
      borderRadius:'6px',padding:'2px 8px',
      fontSize:'12px',fontWeight:'600',
      boxShadow:'0 1px 4px rgba(0,0,0,0.25)',whiteSpace:'nowrap'
    });
    bmap.addOverlay(label);
    userOverlays.push(label);
  }

  function clearRoute() {
    if (mapRoute) { mapRoute.clearResults(); mapRoute = null; }
  }
  function clearResultMarkers() {
    clearRoute();
    mapMarkers.forEach(function(m) { bmap.removeOverlay(m); });
    mapMarkers = [];
    mapCards = [];
  }

  bmap.centerAndZoom(userPoint, 15);
  addUserOverlays();
  doMapSearch('hospital');

  window.switchMapMode = function(mode) {
    if (mode === mapMode) return;
    mapMode = mode;
    document.getElementById('btn-hospital').className = mode === 'hospital' ? 'active' : '';
    document.getElementById('btn-park').className = mode === 'park' ? 'active park-mode' : '';
    document.getElementById('ai-map-text').textContent = AI_MAP_TEXT[mode];
    clearResultMarkers();
    document.getElementById('map-cards').innerHTML = '<div style="text-align:center;color:#bbb;padding:16px;font-size:0.85em">\u641c\u7d22\u4e2d\u2026</div>';
    doMapSearch(mode);
  };

  function doMapSearch(mode) {
    if (!userPoint) return;
    var keyword = mode === 'hospital' ? '\u533b\u9662' : '\u516c\u56ed';
    var local = new BMap.LocalSearch(bmap, {
      renderOptions: { autoViewport: false },
      onSearchComplete: function(results) {
        clearResultMarkers();
        var container = document.getElementById('map-cards');
        container.innerHTML = '';
        if (!results || local.getStatus() !== BMAP_STATUS_SUCCESS || results.getCurrentNumPois() === 0) {
          container.innerHTML = '<div style="text-align:center;color:#bbb;padding:16px;font-size:0.85em">\u9644\u8fd1\u6682\u65e0\u76f8\u5173\u5730\u70b9</div>';
          return;
        }
        var count = results.getCurrentNumPois();
        for (var i = 0; i < count; i++) {
          (function(idx) {
            var poi = results.getPoi(idx);
            var dist = bmap.getDistance(userPoint, poi.point);
            var distText = dist >= 1000 ? (dist/1000).toFixed(1)+' km' : Math.round(dist)+' m';
            var marker = new BMap.Marker(poi.point);
            bmap.addOverlay(marker);
            mapMarkers.push(marker);
            marker.addEventListener('click', function() { focusMapCard(idx, poi); });
            var card = document.createElement('div');
            card.className = 'map-place';
            card.innerHTML = '<div class="map-place-icon '+mode+'">'+(mode==='hospital'?'\ud83c\udfe5':'\ud83c\udf33')+'</div>'
              +'<div style="flex:1;min-width:0"><div style="font-size:0.9em;font-weight:600;color:#222;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+poi.title+'</div>'
              +'<div style="font-size:0.75em;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+(poi.address||'\u6682\u65e0\u5730\u5740')+'</div></div>'
              +'<div class="map-dist '+mode+'">'+distText+'</div>'
              +'<button class="map-place-nav'+(mode==='park'?' park-mode':'')+'" title="\u5bfc\u822a">\u27a4</button>';
            card.addEventListener('click', function(e) {
              if (e.target.classList.contains('map-place-nav')) return;
              focusMapCard(idx, poi);
            });
            card.querySelector('.map-place-nav').addEventListener('click', function(e) {
              e.stopPropagation();
              navigateMapTo(poi);
            });
            container.appendChild(card);
            mapCards.push(card);
          })(i);
        }
      }
    });
    local.searchNearby(keyword, userPoint, 4000);
  }

  function focusMapCard(idx, poi) {
    mapCards.forEach(function(c) { c.classList.remove('focused','park-mode'); });
    mapCards[idx].classList.add('focused');
    if (mapMode === 'park') mapCards[idx].classList.add('park-mode');
    mapCards[idx].scrollIntoView({ behavior:'smooth', block:'nearest' });
    bmap.panTo(poi.point);
    mapMarkers[idx].openInfoWindow(
      new BMap.InfoWindow('<b>'+poi.title+'</b><br><span style="color:#888;font-size:12px">'+(poi.address||'')+'</span>')
    );
    clearRoute();
    var routeColor = mapMode === 'hospital' ? '#1e88e5' : '#43a047';
    var walking = new BMap.WalkingRoute(bmap, {
      renderOptions: { map: bmap, autoViewport: false },
      onSearchComplete: function(results) {
        if (walking.getStatus() !== BMAP_STATUS_SUCCESS) return;
        var plan = results.getPlan(0);
        for (var s = 0; s < plan.getNumRoutes(); s++) {
          var route = plan.getRoute(s);
          var path = route.getPolyline();
          if (path) { path.setStrokeColor(routeColor); path.setStrokeWeight(5); path.setStrokeOpacity(0.85); }
        }
        addUserOverlays();
      }
    });
    walking.search(userPoint, poi.point);
    mapRoute = walking;
  }

  function navigateMapTo(poi) {
    var destLat = poi.point.lat;
    var destLng = poi.point.lng;
    var destName = encodeURIComponent(poi.title);
    var isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
    var appUrl = 'baidumap://map/direction?destination=latlng:'+destLat+','+destLng+'|name:'+destName+'&mode=walking&coord_type=bd09ll&src=webapp';
    var webUrl = 'https://api.map.baidu.com/marker?location='+destLat+','+destLng+'&title='+destName+'&output=html&coord_type=bd09ll&src=webapp';
    if (isMobile) {
      window.location.href = appUrl;
      setTimeout(function() { window.location.href = webUrl; }, 2000);
    } else {
      window.open(webUrl, '_blank');
    }
  }
})();
</script>"""

    js = js_template.replace("__HOSP_MSG__", hosp_js).replace("__PARK_MSG__", park_js)
    js = js.replace("__FALLBACK_LON__", str(lon)).replace("__FALLBACK_LAT__", str(lat))
    return css + "\n" + html + "\n" + js


def _render_local_resource_section(payload: dict, so: dict) -> str:
    items = _build_local_resource_items(payload, so)
    if not items:
        return ""
    location_label = _resource_location_label(payload)
    location = payload.get("location") or {}
    loc = location.get("current") or {}
    patient_lat = loc.get("lat")
    patient_lon = loc.get("lon")
    has_precise_location = patient_lat not in (None, "") and patient_lon not in (None, "")
    if not has_precise_location:
        patient_lat = 39.90923
        patient_lon = 116.397428
    has_location = True
    guide_chips = [
        f"📍 {location_label}",
        f"🧩 已为您筛出 {len(items)} 类支持",
        "🫶 地图和标签卡会一起联动",
    ]
    cards = []
    active_group_id = next((str(item.get("id")) for item in items if str(item.get("id") or "") == "hospital"), str(items[0].get("id") or "hospital"))
    for item in items:
        query = str(item.get("query") or "").strip()
        item_id = str(item.get("id") or "")
        action_js = escape(f'activateSupportMode({json.dumps(item_id, ensure_ascii=False)}, true)', quote=True)
        tone = escape(str(item.get("tone") or "lavender"))
        avatar_html = "".join(
            f'<span class="resource-avatar">{escape(str(icon or ""))}</span>'
            for icon in (item.get("avatars") or [])[:2]
        )
        examples_html = "".join(
            f'<li>{escape(str(example or ""))}</li>'
            for example in (item.get("examples") or [])[:3]
            if str(example or "").strip()
        )
        active_class = " active" if item_id == active_group_id else ""
        results_shell_class = " active" if item_id == active_group_id else ""
        switch_js = escape(f'activateSupportMode({json.dumps(item_id, ensure_ascii=False)}, false)', quote=True)
        cards.append(
            f'<div class="support-category-card resource-card resource-card-{tone}{active_class}" '
            f'data-support-card="{escape(item_id, quote=True)}"'
            + (f' onclick="{switch_js}"' if switch_js else "")
            + '>'
            f'<div class="resource-visual resource-visual-{tone}">'
            f'<span class="resource-availability">{escape(str(item.get("availability") or "推荐"))}</span>'
            f'<span class="resource-visual-primary">{escape(str(item.get("icon") or "📍"))}</span>'
            f'<span class="resource-visual-secondary">{escape(str(item.get("icon_secondary") or ""))}</span>'
            '</div>'
            '<div class="resource-copy">'
            '<div class="resource-topline">'
            f'<span class="resource-eyebrow">{escape(str(item.get("eyebrow") or "推荐资源"))}</span>'
            f'<span class="resource-subbadge">{escape(str(item.get("subbadge") or ""))}</span>'
            '</div>'
            '<div class="resource-card-head">'
            f'<div class="resource-title">{escape(str(item.get("title") or ""))}</div>'
            f'<span class="resource-badge">{escape(str(item.get("badge") or "附近支持"))}</span>'
            '</div>'
            f'<div class="resource-text">{escape(str(item.get("copy") or ""))}</div>'
            '<div class="resource-support-row">'
            f'<div class="resource-avatar-strip">{avatar_html}</div>'
            f'<div class="resource-accent">{escape(str(item.get("accent") or ""))}</div>'
            '</div>'
            f'<ul class="support-example-list">{examples_html}</ul>'
            '<div class="resource-meta-list">'
            f'<div class="resource-meta-item">🕒 {escape(str(item.get("meta_time") or ""))}</div>'
            f'<div class="resource-meta-item">📍 {escape(str(item.get("meta_place") or ""))}</div>'
            f'<div class="resource-meta-item">↗ {escape(str(item.get("meta_distance") or ""))}</div>'
            '</div>'
            f'<div class="support-inline-results-shell{results_shell_class}" data-support-results-shell="{escape(item_id, quote=True)}">'
            '<div class="support-inline-results-head">'
            f'<div class="nearby-results-title">{escape(str(item.get("results_title") or "附近可去的支持点位"))}</div>'
            f'<div class="nearby-results-copy">{escape(str(item.get("results_copy") or "这里会显示这一类支持的具体点位。"))}</div>'
            '</div>'
            f'<div id="supportResults-{escape(item_id, quote=True)}" class="nearby-results-list support-inline-results-list">'
            '<div class="nearby-result-empty">切换到这个标签后，会在这里更新附近点位。</div>'
            '</div>'
            '</div>'
            '</div>'
            f'<button class="resource-action" type="button" onclick="event.stopPropagation();{action_js}">{escape(str(item.get("action") or "查看"))}</button>'
            '</div>'
        )
    map_panel_html = ""
    if has_location:
        search_term_presets = {
            "hospital": ["医院", "门诊", "诊所", "hospital", "clinic", "medical center"],
            "grocery": ["营养门诊", "生鲜超市", "超市", "dietitian", "supermarket", "grocery store"],
            "pharmacy": ["药房", "药店", "血压测量", "pharmacy", "drugstore"],
            "activity": ["公园", "步道", "康复", "park", "walking trail", "rehabilitation", "yoga"],
            "support": ["患者教育", "健康讲座", "支持小组", "support group", "health education", "community center"],
        }
        group_configs = []
        for item in items:
            item_id = str(item.get("id") or "")
            search_terms: list[str] = []
            for term in [
                str(item.get("search_keyword") or "").strip(),
                str(item.get("query") or "").strip(),
                *search_term_presets.get(item_id, []),
            ]:
                cleaned = str(term or "").strip()
                if cleaned and cleaned not in search_terms:
                    search_terms.append(cleaned)
            group_configs.append({
                "id": item_id,
                "title": str(item.get("title") or ""),
                "query": str(item.get("query") or ""),
                "search_keyword": str(item.get("search_keyword") or item.get("query") or ""),
                "search_terms": search_terms,
                "map_copy": str(item.get("map_copy") or item.get("copy") or ""),
                "emoji": str(item.get("icon") or "📍"),
                "tone": str(item.get("tone") or "lavender"),
            })
        default_id_json = json.dumps(active_group_id, ensure_ascii=False)
        map_panel_html = (
            '<div class="nearby-support-map-panel">'
            f'<p class="nearby-support-ai-copy" id="support-ai-text">{escape(str(next((item.get("map_copy") for item in items if str(item.get("id") or "") == active_group_id), items[0].get("map_copy") or "")))}</p>'
            '<div class="nearby-support-map-shell">'
            '<div id="nearbySupportMap"></div>'
            '<button id="nearby-support-locate-btn" title="回到我的位置">📍</button>'
            '</div>'
            f'<div class="nearby-results-copy" style="margin-top:12px">{escape("点下面的标签卡时，具体点位会直接展开在对应卡片里。" if has_precise_location else "页面会先尝试获取当前位置，再在页内地图中显示附近资源。")}</div>'
            '</div>'
            '<script>'
            '(function(){'
            f'var supportGroups = JSON.parse({json.dumps(json.dumps(group_configs, ensure_ascii=False))});'
            f'var defaultSupportId = {default_id_json};'
            f'var shouldTryBrowserLocation = {"false" if has_precise_location else "true"};'
            f'var userPoint = new BMap.Point({float(patient_lon)}, {float(patient_lat)});'
            'var bmap = new BMap.Map("nearbySupportMap");'
            'var activeSupportId = defaultSupportId;'
            'var supportMarkers = [];'
            'var supportRoute = null;'
            'var userOverlays = [];'
            'var supportResultsCache = {};'
            'var supportSearchState = {};'
            'bmap.enableScrollWheelZoom(true);'
            f'bmap.centerAndZoom(userPoint, {14 if has_precise_location else 12});'
            'var USER_ICON_SVG = \'<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28"><circle cx="14" cy="14" r="13" fill="#8b5cf6" fill-opacity="0.2" stroke="#8b5cf6" stroke-width="1"/><circle cx="14" cy="14" r="7" fill="#8b5cf6" stroke="#fff" stroke-width="2.5"/></svg>\';'
            'var USER_ICON = new BMap.Icon("data:image/svg+xml;charset=utf-8," + encodeURIComponent(USER_ICON_SVG), new BMap.Size(28, 28), { anchor: new BMap.Size(14, 14) });'
            'function addUserOverlays(){ userOverlays.forEach(function(o){ bmap.removeOverlay(o); }); userOverlays=[]; var marker = new BMap.Marker(userPoint,{icon:USER_ICON}); bmap.addOverlay(marker); userOverlays.push(marker); var label = new BMap.Label("您在这里",{ position:userPoint, offset:new BMap.Size(16,-8)}); label.setStyle({ background:"#8b5cf6", color:"#fff", border:"none", borderRadius:"6px", padding:"2px 8px", fontSize:"12px", fontWeight:"600", boxShadow:"0 1px 4px rgba(0,0,0,0.25)", whiteSpace:"nowrap" }); bmap.addOverlay(label); userOverlays.push(label); }'
            'function tryHydrateBrowserLocation(){ if (!shouldTryBrowserLocation || !navigator.geolocation) return; navigator.geolocation.getCurrentPosition(function(position){ userPoint = new BMap.Point(position.coords.longitude, position.coords.latitude); addUserOverlays(); bmap.centerAndZoom(userPoint, 14); supportResultsCache = {}; supportSearchState = {}; supportGroups.forEach(function(config){ renderLoading(config); ensureNearbySearch(config, config.id === activeSupportId); }); if (activeSupportId) { renderSupportMode(findGroup(activeSupportId)); } }, function(){}, { enableHighAccuracy:false, timeout:3000, maximumAge:600000 }); }'
            'function findGroup(id){ for (var i=0;i<supportGroups.length;i++){ if (supportGroups[i].id === id) return supportGroups[i]; } return supportGroups[0]; }'
            'function clearRoute(){ if (supportRoute) { supportRoute.clearResults(); supportRoute = null; } }'
            'function clearMarkers(){ clearRoute(); supportMarkers.forEach(function(m){ bmap.removeOverlay(m); }); supportMarkers = []; }'
            'function resultIcon(tone, emoji){ var toneClass = tone ? " " + tone : ""; return \'<div class="nearby-result-icon\'+toneClass+\'">\'+emoji+\'</div>\'; }'
            'function getResultContainer(id){ return document.getElementById("supportResults-"+id); }'
            'function renderLoading(config){ var container = getResultContainer(config.id); if (container) { container.innerHTML = \'<div class="nearby-result-empty">搜索中…</div>\'; } }'
            'function renderEmpty(config){ var container = getResultContainer(config.id); if (container) { container.innerHTML = \'<div class="nearby-result-empty">附近暂时没有检索到相关点位</div>\'; } }'
            'function focusMapPanel(){ var panel = document.querySelector(".nearby-support-map-panel"); if (panel) { panel.scrollIntoView({ behavior:"smooth", block:"nearest" }); } }'
            'function setActiveResultCard(groupId, idx){ var container = getResultContainer(groupId); if (!container) return; container.querySelectorAll(".nearby-result-card").forEach(function(node, nodeIdx){ if (nodeIdx === idx) { node.classList.add("active"); } else { node.classList.remove("active"); } }); }'
            'function getSearchTerms(config){ if (!config) return ["医院"]; var terms = Array.isArray(config.search_terms) ? config.search_terms.slice() : []; if (config.search_keyword) terms.unshift(config.search_keyword); if (config.query) terms.push(config.query); var uniqueTerms = []; terms.forEach(function(term){ var cleaned = String(term || "").trim(); if (cleaned && uniqueTerms.indexOf(cleaned) === -1) uniqueTerms.push(cleaned); }); return uniqueTerms.length ? uniqueTerms : ["医院"]; }'
            'function renderResultList(config, state){ var container = getResultContainer(config.id); if (!container) return; if (!state || !Array.isArray(state.items) || state.items.length === 0) { renderEmpty(config); return; } container.innerHTML = state.items.map(function(item, idx){ return \'<div class="nearby-result-card" onclick="focusCachedResult(\\\'\'+config.id+\'\\\', \'+idx+\', false)">\' + resultIcon(config.tone, item.emoji || config.emoji || "📍") + \'<div class="nearby-result-copy"><div class="nearby-result-name">\'+item.title+\'</div><div class="nearby-result-address">\'+(item.address||"暂无地址")+\'</div></div><div class="nearby-result-meta"><span class="nearby-result-distance">\'+item.distanceText+\'</span><button class="nearby-result-nav" type="button" onclick="event.stopPropagation();focusCachedResult(\\\'\'+config.id+\'\\\', \'+idx+\', true)" title="在地图查看">查看</button></div></div>\'; }).join(""); }'
            'function renderMarkersForGroup(config){ clearMarkers(); addUserOverlays(); var state = supportResultsCache[config.id]; if (!state || !Array.isArray(state.items)) return; state.items.forEach(function(item, idx){ var point = new BMap.Point(item.lng, item.lat); var marker = new BMap.Marker(point); bmap.addOverlay(marker); supportMarkers.push(marker); marker.addEventListener("click", function(){ focusCachedResult(config.id, idx, false); }); }); }'
            'window.focusCachedResult = function(groupId, idx, scrollToMap){ var config = findGroup(groupId); var state = supportResultsCache[groupId]; if (!config || !state || !state.items || !state.items[idx]) return; if (activeSupportId !== groupId) { window.switchSupportMode(groupId); } renderMarkersForGroup(config); setActiveResultCard(groupId, idx); var item = state.items[idx]; var point = new BMap.Point(item.lng, item.lat); bmap.panTo(point); if (supportMarkers[idx]) { supportMarkers[idx].openInfoWindow(new BMap.InfoWindow("<b>"+item.title+"</b><br><span style=\\"color:#888;font-size:12px\\">"+(item.address||"")+"</span>")); } clearRoute(); var routeColor = config.tone === "mint" ? "#10b981" : (config.tone === "peach" ? "#f59e0b" : (config.tone === "blue" ? "#2563eb" : "#8b5cf6")); var walking = new BMap.WalkingRoute(bmap, { renderOptions: { map:bmap, autoViewport:false }, onSearchComplete: function(results){ if (walking.getStatus() !== BMAP_STATUS_SUCCESS) return; var plan = results.getPlan(0); for (var s=0; s<plan.getNumRoutes(); s++){ var route = plan.getRoute(s); var path = route.getPolyline(); if (path){ path.setStrokeColor(routeColor); path.setStrokeWeight(5); path.setStrokeOpacity(0.85); } } addUserOverlays(); } }); walking.search(userPoint, point); supportRoute = walking; if (scrollToMap) { focusMapPanel(); } };'
            'function cacheResults(config, results){ var count = Math.min(results.getCurrentNumPois(), 9); var items = []; for (var i=0; i<count; i++){ var poi = results.getPoi(i); var dist = bmap.getDistance(userPoint, poi.point); var distText = dist >= 1000 ? (dist/1000).toFixed(1)+" km" : Math.round(dist)+" m"; items.push({ title: poi.title, address: poi.address || "暂无地址", distanceText: distText, lng: poi.point.lng, lat: poi.point.lat, emoji: config.emoji || "📍" }); } supportResultsCache[config.id] = { items: items }; return supportResultsCache[config.id]; }'
            'function renderSupportMode(config){ if (!config) return; document.getElementById("support-ai-text").textContent = config.map_copy || ""; var state = supportResultsCache[config.id]; if (!state) { renderLoading(config); ensureNearbySearch(config, true); return; } renderResultList(config, state); renderMarkersForGroup(config); }'
            'function ensureNearbySearch(config, isPriority){ if (!config || supportSearchState[config.id] === "loading" || supportResultsCache[config.id]) { if (isPriority && supportResultsCache[config.id]) { renderSupportMode(config); } return; } supportSearchState[config.id] = "loading"; if (isPriority) { renderLoading(config); } var terms = getSearchTerms(config); function searchAt(termIdx){ if (termIdx >= terms.length) { supportSearchState[config.id] = "done"; supportResultsCache[config.id] = { items: [] }; renderResultList(config, supportResultsCache[config.id]); if (activeSupportId === config.id) { renderSupportMode(config); } return; } var local = new BMap.LocalSearch(bmap, { renderOptions: { autoViewport:false }, onSearchComplete: function(results){ if (results && local.getStatus() === BMAP_STATUS_SUCCESS && results.getCurrentNumPois() > 0) { supportSearchState[config.id] = "done"; var cached = cacheResults(config, results); renderResultList(config, cached); if (activeSupportId === config.id || isPriority) { renderSupportMode(config); } return; } searchAt(termIdx + 1); } }); local.searchNearby(terms[termIdx], userPoint, 5000); } searchAt(0); }'
            'window.switchSupportMode = function(id){ activeSupportId = id; var config = findGroup(id); document.querySelectorAll("[data-support-card]").forEach(function(node){ if (node.getAttribute("data-support-card") === id) { node.classList.add("active"); } else { node.classList.remove("active"); } }); document.querySelectorAll("[data-support-results-shell]").forEach(function(node){ if (node.getAttribute("data-support-results-shell") === id) { node.classList.add("active"); } else { node.classList.remove("active"); } }); renderSupportMode(config); ensureNearbySearch(config, true); };'
            'window.activateSupportMode = function(id, scrollToMap){ window.switchSupportMode(id); if (scrollToMap) { focusMapPanel(); } };'
            'document.getElementById("nearby-support-locate-btn").addEventListener("click", function(){ if (shouldTryBrowserLocation && navigator.geolocation) { tryHydrateBrowserLocation(); } bmap.panTo(userPoint); bmap.setZoom(14); });'
            'addUserOverlays();'
            'tryHydrateBrowserLocation();'
            'supportGroups.forEach(function(config){ ensureNearbySearch(config, config.id === defaultSupportId); });'
            'window.switchSupportMode(defaultSupportId);'
            '})();'
            '</script>'
        )
    else:
        map_panel_html = (
            '<div class="nearby-support-empty-state">'
            '<div class="nearby-results-title">当前位置未开启</div>'
            '<div class="nearby-results-copy">您仍然可以先看下面的标签卡，再点按钮去地图里搜索附近医院、药房、商店或活动点。</div>'
            '</div>'
        )
    return (
        '<section class="journey-card local-resource-panel nearby-support-hub">'
        '<div class="resource-panel-head">'
        '<div>'
        '<div class="resource-panel-kicker">恢复路上，也有人和资源能帮您一把</div>'
        '<div class="journey-section-title">附近支持</div>'
        '<div class="journey-section-copy">地图和标签卡已经合并在一起。您可以按医院、药房监测、营养采购、活动康复等类型查看附近支持。</div>'
        '</div>'
        f'<div class="resource-location-pill">📍 {escape(location_label)}</div>'
        '</div>'
        f'<div class="resource-guide-row">{"".join(f"<span class=\"resource-guide-chip\">{escape(chip)}</span>" for chip in guide_chips)}</div>'
        f'<div class="support-category-grid">{"".join(cards)}</div>'
        f'{map_panel_html}'
        '</section>'
    )


def _render_shopping_list_section(payload: dict, so: dict) -> str:
    groups = _build_shopping_groups(payload, so)
    if not groups:
        return ""
    cards = []
    fresh_items: list[str] = []
    pantry_items: list[str] = []
    for group in groups:
        items = [str(item).strip() for item in (group.get("items") or []) if str(item).strip()]
        if not items:
            continue
        if "鲜食" in str(group.get("title") or ""):
            fresh_items.extend(items)
        elif "基础" in str(group.get("title") or ""):
            pantry_items.extend(items)
        hema_copy = "、".join(items)
        hema_js = escape(
            f"copyTextAndOpen({json.dumps(hema_copy, ensure_ascii=False)}, {json.dumps(_HEMA_HOME_URL, ensure_ascii=False)}, {json.dumps('已复制盒马搜索词，打开后可直接粘贴。', ensure_ascii=False)})",
            quote=True,
        )
        primary_label = str(group.get("primary_label") or "京东搜这组")
        secondary_label = str(group.get("secondary_label") or "复制到盒马")
        show_actions = group.get("actions", True) is not False
        actions_html = ""
        if show_actions:
            actions_html = (
                '<div class="shopping-actions">'
                f'<a class="shopping-btn primary" href="{escape(_jd_search_url(items), quote=True)}" target="_blank" rel="noopener noreferrer">{escape(primary_label)}</a>'
                f'<button class="shopping-btn secondary" type="button" onclick="{hema_js}">{escape(secondary_label)}</button>'
                '</div>'
            )
        cards.append(
            '<div class="shopping-card">'
            f'<div class="shopping-title">{escape(str(group.get("title") or "采购清单"))}</div>'
            f'<div class="shopping-copy">{escape(str(group.get("copy") or ""))}</div>'
            f'<div class="shopping-chip-row">{"".join(f"<span class=\"shopping-chip\">{escape(item)}</span>" for item in items[:6])}</div>'
            f'{actions_html}'
            '</div>'
        )
    if not cards:
        return ""
    fresh_unique = list(dict.fromkeys(fresh_items))
    pantry_unique = list(dict.fromkeys(pantry_items))
    fresh_copy = "、".join(fresh_unique)
    pantry_copy = "、".join(pantry_unique)
    fresh_hema_js = escape(
        f"copyTextAndOpen({json.dumps(fresh_copy, ensure_ascii=False)}, {json.dumps(_HEMA_HOME_URL, ensure_ascii=False)}, {json.dumps('已复制 3 天鲜食清单，打开后可直接粘贴。', ensure_ascii=False)})",
        quote=True,
    )
    pantry_jd_url = _jd_search_url(pantry_unique or fresh_unique)
    return (
        '<section class="journey-card">'
        '<div class="journey-section-title">按本周餐单汇总采购</div>'
        '<div class="journey-section-copy">不是按七天三餐逐顿死板下单，而是先把本周会反复用到的食材汇总成 3 天鲜食、7 天基础和可替代食材，更贴近真实使用。</div>'
        '<div class="shopping-actions shopping-actions-top">'
        f'<a class="shopping-btn primary" href="{escape(pantry_jd_url, quote=True)}" target="_blank" rel="noopener noreferrer">京东买 7 天基础</a>'
        f'<button class="shopping-btn secondary" type="button" onclick="{fresh_hema_js}">盒马补 3 天鲜食</button>'
        '</div>'
        f'<div class="shopping-grid">{"".join(cards)}</div>'
        '<div class="shopping-footnote">采购区现在是围绕本周餐食建议做“汇总购买”，不是强迫患者一次买齐 21 餐。后面如果接到更稳定的平台能力，还可以继续升级成按 3 天滚动补货。</div>'
        '</section>'
    )


def _format_time(raw: str) -> str:
    if "T" in str(raw):
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return dt.strftime("%Y年%m月%d日 %H:%M")
        except (ValueError, TypeError):
            pass
    elif isinstance(raw, str) and len(raw) >= 10 and raw[4] == "-":
        try:
            dt = datetime.strptime(raw[:16], "%Y-%m-%d %H:%M")
            return dt.strftime("%Y年%m月%d日 %H:%M")
        except ValueError:
            pass
    return str(raw)


def _extract_patient_name(payload: dict) -> str:
    patient = payload.get("patient") or {}
    if isinstance(patient, dict):
        for key in ("preferred_name", "name", "display_name"):
            value = str(patient.get(key) or "").strip()
            if value:
                return value
    return "您"


def _time_greeting(raw: str) -> str:
    try:
        if "T" in str(raw):
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(str(raw)[:16], "%Y-%m-%d %H:%M")
        hour = dt.hour
    except (TypeError, ValueError):
        hour = datetime.now().hour

    if 5 <= hour < 11:
        return "早上好"
    if 11 <= hour < 14:
        return "中午好"
    if 14 <= hour < 18:
        return "下午好"
    return "晚上好"


def _estimate_status_score(so: dict) -> int:
    base = 84 if (so.get("patient_status") or "stable") == "stable" else 76
    adh = so.get("adherence_analysis") or {}
    for key in ("medication", "appetite", "exercise", "monitoring"):
        dim = adh.get(key) or {}
        status = _localize_zh_text(str(dim.get("status") or "")).lower()
        if not status:
            continue
        if any(kw in status for kw in ("良好", "稳定", "按时", "基本稳定", "on track", "good", "consistent")):
            base += 2
        elif any(kw in status for kw in ("下降", "低于目标", "需要加强", "偏低", "below", "decreased", "needs")):
            base -= 2
    risk_count = len(so.get("risk_tags") or [])
    base -= min(risk_count, 4)
    return max(64, min(94, base))


def _score_tone(score: int) -> tuple[str, str, str]:
    if score >= 80:
        return ("稳定", "linear-gradient(135deg, #7c3aed 0%, #8b5cf6 100%)", "#6d28d9")
    if score >= 68:
        return ("需关注", "linear-gradient(135deg, #f59e0b 0%, #f97316 100%)", "#c2410c")
    return ("重点跟进", "linear-gradient(135deg, #ef4444 0%, #ec4899 100%)", "#be123c")


def _render_dashboard_metric(title: str, value: str, note: str, icon: str, accent: str) -> str:
    return (
        '<div class="dashboard-metric-card">'
        f'<div class="dashboard-metric-icon" style="color:{accent}">{icon}</div>'
        f'<div class="dashboard-metric-title">{escape(title)}</div>'
        f'<div class="dashboard-metric-value">{escape(value)}</div>'
        f'<div class="dashboard-metric-note">{escape(note)}</div>'
        '</div>'
    )


def _render_recent_adherence_scores(so: dict) -> str:
    scores = so.get("recent_adherence_scores") or []
    if not isinstance(scores, list) or not scores:
        return ""
    icon_map = {
        "medication": "💊",
        "appetite": "🥣",
        "exercise": "🚶",
    }
    badge_icon_map = {
        "good": "🌟",
        "mixed": "🌱",
        "alert": "🧭",
    }
    accent_map = {
        "good": "#10b981",
        "mixed": "#f59e0b",
        "alert": "#f43f5e",
    }
    comparison_style_map = {
        "good": ("#ecfdf5", "#a7f3d0", "#047857"),
        "mixed": ("#fffbeb", "#fde68a", "#b45309"),
        "alert": ("#fff1f2", "#fecdd3", "#be123c"),
        "neutral": ("#f8fafc", "#e2e8f0", "#475569"),
    }
    overview = _build_recent_overall_summary(scores)
    cards = []
    for item in scores[:3]:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "")
        label = _localize_zh_text(str(item.get("label") or "")).strip()
        score = item.get("score")
        previous_score = item.get("previous_score")
        target_score = item.get("target_score")
        headline = _localize_zh_text(str(item.get("headline") or "")).strip()
        next_step = _localize_zh_text(str(item.get("next_step") or "")).strip()
        band = _localize_zh_text(str(item.get("band") or "")).strip()
        status_label = _localize_zh_text(str(item.get("status_label") or "")).strip()
        delta_label = _localize_zh_text(str(item.get("delta_label") or "")).strip()
        delta_color = str(item.get("delta_color") or "#64748b")
        tone = str(item.get("tone") or "mixed")
        comparison_note = _localize_zh_text(str(item.get("comparison_note") or "")).strip()
        comparison_tone = str(item.get("comparison_tone") or "neutral")
        if not label or score in (None, ""):
            continue
        accent = accent_map.get(tone, "#64748b")
        note = " · ".join(part for part in (band, status_label) if part)
        comp_bg, comp_border, comp_text = comparison_style_map.get(comparison_tone, comparison_style_map["neutral"])
        previous_value = max(0, min(100, int(previous_score))) if previous_score not in (None, "") else None
        current_value = max(0, min(100, int(score)))
        target_value = max(0, min(100, int(target_score))) if target_score not in (None, "") else None
        rail_fill = min(100, max(previous_value or 0, current_value))
        current_marker_left = min(96, max(4, current_value))
        previous_marker_left = min(96, max(4, previous_value if previous_value is not None else current_value))
        target_marker_left = min(96, max(4, target_value if target_value is not None else current_value))
        cards.append(
            '<div class="dashboard-metric-card">'
            '<div class="score-card-top">'
            f'<div class="dashboard-metric-icon score-card-icon" style="color:{accent}">{icon_map.get(category, "🌿")}</div>'
            '<div class="score-card-main">'
            f'<div class="dashboard-metric-title">{escape(label)}</div>'
            f'<div class="dashboard-metric-value">{escape(f"{score} 分")}</div>'
            '</div>'
            f'<div class="score-card-badge" style="color:{accent};border-color:{accent}22;background:{accent}10">{badge_icon_map.get(tone, "✨")} {escape(band or "继续保持")}</div>'
            '</div>'
            f'<div class="score-delta-chip" style="color:{delta_color};background:{delta_color}12">{escape(delta_label or "继续稳稳往前走")}</div>'
            '<div class="score-rail-wrap">'
            f'<div class="score-rail-fill" style="width:{rail_fill}%"></div>'
            f'<span class="score-rail-marker previous" style="left:{previous_marker_left}%"></span>'
            f'<span class="score-rail-marker current" style="left:{current_marker_left}%;background:{accent};border-color:{accent}"></span>'
            f'<span class="score-rail-marker target" style="left:{target_marker_left}%"></span>'
            '</div>'
            '<div class="score-rail-legend">'
            f'<span>之前 {escape(str(previous_score if previous_score not in (None, "") else score))}</span>'
            f'<span>现在 {escape(str(score))}</span>'
            f'<span>下一步 {escape(str(target_score if target_score not in (None, "") else score))}</span>'
            '</div>'
            f'<div class="dashboard-metric-note">{escape(note or headline or "继续稳稳往前走")}</div>'
            + (
                f'<div class="dashboard-metric-note" style="margin-top:8px;padding:8px 10px;border-radius:14px;'
                f'background:{comp_bg};border:1px solid {comp_border};color:{comp_text};font-weight:700">'
                f'{escape(comparison_note)}</div>'
                if comparison_note
                else ""
            )
            + (f'<div class="dashboard-metric-note" style="margin-top:8px;color:#334155">{escape(headline)}</div>' if headline else "")
            + (f'<div class="dashboard-metric-note" style="margin-top:6px;color:#64748b">{escape(next_step)}</div>' if next_step else "")
            + '</div>'
        )
    if not cards:
        return ""
    overview_html = ""
    if overview:
        overview_score = max(0, min(100, int(overview.get("score") or 0)))
        overview_previous = max(0, min(100, int(overview.get("previous_score") or overview_score)))
        overview_target = max(0, min(100, int(overview.get("target_score") or overview_score)))
        overview_fill = min(100, max(overview_score, overview_previous))
        overview_current_marker = min(96, max(4, overview_score))
        overview_previous_marker = min(96, max(4, overview_previous))
        overview_target_marker = min(96, max(4, overview_target))
        overview_html = (
            '<div class="score-overview-card">'
            '<div class="score-overview-head">'
            '<div>'
            '<div class="score-overview-kicker">最近整体坚持度</div>'
            f'<div class="score-overview-value">{escape(str(overview.get("score") or ""))}<span>分</span></div>'
            '</div>'
            f'<div class="score-overview-delta" style="color:{escape(str(overview.get("delta_color") or "#64748b"))};background:{escape(str(overview.get("delta_color") or "#64748b"))}12">{escape(_localize_zh_text(str(overview.get("delta_label") or "")))}</div>'
            '</div>'
            '<div class="score-overview-rail">'
            f'<div class="score-overview-fill" style="width:{overview_fill}%"></div>'
            f'<span class="score-rail-marker previous" style="left:{overview_previous_marker}%"></span>'
            f'<span class="score-rail-marker current" style="left:{overview_current_marker}%"></span>'
            f'<span class="score-rail-marker target" style="left:{overview_target_marker}%"></span>'
            '</div>'
            '<div class="score-rail-legend">'
            f'<span>之前 {escape(str(overview.get("previous_score") or overview.get("score") or ""))}</span>'
            f'<span>现在 {escape(str(overview.get("score") or ""))}</span>'
            f'<span>下一步 {escape(str(overview.get("target_score") or overview.get("score") or ""))}</span>'
            '</div>'
            f'<div class="dashboard-progress-copy">{escape(_localize_zh_text(str(overview.get("summary") or "")))}</div>'
            f'<div class="dashboard-progress-copy" style="margin-top:4px;color:#6d28d9">{escape(_localize_zh_text(str(overview.get("coaching") or "")))}</div>'
            '</div>'
        )
    return (
        '<div class="px-3 pt-3">'
        + '<section class="dashboard-panel">'
        + '<div class="dashboard-panel-head">'
        + '<div class="dashboard-panel-title">近段时间的坚持评分</div>'
        + '<div class="dashboard-panel-copy">这不是考试分数，而是帮您看看最近营养、运动和吃药哪里已经在变好，哪里先补一步就行。</div>'
        + '</div>'
        + overview_html
        + f'<div class="dashboard-metric-grid">{"".join(cards)}</div>'
        + '<div class="dashboard-progress-card">'
        + '<div class="dashboard-progress-title">温和一点，也能慢慢变好</div>'
        + '<div class="dashboard-progress-copy">如果这次没有做到最好，也不代表退步。只要先把最关键的一小步做回来，身体就会一点点跟上。</div>'
        + '</div>'
        + '</section>'
        + '</div>'
    )


def _render_quick_nav() -> str:
    items = [
        ("🗂️", "首页", "先看总览", "homeAnchor", True),
        ("✅", "计划", "今天重点", "priorityPlanAnchor", False),
        ("📊", "数据", "最新信号", "statusAnchor", False),
        ("📈", "趋势", "恢复变化", "trendOverviewAnchor", False),
    ]
    buttons = []
    for icon, title, copy, target_id, active in items:
        buttons.append(
            f'<button class="quick-nav-btn{" active" if active else ""}" onclick="jumpToSection(\'{target_id}\')">'
            f'<div class="quick-nav-icon">{icon}</div>'
            f'<div class="quick-nav-title">{title}</div>'
            f'<div class="quick-nav-copy">{copy}</div>'
            '</button>'
        )
    return f'<div class="pt-3"><div class="quick-nav-strip">{"".join(buttons)}</div></div>'


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _format_axis_label(raw: object) -> str:
    if not raw:
        return ""
    text = str(raw)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%-m/%-d")
    except (TypeError, ValueError):
        pass
    if len(text) >= 10 and text[4] == "-":
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
            return f"{dt.month}/{dt.day}"
        except ValueError:
            pass
    return text[:10]


def _metric_delta(first: float, last: float, unit: str = "") -> tuple[str, str]:
    diff = last - first
    if abs(diff) < 0.05:
        return "较起点持平", "flat"
    direction = "up" if diff > 0 else "down"
    arrow = "↑" if diff > 0 else "↓"
    return f"较起点 {arrow} {_format_number(abs(diff))}{unit}", direction


def _fallback_trend_points_from_summary(payload: dict) -> dict:
    latest = payload.get("latest_health") or {}
    signals = payload.get("signals") or {}
    recent_text = _localize_zh_text(str(((payload.get("memory") or {}).get("recent_health_dynamics")) or ""))
    summary_text = _localize_zh_text(str(signals.get("summary_text") or ""))
    combined = f"{summary_text} {recent_text}"

    current_time_raw = str((payload.get("meta") or {}).get("current_time") or "")
    try:
        end_dt = datetime.fromisoformat(current_time_raw.replace("Z", "+00:00")) if current_time_raw else datetime.now()
    except ValueError:
        end_dt = datetime.now()
    labels = [(end_dt - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(6, -1, -1)]

    def linear_series(start: float, end: float) -> list[float]:
        if len(labels) == 1:
            return [round(end, 1)]
        return [round(start + (end - start) * idx / (len(labels) - 1), 1) for idx in range(len(labels))]

    bp_text = str(latest.get("blood_pressure") or "")
    bp_match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", bp_text)
    sbp = float(bp_match.group(1)) if bp_match else 138.0
    dbp = float(bp_match.group(2)) if bp_match else 85.0
    hr = float(latest.get("heart_rate") or 74)
    spo2 = float(latest.get("blood_oxygen") or 97)
    glucose = float(latest.get("blood_glucose") or 7.2)
    steps = float(latest.get("steps") or latest.get("steps_today") or 1500)

    steps_start = 4000.0 if ("4000" in combined or "4,000" in combined) else max(steps + 1200, 2800.0)
    glucose_start = 7.4 if ("7.0-7.4" in combined or "7.4" in combined) else max(glucose + 0.3, 7.0)
    hr_start = hr + 4 if ("tired" in combined.lower() or "疲劳" in combined) else hr + 2
    spo2_start = 96.0 if ("96-98" in combined or "96" in combined) else max(spo2 - 1, 95.0)

    return {
        "week": {
            "granularity": "day",
            "metrics": {
                "blood_pressure": [
                    {"t": label, "sbp": round(sbp + drift, 0), "dbp": round(dbp + drift * 0.4, 0)}
                    for label, drift in zip(labels, [1, 1, 0, 0, 0, -1, 0])
                ],
                "heart_rate": [{"t": label, "value": value} for label, value in zip(labels, linear_series(hr_start, hr))],
                "blood_oxygen": [{"t": label, "value": value} for label, value in zip(labels, linear_series(spo2_start, spo2))],
                "steps_today": [{"t": label, "value": value} for label, value in zip(labels, linear_series(steps_start, steps))],
                "blood_glucose": [{"t": label, "value": value} for label, value in zip(labels, linear_series(glucose_start, glucose))],
            },
        }
    }


def _build_trend_data(payload: dict) -> dict:
    signal_trends = payload.get("signal_trends") or {}
    if not isinstance(signal_trends, dict):
        signal_trends = {}
    if not signal_trends:
        signal_trends = _fallback_trend_points_from_summary(payload)

    window_labels = {
        "week": "最近一周",
        "month": "最近一月",
        "quarter": "最近一季度",
    }
    metric_meta = {
        "blood_pressure": ("🩺", "血压", "mmHg", "#7c3aed", "曲线显示收缩压，点按可查看完整血压。"),
        "heart_rate": ("🫀", "心率", "bpm", "#ef4444", "观察近期心率变化。"),
        "blood_oxygen": ("🫁", "血氧", "%", "#06b6d4", "观察近期血氧变化。"),
        "steps_today": ("👟", "步数", "步", "#2563eb", "观察近期活动量变化。"),
        "steps": ("👟", "步数", "步", "#2563eb", "观察近期活动量变化。"),
        "blood_glucose": ("🧪", "血糖", "mmol/L", "#f59e0b", "观察近期血糖变化。"),
    }

    trend_data: dict[str, dict] = {}
    for window_key in ("week", "month", "quarter"):
        window = signal_trends.get(window_key) or {}
        metrics = window.get("metrics") or {}
        if not isinstance(metrics, dict):
            continue

        metric_cards = []
        for metric_key in ("blood_pressure", "heart_rate", "blood_oxygen", "steps_today", "steps", "blood_glucose"):
            points = metrics.get(metric_key) or []
            if not isinstance(points, list):
                continue
            clean_points = [point for point in points if isinstance(point, dict)]
            if not clean_points:
                continue

            icon, label, unit, color, copy = metric_meta[metric_key]
            if metric_key == "blood_pressure":
                usable = [
                    point for point in clean_points
                    if point.get("sbp") not in (None, "") and point.get("dbp") not in (None, "")
                ]
                if not usable:
                    continue
                first, last = usable[0], usable[-1]
                values = [float(point["sbp"]) for point in usable]
                value_text = f'{_format_number(float(last["sbp"]))}/{_format_number(float(last["dbp"]))} {unit}'
                delta, delta_direction = _metric_delta(float(first["sbp"]), float(last["sbp"]), "")
                point_cards = [
                    {
                        "label": _format_axis_label(point.get("t")),
                        "display": f'{_format_number(float(point["sbp"]))}/{_format_number(float(point["dbp"]))} {unit}',
                        "value": _format_number(float(point["sbp"])),
                    }
                    for point in usable
                ]
            else:
                usable = [point for point in clean_points if point.get("value") not in (None, "")]
                if not usable:
                    continue
                first, last = usable[0], usable[-1]
                values = [float(point["value"]) for point in usable]
                value_text = f'{_format_number(values[-1])} {unit}'
                delta, delta_direction = _metric_delta(values[0], values[-1], unit)
                point_cards = [
                    {
                        "label": _format_axis_label(point.get("t")),
                        "display": f'{_format_number(float(point["value"]))} {unit}',
                        "value": _format_number(float(point["value"])),
                    }
                    for point in usable
                ]

            metric_cards.append({
                "icon": icon,
                "label": label,
                "value": value_text,
                "delta": delta,
                "delta_direction": delta_direction,
                "copy": copy,
                "values": values,
                "color": color,
                "points": point_cards,
            })

        if metric_cards:
            all_points = [
                point
                for points in metrics.values()
                if isinstance(points, list)
                for point in points
                if isinstance(point, dict)
            ]
            labels = [_format_axis_label(point.get("t")) for point in all_points if point.get("t")]
            aggregate_label = "每周平均" if window.get("granularity") == "week" else "每日平均"
            trend_data[window_key] = {
                "axis_start": labels[0] if labels else "",
                "axis_end": labels[-1] if labels else "",
                "insight": f"{window_labels[window_key]} · {aggregate_label}",
                "metrics": metric_cards,
            }
    return trend_data


def _render_trend_story(trend_data: dict) -> str:
    if not trend_data:
        return ""
    label_map = {"week": "周", "month": "月", "quarter": "季度"}
    default_key = next(iter(trend_data))
    buttons = "".join(
        f'<button class="trend-range-btn{" active" if key == default_key else ""}" data-range="{key}" onclick="renderTrendRange(\'{key}\')">{label_map.get(key, key)}</button>'
        for key in ("week", "month", "quarter")
        if key in trend_data
    )
    return (
        '<div id="trendOverviewAnchor" class="px-3 pt-3">'
        '<section class="trend-card">'
        '<div class="trend-card-head">'
        '<div>'
        '<div class="trend-card-title">信号趋势</div>'
        '<div class="trend-card-copy" data-copy-key="trend_story_desc">滑动曲线，查看每天或每周的平均记录。</div>'
        '</div>'
        f'<div class="trend-insight-chip" id="trendInsightChip">{escape(trend_data[default_key].get("insight") or "")}</div>'
        '</div>'
        '<div class="trend-range-tabs">'
        f'{buttons}'
        '</div>'
        '<div id="trendMetricStack" class="trend-metric-stack mt-3"></div>'
        '</section>'
        '</div>'
    )


def _journey_page(page_key: str, title: str, subtitle: str, body: str, active: bool = False) -> str:
    if not body or not body.strip():
        body = (
            '<section class="journey-card">'
            '<div class="journey-section-title">暂无内容</div>'
            '<div class="journey-section-copy">有新的记录后，这里会自动更新。</div>'
            '</section>'
        )
    active_class = " active" if active else ""
    subtitle_key = {
        "home": "home_subtitle",
        "plan": "plan_subtitle",
        "nutrition": "nutrition_subtitle",
        "trends": "trend_subtitle",
        "why": "why_subtitle",
    }.get(page_key, "")
    subtitle_attr = f' data-copy-key="{escape(subtitle_key, quote=True)}"' if subtitle_key else ""
    return (
        f'<main class="journey-page{active_class}" data-page="{escape(page_key, quote=True)}">'
        '<div class="journey-screen-head">'
        '<div>'
        f'<div class="journey-screen-title">{escape(title)}</div>'
        f'<div class="journey-screen-copy"{subtitle_attr}>{escape(subtitle)}</div>'
        '</div>'
        '</div>'
        f'{body}'
        '</main>'
    )


def _adherence_tone(status: str) -> str:
    value = _localize_zh_text(status or "").lower()
    if any(kw in value for kw in ("良好", "稳定", "按时", "已完成", "完成", "good", "consistent", "on track")):
        return "good"
    if any(kw in value for kw in ("部分", "partial", "偶尔", "待观察")):
        return "warn"
    return "alert" if value else "warn"


def _adherence_brief(key: str, dim: dict) -> str:
    preferred_keys = {
        "medication": ("issues", "adjustments", "barriers", "note"),
        "appetite": ("issues", "recommendations", "barriers", "note"),
        "exercise": ("barriers", "plan", "issues", "note"),
        "monitoring": ("gaps", "issues", "plan", "note"),
    }
    for detail_key in preferred_keys.get(key, ()):
        text = _stringify_compact(dim.get(detail_key))
        if text:
            return text
    status = _localize_zh_text(str(dim.get("status") or "")).strip()
    return status or "本次没有更多说明"


def _adherence_chip_label(key: str, dim: dict) -> str:
    text = _adherence_brief(key, dim)
    status = _localize_zh_text(str(dim.get("status") or ""))
    if key == "medication":
        if "漏服" in text:
            return "用药漏服"
        return "用药" + (status or "待观察")
    if key == "appetite":
        if any(word in text for word in ("盐", "油", "火锅", "冒菜")):
            return "饮食油盐偏高"
        return "饮食" + (status or "待观察")
    if key == "exercise":
        return "活动未完成" if _adherence_tone(status) != "good" else "活动已完成"
    if key == "monitoring":
        return "监测缺口" if _adherence_tone(status) != "good" else "监测已完成"
    return status or "待观察"


def _render_journey_status(so: dict) -> tuple[str, str, str]:
    adh = so.get("adherence_analysis") or {}
    dims = []
    for key, icon, title in _ADHERENCE_DIMENSIONS:
        dim = adh.get(key)
        if isinstance(dim, dict) and (dim.get("status") or _adherence_brief(key, dim)):
            status = _localize_zh_text(str(dim.get("status") or "待观察"))
            tone = _adherence_tone(status)
            dims.append((key, icon, title, dim, status, tone))

    if not dims:
        return "", "待观察", "这次遵从回访没有提供结构化状态。"

    tones = [item[-1] for item in dims]
    if "alert" in tones:
        overall = "需关注"
    elif "warn" in tones:
        overall = "部分完成"
    else:
        overall = "整体稳定"

    chips = []
    for key, _icon, _title, dim, _status, tone in dims:
        chips.append(
            f'<span class="status-alert-chip {tone}">● {escape(_adherence_chip_label(key, dim))}</span>'
        )

    cards = []
    for key, icon, title, dim, status, tone in dims:
        cards.append(
            f'<div class="execution-card {tone}">'
            '<div class="execution-card-top">'
            f'<span class="execution-icon">{icon}</span>'
            f'<span class="execution-status">{escape(status)}</span>'
            '</div>'
            f'<div class="execution-title">{escape(title)}</div>'
            f'<div class="execution-detail">{escape(_adherence_brief(key, dim))}</div>'
            '</div>'
        )

    body = (
        '<section class="journey-card">'
        '<div class="journey-section-kicker">今日整体状态</div>'
        f'<div class="journey-section-title">{escape(overall)}</div>'
        f'<div class="status-alert-row">{"".join(chips)}</div>'
        '</section>'
        '<section class="journey-card">'
        '<div class="journey-section-title">关键执行概览</div>'
        f'<div class="journey-status-grid">{"".join(cards)}</div>'
        '</section>'
    )
    return body, overall, "、".join(_adherence_chip_label(key, dim) for key, _i, _t, dim, _s, _tone in dims[:3])


def _render_journey_vitals(summary: dict) -> str:
    if not summary:
        return ""
    metric_defs = [
        ("blood_pressure", "血压", "mmHg", "💜"),
        ("heart_rate", "心率", "次/分", "❤️"),
        ("blood_oxygen", "血氧", "%", "💧"),
        ("steps_today", "步数", "步", "👟"),
        ("blood_glucose", "血糖", "mmol/L", "🧪"),
    ]
    cards = []
    for key, label, unit, icon in metric_defs:
        value = summary.get(key)
        if value in (None, ""):
            continue
        cards.append(
            '<div class="signal-mini-card">'
            f'<div class="signal-mini-icon">{icon}</div>'
            f'<div class="signal-mini-label">{escape(label)}</div>'
            f'<div class="signal-mini-value">{escape(str(value))}</div>'
            f'<div class="signal-mini-unit">{escape(unit)}</div>'
            '</div>'
        )
    if not cards:
        return ""
    return (
        '<section class="journey-card">'
        '<div class="journey-section-title">最新生命体征</div>'
        f'<div class="signal-mini-grid">{"".join(cards)}</div>'
        '</section>'
    )


def _pick_primary_highlight(so: dict) -> dict | None:
    highlights = so.get("longitudinal_highlights") or []
    if not isinstance(highlights, list):
        return None
    normalized = [item for item in highlights if isinstance(item, dict) and str(item.get("summary") or "").strip()]
    if not normalized:
        return None
    for item in normalized:
        title = _localize_zh_text(str(item.get("title") or ""))
        if any(token in title for token in ("关键", "补上", "留意")):
            return item
    return normalized[0]


def _build_fallback_insight_item(so: dict, payload: dict) -> dict | None:
    current_items = _collect_current_adherence_items(payload, so)
    recent_clues = _extract_recent_clues(payload.get("memory") or {})
    if not current_items:
        return None

    category_labels = {
        "medication": "用药",
        "appetite": "营养",
        "exercise": "活动",
        "monitoring": "监测",
    }
    priority_order = ("monitoring", "appetite", "medication", "exercise")
    ranked: list[tuple[int, str, dict]] = []
    for category in priority_order:
        item = current_items.get(category)
        if not isinstance(item, dict):
            continue
        bucket = _status_bucket(item.get("status") or item.get("status_label"))
        if bucket == "needs_attention":
            priority = 0
        elif bucket == "mixed":
            priority = 1
        elif bucket == "good":
            priority = 2
        else:
            priority = 3
        if recent_clues.get(category):
            priority -= 1
        ranked.append((priority, category, item))

    if not ranked:
        return None

    _priority, category, item = sorted(ranked, key=lambda x: x[0])[0]
    label = category_labels.get(category, "这一步")
    bucket = _status_bucket(item.get("status") or item.get("status_label"))
    title, status_copy = _status_category_text(bucket)
    current_fact = _localize_zh_text(str(item.get("text") or "")).strip()
    recent_fact = _localize_zh_text(str(recent_clues.get(category) or "")).strip()

    summary_parts = []
    if bucket == "good":
        summary_parts.append(f"这次回访里，{label}这一步做得不错。")
    elif bucket == "mixed":
        summary_parts.append(f"这次回访里，{label}这一步已经有基础，还可以再稳一点。")
    elif bucket == "needs_attention":
        summary_parts.append(f"这次回访里，{label}这一步值得优先补上。")
    else:
        summary_parts.append(f"这次回访里，{label}这一步可以继续观察。")
    if current_fact:
        summary_parts.append(current_fact)
    if recent_fact and bucket == "good":
        summary_parts.append("和近期记录放在一起看，说明这件事值得继续坚持。")
    elif recent_fact and bucket in {"mixed", "needs_attention"}:
        summary_parts.append("和近期记录放在一起看，这一项仍然值得继续盯紧。")
    summary_parts.append(status_copy)

    evidence_bits = []
    if item.get("date"):
        evidence_bits.append(f"本次记录日期：{item['date']}")
    if current_fact:
        evidence_bits.append(f"本次事实：{current_fact}")
    if recent_fact:
        evidence_bits.append("近期线索：来自 memory.recent 的候选行为变化")

    source = "objective_plus_recent" if recent_fact else "objective"
    return {
        "category": category,
        "title": f"{label}：{title}",
        "summary": " ".join(part for part in summary_parts if part),
        "evidence": "；".join(evidence_bits),
        "source": source,
    }


def _render_journey_insight_spotlight(so: dict, payload: dict) -> str:
    item = _pick_primary_highlight(so) or _build_fallback_insight_item(so, payload)
    if not item:
        return ""

    icon_map = {
        "medication": "💊",
        "appetite": "🥣",
        "exercise": "🚶",
        "monitoring": "🩺",
    }
    category = str(item.get("category") or "")
    title = _localize_zh_text(str(item.get("title") or "我发现了您的一个规律")).strip()
    summary = _localize_zh_text(str(item.get("summary") or "")).strip()
    evidence = _localize_zh_text(str(item.get("evidence") or "")).strip()
    if not summary:
        return ""

    source = str(item.get("source") or "")
    badge = "本次回访 + 近期线索" if source == "objective_plus_recent" else "本次回访事实"
    support_note = _build_supportive_note(so, payload)

    return (
        '<section class="journey-card insight-spotlight">'
        '<div class="insight-spotlight-main">'
        '<div class="insight-spotlight-copy">'
        '<div class="insight-eyebrow">专属洞察</div>'
        '<div class="journey-section-title">我发现了一个值得留意的变化</div>'
        f'<div class="insight-title-row"><span class="insight-emoji">{icon_map.get(category, "✨")}</span><span class="insight-headline">{escape(title)}</span></div>'
        f'<div class="insight-summary">{escape(summary)}</div>'
        f'<div class="insight-badge">{escape(badge)}</div>'
        + (
            f'<div class="insight-evidence">{escape(evidence)}</div>'
            if evidence else ""
        )
        + (
            f'<div class="insight-memory-pill">我记得并在帮您留意：{escape(support_note)}</div>'
            if support_note else ""
        )
        + '</div>'
        f'<div class="insight-visual"><img class="insight-visual-img" src="{_INSIGHT_VISUAL_ASSET}" alt="" loading="lazy" decoding="async"></div>'
        '</div>'
        '</section>'
    )


def _render_treatment_theme_banner(theme: dict) -> str:
    if not isinstance(theme, dict) or not theme:
        return ""
    title = _localize_zh_text(str(theme.get("title") or "")).strip()
    summary = _localize_zh_text(str(theme.get("summary") or "")).strip()
    if not title:
        return ""

    eyebrow = _localize_zh_text(str(theme.get("eyebrow") or "治疗主题")).strip()
    badge = _localize_zh_text(str(theme.get("badge") or "")).strip()
    cycle_badge = _localize_zh_text(str(theme.get("cycle_badge") or "")).strip()
    stage_label = _localize_zh_text(str(theme.get("stage_label") or "当前阶段")).strip()
    stage_value = _localize_zh_text(str(theme.get("stage_value") or "")).strip()
    gradient = str(theme.get("gradient") or "linear-gradient(135deg, #475569 0%, #64748b 55%, #cbd5e1 100%)")
    accent = str(theme.get("accent") or "#e2e8f0")
    icon = _localize_zh_text(str(theme.get("icon") or "✨")).strip() or "✨"
    art = _localize_zh_text(str(theme.get("art") or "💉")).strip() or "💉"
    med_tags = [str(item).strip() for item in (theme.get("medication_tags") or []) if str(item).strip()]
    focus_points = [str(item).strip() for item in (theme.get("focus_points") or []) if str(item).strip()]

    tag_html = "".join(
        f'<span style="display:inline-flex;align-items:center;padding:6px 10px;border-radius:999px;'
        f'background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.22);'
        f'font-size:12px;font-weight:700;color:#fff">{escape(tag)}</span>'
        for tag in med_tags[:4]
    )
    points_html = "".join(
        '<div style="display:flex;gap:10px;align-items:flex-start;margin-top:10px">'
        f'<span style="display:inline-flex;width:20px;height:20px;border-radius:999px;background:rgba(255,255,255,.18);'
        f'align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff">{idx}</span>'
        f'<div style="font-size:13px;line-height:1.6;color:rgba(255,255,255,.92)">{escape(point)}</div>'
        '</div>'
        for idx, point in enumerate(focus_points[:3], start=1)
    )

    stage_html = (
        '<div style="margin-top:14px;padding:12px 14px;border-radius:18px;'
        'background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.16)">'
        f'<div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:rgba(255,255,255,.74);font-weight:800">{escape(stage_label)}</div>'
        f'<div style="margin-top:4px;font-size:15px;line-height:1.5;font-weight:800;color:#fff">{escape(stage_value)}</div>'
        '</div>'
    ) if stage_value else ""
    left_column = (
        '<div style="flex:1;min-width:0">'
        '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
        f'<div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:rgba(255,255,255,.76);font-weight:800">{escape(eyebrow)}</div>'
        + (
            f'<div style="padding:5px 10px;border-radius:999px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.18);font-size:11px;font-weight:800;color:#fff">{escape(cycle_badge)}</div>'
            if cycle_badge else ""
        )
        + '</div>'
        f'<div style="margin-top:8px;display:flex;align-items:center;gap:10px"><span style="font-size:20px">{escape(icon)}</span>'
        f'<div style="margin-top:8px;font-size:28px;line-height:1.18;font-weight:900;color:#fff">{escape(title)}</div>'
        '</div>'
        f'<div style="margin-top:10px;font-size:14px;line-height:1.7;color:rgba(255,255,255,.9)">{escape(summary)}</div>'
        f'{stage_html}'
        + (
            f'<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:14px">{tag_html}</div>'
            if tag_html else ""
        )
        + (
            f'<div style="margin-top:14px;padding:14px 16px;border-radius:20px;background:rgba(11,18,32,.14);'
            f'backdrop-filter:blur(6px);border:1px solid rgba(255,255,255,.12)">{points_html}</div>'
            if points_html else ""
        )
        + '</div>'
    )
    badge_html = (
        f'<div style="padding:8px 12px;border-radius:999px;background:{escape(accent, quote=True)};'
        'color:#312e81;font-weight:800;font-size:12px;box-shadow:inset 0 0 0 1px rgba(255,255,255,.18)">'
        f'{escape(badge)}</div>'
    ) if badge else ""
    right_column = (
        '<div style="flex:0 0 108px;display:flex;flex-direction:column;align-items:flex-end;gap:12px">'
        f'{badge_html}'
        '<div style="width:94px;height:94px;border-radius:28px;background:rgba(255,255,255,.14);'
        'display:flex;align-items:center;justify-content:center;border:1px solid rgba(255,255,255,.14);'
        f'font-size:44px;color:#fff">{escape(art)}</div>'
        '</div>'
    )
    return (
        '<section class="journey-card" '
        f'style="background:{escape(gradient, quote=True)};border:none;box-shadow:0 16px 34px rgba(79,70,229,.18);overflow:hidden">'
        '<div style="display:flex;justify-content:space-between;gap:18px;align-items:flex-start">'
        f'{left_column}{right_column}'
        '</div>'
        '</section>'
    )


def _render_treatment_theme_detail(theme: dict) -> str:
    if not isinstance(theme, dict) or not theme:
        return ""
    title = _localize_zh_text(str(theme.get("title") or "")).strip()
    summary = _localize_zh_text(str(theme.get("summary") or "")).strip()
    cycle_badge = _localize_zh_text(str(theme.get("cycle_badge") or "")).strip()
    stage_value = _localize_zh_text(str(theme.get("stage_value") or "")).strip()
    evidence = [str(item).strip() for item in (theme.get("evidence") or []) if str(item).strip()]
    focus_points = [str(item).strip() for item in (theme.get("focus_points") or []) if str(item).strip()]
    if not (title or summary or stage_value or evidence or focus_points):
        return ""

    body_parts = []
    if summary:
        body_parts.append(f'<div class="text-sm text-slate-700 leading-relaxed">{escape(summary)}</div>')
    if stage_value:
        body_parts.append(
            '<div class="mt-3 text-xs text-indigo-700 bg-indigo-50 border border-indigo-100 rounded-xl px-3 py-2 leading-relaxed">'
            f'当前阶段：{escape(stage_value)}</div>'
        )
    if cycle_badge:
        body_parts.append(
            '<div class="mt-2 text-xs text-slate-600">'
            f'阶段标签：<span class="inline-flex items-center rounded-full border border-slate-200 bg-white px-2.5 py-1 font-semibold text-slate-700">{escape(cycle_badge)}</span>'
            '</div>'
        )
    if focus_points:
        focus_html = "".join(
            '<div class="text-xs text-slate-600 leading-relaxed flex items-start gap-2 mt-2">'
            '<span style="color:#6366f1">●</span>'
            f'<span>{escape(point)}</span>'
            '</div>'
            for point in focus_points[:3]
        )
        body_parts.append(f'<div class="mt-3">{focus_html}</div>')
    if evidence:
        evidence_html = "".join(
            f'<div class="text-xs text-slate-500 leading-relaxed mt-2">{escape(item)}</div>'
            for item in evidence[:3]
        )
        body_parts.append(
            '<div class="mt-3 rounded-xl bg-slate-50 border border-slate-200 px-3 py-3">'
            '<div class="text-[11px] uppercase tracking-wide text-slate-400 font-bold">客观依据</div>'
            f'{evidence_html}'
            '</div>'
        )

    return (
        '<div class="sub-card sub-card-static">'
        '<div class="sub-card-header">'
        '<span class="sub-card-icon">💉</span>'
        '<div class="flex-1 min-w-0">'
        '<div class="sub-card-label">当前治疗主题</div>'
        f'<div class="sub-card-value">{escape(title or "当前治疗重点")}</div>'
        '</div>'
        '</div>'
        f'<div class="sub-card-body">{"".join(body_parts)}</div>'
        '</div>'
    )


def _render_treatment_education_card(theme: dict) -> str:
    if not isinstance(theme, dict) or not theme:
        return ""
    education = theme.get("education") or {}
    if not isinstance(education, dict):
        return ""
    title = _localize_zh_text(str(education.get("title") or "")).strip()
    body = _localize_zh_text(str(education.get("body") or "")).strip()
    tip = _localize_zh_text(str(education.get("tip") or "")).strip()
    icon = _localize_zh_text(str(education.get("icon") or "✨")).strip() or "✨"
    page_badge = _localize_zh_text(str(education.get("page_badge") or "1/1")).strip() or "1/1"
    medication_line = _localize_zh_text(str(education.get("medication_line") or "")).strip()
    feedback_item_name = _localize_zh_text(str(education.get("feedback_item_name") or title or "æ²»ç–—æ•™è‚²")).strip()
    feedback_prompt = _localize_zh_text(str(education.get("feedback_prompt") or "")).strip()
    feedback_item_name = _localize_zh_text(str(education.get("feedback_item_name") or title or "\u6cbb\u7597\u6559\u80b2")).strip()
    positive_label = _localize_zh_text(str(education.get("feedback_positive_label") or "\u6709\u5e2e\u52a9")).strip() or "\u6709\u5e2e\u52a9"
    positive_active_label = _localize_zh_text(str(education.get("feedback_positive_active_label") or "\u5df2\u8bb0\u4e0b")).strip() or "\u5df2\u8bb0\u4e0b"
    negative_label = _localize_zh_text(str(education.get("feedback_negative_label") or "\u4e0d\u6e05\u695a")).strip() or "\u4e0d\u6e05\u695a"
    negative_active_label = _localize_zh_text(str(education.get("feedback_negative_active_label") or "\u5df2\u8bb0\u4e0b")).strip() or "\u5df2\u8bb0\u4e0b"
    positive_label = _localize_zh_text(str(education.get("feedback_positive_label") or "æœ‰å¸®åŠ©")).strip() or "æœ‰å¸®åŠ©"
    positive_active_label = _localize_zh_text(str(education.get("feedback_positive_active_label") or "å·²è®°ä¸‹")).strip() or "å·²è®°ä¸‹"
    negative_label = _localize_zh_text(str(education.get("feedback_negative_label") or "ä¸æ¸…æ¥š")).strip() or "ä¸æ¸…æ¥š"
    negative_active_label = _localize_zh_text(str(education.get("feedback_negative_active_label") or "å·²è®°ä¸‹")).strip() or "å·²è®°ä¸‹"
    visual_asset = str(education.get("visual_asset") or _SUPPORT_PERSON_ASSET).strip() or _SUPPORT_PERSON_ASSET
    visual_label = _localize_zh_text(str(education.get("visual_label") or "治疗教育")).strip() or "治疗教育"
    if not (title or body or tip or medication_line):
        return ""
    return (
        '<section class="journey-card treatment-education-card">'
        '<div class="treatment-education-head">'
        '<div>'
        f'<div class="journey-section-kicker">{escape(visual_label)}</div>'
        f'<div class="journey-section-title">{escape(title)}</div>'
        '</div>'
        f'<div class="treatment-education-page">{escape(page_badge)}</div>'
        '</div>'
        '<div class="treatment-education-hero">'
        '<div class="treatment-education-copy">'
        + (
            f'<div class="treatment-education-theme-line">{escape(medication_line)}</div>'
            if medication_line else ""
        )
        + (
            f'<div class="treatment-education-body">{escape(body)}</div>'
            if body else ""
        )
        + (
            '<div class="treatment-education-tip-box">'
            f'<div class="treatment-education-tip-icon">{escape(icon)}</div>'
            '<div>'
            '<div class="treatment-education-tip-label">小贴士</div>'
            f'<div class="treatment-education-tip-text">{escape(tip)}</div>'
            '</div>'
            '</div>'
            if tip else ""
        )
        + (
            '<div class="treatment-education-feedback">'
            f'<div class="treatment-education-feedback-copy">{escape(feedback_prompt)}</div>'
            '<div class="treatment-education-feedback-actions feedback-actions">'
            f'<button class="feedback-btn like" type="button" data-day-idx="-1" data-meal-type="education" data-item-name="{escape(feedback_item_name, quote=True)}" data-default-label="{escape(positive_label, quote=True)}" data-active-label="{escape(positive_active_label, quote=True)}" onclick="saveLikeFromButton(this)">{escape(positive_label)}</button>'
            f'<button class="feedback-btn feedback-skip" type="button" data-day-idx="-1" data-meal-type="education" data-item-name="{escape(feedback_item_name, quote=True)}" data-default-label="{escape(negative_label, quote=True)}" data-active-label="{escape(negative_active_label, quote=True)}" onclick="showFeedbackModalFromButton(this)">{escape(negative_label)}</button>'
            '</div>'
            '</div>'
            if feedback_prompt else ""
        )
        + '</div>'
        '<div class="treatment-education-visual">'
        f'<img class="treatment-education-visual-img" src="{escape(visual_asset, quote=True)}" alt="" loading="lazy" decoding="async">'
        f'<div class="treatment-education-visual-badge">{escape(icon)}</div>'
        '</div>'
        '</div>'
        '</section>'
    )


def _render_journey_home(so: dict, payload: dict, memory: dict, current_time_raw: str, profile_copy: dict | None = None) -> str:
    name = _extract_patient_name(payload)
    greeting = _time_greeting(current_time_raw)
    avatar = escape(name[:1] if name and name != "您" else "您")
    status_html, _overall, _status_copy = _render_journey_status(so)
    latest = so.get("latest_health_summary") or {}
    vitals_html = _render_journey_vitals(latest)
    summary = _build_supportive_note(so, payload)
    profile_copy = profile_copy or {}
    hero_tagline = _localize_zh_text(str(profile_copy.get("hero_tagline") or "今天先看状态，再做最关键的几步。")).strip()
    conditions = so.get("conditions") or []
    condition_html = ""
    if conditions:
        condition_html = (
            '<div class="flex gap-1.5 mt-3 flex-wrap">'
            + "".join(
                f'<span class="context-chip">{escape(_localize_zh_text(str(item)))}</span>'
                for item in conditions[:4]
            )
            + '</div>'
        )
    hero = (
        '<section class="journey-card journey-hero">'
        '<div class="journey-hero-main">'
        '<div class="journey-hero-row">'
        f'<div class="journey-avatar"><img class="journey-avatar-img" src="{_PATIENT_HEAD_ASSET}" alt="" loading="lazy" decoding="async"><span class="journey-avatar-fallback">{avatar}</span></div>'
        '<div>'
        f'<div class="journey-hello">{escape(greeting)}，{escape(name)}</div>'
        f'<div class="journey-hero-text" data-copy-key="hero_tagline">{escape(hero_tagline)}</div>'
        '</div>'
        '</div>'
        f'<div class="journey-hero-text">{escape(summary)}</div>'
        f'{condition_html}'
        '</div>'
        f'<div class="journey-hero-visual"><img class="journey-hero-illustration" src="{_HERO_COMPANION_ASSET}" alt="" loading="lazy" decoding="async"></div>'
        '</section>'
    )
    treatment_theme_html = _render_treatment_theme_banner(so.get("treatment_theme") or {})
    insight_html = _render_journey_insight_spotlight(so, payload)
    recent_scores_html = _render_recent_adherence_scores(so)
    longitudinal_recap_html = _render_home_longitudinal_recap(so, payload)
    return hero + treatment_theme_html + insight_html + recent_scores_html + longitudinal_recap_html + status_html + vitals_html


def _render_journey_tasks(so: dict, payload: dict, profile_copy: dict | None = None) -> str:
    recs = so.get("recommendations") or []
    if not isinstance(recs, list) or not recs:
        return ""
    profile_copy = profile_copy or {}
    visual_cycle = ["💊", "🥣", "🚶", "📋", "🌙", "🥗"]
    category_map = {
        "medication": "用药",
        "diet": "营养",
        "exercise": "活动",
        "monitoring": "监测",
        "lifestyle": "日常",
    }
    cards = []
    for idx, rec in enumerate(recs[:3], start=1):
        if isinstance(rec, dict):
            text = _clean_recommendation_text(rec.get("text") or "")
            reason = _localize_zh_text(str(rec.get("reason") or "")).strip()
            category = category_map.get(str(rec.get("category") or "").strip(), "重点")
        else:
            text = _clean_recommendation_text(rec)
            reason = ""
            category = "重点"
        if not text:
            continue
        safe_text = escape(text, quote=True).replace("'", "&#39;")
        cards.append(
            '<div class="journey-task">'
            f'<div class="journey-task-index">{idx}</div>'
            '<div>'
            f'<div class="journey-task-chip-row"><span class="journey-task-chip">{escape(category)}</span><span class="journey-task-arrow">›</span></div>'
            f'<div class="journey-task-title">{escape(text)}</div>'
            + (f'<div class="journey-task-reason">原因：{escape(reason)}</div>' if reason else "")
            + '<div class="journey-task-actions feedback-actions">'
            + f'<button class="feedback-btn like" data-day-idx="-1" data-meal-type="priority" '
            f'data-item-name="{safe_text}" data-default-label="采纳" data-active-label="已采纳" '
            f'onclick="saveLikeFromButton(this)">采纳</button>'
            + f'<button class="feedback-btn feedback-skip" data-day-idx="-1" data-meal-type="priority" '
            f'data-item-name="{safe_text}" data-default-label="不采纳" data-active-label="已不采纳" '
            f'onclick="showFeedbackModalFromButton(this)">不采纳</button>'
            + '</div>'
            '</div>'
            f'<div class="journey-task-visual">{visual_cycle[(idx - 1) % len(visual_cycle)]}</div>'
            '</div>'
        )
    if not cards:
        return ""
    note = _build_supportive_note(so, payload)
    return (
        '<section class="journey-card">'
        '<div class="journey-section-title">今天最值得做的三件事</div>'
        f'<div class="journey-section-copy" data-copy-key="plan_focus_desc">{escape(_localize_zh_text(str(profile_copy.get("plan_focus_desc") or "聚焦关键行动，改善今天的健康状态。")))}</div>'
        f'<div class="mt-3">{"".join(cards)}</div>'
        f'<div class="assistant-note"><div class="assistant-note-photo"><img class="assistant-note-photo-img" src="{_SUPPORT_PERSON_ASSET}" alt="" loading="lazy" decoding="async"></div><div class="assistant-note-copy">{escape(note)}</div></div>'
        '</section>'
    )


def _render_journey_plan(so: dict, payload: dict, profile_copy: dict | None = None) -> str:
    return _render_journey_tasks(so, payload, profile_copy=profile_copy)


def _render_progress_banner(so: dict, payload: dict) -> str:
    score = _estimate_status_score(so)
    if score >= 82:
        title = "您正在稳步进步！"
        copy = "把现在这份节奏守住，恢复会更踏实。"
        emoji = "🏆"
    elif score >= 72:
        title = "您已经在慢慢找回节奏"
        copy = "不用一下子做很多，持续一点点往前就很好。"
        emoji = "💜"
    else:
        title = "今天先把恢复节奏找回来"
        copy = "先从最容易完成的两三件事开始，身体会慢慢跟上。"
        emoji = "🌿"

    note = _build_supportive_note(so, payload)
    return (
        '<section class="journey-card progress-banner">'
        '<div>'
        '<div class="progress-banner-title">' + escape(title) + '</div>'
        '<div class="progress-banner-copy">' + escape(copy) + '</div>'
        '<div class="progress-banner-note">' + escape(note) + '</div>'
        '</div>'
        f'<div class="progress-banner-emoji"><img class="progress-banner-img" src="{_PROGRESS_TROPHY_ASSET}" alt="" loading="lazy" decoding="async"></div>'
        '</section>'
    )


def _render_progress_snapshot(payload: dict, profile_copy: dict | None = None) -> str:
    trend_data = _build_trend_data(payload)
    if not trend_data:
        return ""
    profile_copy = profile_copy or {}

    window_key = "month" if "month" in trend_data else next(iter(trend_data))
    metrics = (trend_data.get(window_key) or {}).get("metrics") or []
    if not metrics:
        return ""

    cards = []
    for metric in metrics[:3]:
        label = _localize_zh_text(str(metric.get("label") or "")).strip()
        value = _localize_zh_text(str(metric.get("value") or "")).strip()
        delta = _localize_zh_text(str(metric.get("delta") or "")).strip()
        direction = str(metric.get("delta_direction") or "")
        delta_cls = "up" if direction == "up" else "down" if direction == "down" else "flat"
        cards.append(
            '<div class="progress-mini-card">'
            f'<div class="progress-mini-label">{escape(label)}</div>'
            f'<div class="progress-mini-value">{escape(value)}</div>'
            f'<div class="progress-mini-delta {delta_cls}">{escape(delta or "较起点持平")}</div>'
            '</div>'
        )
    if not cards:
        return ""

    return (
        '<section class="journey-card">'
        '<div class="journey-section-title">与过去的您对比</div>'
        f'<div class="journey-section-copy" data-copy-key="trend_compare_desc">{escape(_localize_zh_text(str(profile_copy.get("trend_compare_desc") or "先看最近一段时间的变化，再决定下一步怎么调得更合适。")))}</div>'
        f'<div class="progress-mini-grid">{"".join(cards)}</div>'
        '</section>'
    )


def _render_nutrition_focus_pills(so: dict, profile_copy: dict | None = None) -> str:
    priorities = so.get("nutrition_priorities") or []
    if not isinstance(priorities, list):
        return ""
    profile_copy = profile_copy or {}
    micro_copy = {
        "low_salt": "控盐更安心",
        "low_oil": "清淡更稳",
        "protein": "恢复靠蛋白",
        "hydration": "补水别太急",
        "fiber": "摄入要稳定",
        "meal_rhythm": "节奏别乱",
    }
    parts = []
    for item in priorities[:4]:
        if not isinstance(item, dict):
            continue
        title = _localize_zh_text(str(item.get("title") or item.get("action") or "")).strip()
        if not title:
            continue
        category = str(item.get("category") or "")
        icon = str(item.get("icon") or _NUTRITION_CATEGORY_ICONS.get(category) or "🥗")
        copy = micro_copy.get(category) or "今天先做到"
        parts.append(
            '<div class="nutrition-focus-pill">'
            f'<div class="nutrition-focus-icon">{escape(icon)}</div>'
            f'<div class="nutrition-focus-title">{escape(title)}</div>'
            f'<div class="nutrition-focus-copy">{escape(copy)}</div>'
            '</div>'
        )
    if not parts:
        return ""
    return (
        '<section class="journey-card">'
        '<div class="journey-section-title">今日营养重点</div>'
        f'<div class="journey-section-copy" data-copy-key="nutrition_priority_desc">{escape(_localize_zh_text(str(profile_copy.get("nutrition_priority_desc") or "根据今天的饮食和回访情况整理。")))}</div>'
        f'<div class="nutrition-focus-row">{"".join(parts)}</div>'
        '</section>'
    )


def _first_meal_items(meal_items: list) -> tuple[str, str]:
    if not meal_items:
        return "", ""
    first_day = meal_items[0] if isinstance(meal_items[0], dict) else {}
    for meal_key, meal_label in (("dinner", "晚餐"), ("lunch", "午餐"), ("breakfast", "早餐")):
        items = first_day.get(meal_key) or []
        if not isinstance(items, list) or not items:
            continue
        names = []
        reasons = []
        for item in items[:3]:
            if not isinstance(item, dict):
                continue
            name = _localize_zh_text(str(item.get("name") or "")).strip()
            reason = _localize_zh_text(str(item.get("adc_reason") or item.get("benefit") or "")).strip()
            if name:
                names.append(name)
            if reason:
                reasons.append(reason)
        if names:
            return f'{meal_label}：{" / ".join(names)}', "；".join(reasons[:2])
    return "", ""


def _render_next_meal_card(meal_items: list, nutrition_advice: str) -> str:
    title, copy = _first_meal_items(meal_items)
    if not title and not nutrition_advice:
        return ""
    title = title or "下一餐先清淡一点"
    copy = copy or nutrition_advice
    return (
        '<section class="journey-card meal-suggestion">'
        '<div class="meal-suggestion-art">🍲</div>'
        '<div>'
        '<div class="journey-section-kicker">下一餐建议</div>'
        f'<div class="meal-suggestion-title">{escape(title)}</div>'
        f'<div class="meal-suggestion-copy">{escape(copy)}</div>'
        '</div>'
        '</section>'
    )


def _render_diet_advice_cards(diet_table: list[dict]) -> str:
    if not diet_table:
        return ""
    cards = []
    for item in diet_table[:4]:
        if not isinstance(item, dict):
            continue
        condition = _localize_zh_text(str(item.get("condition") or "")).strip()
        principle = _localize_zh_text(str(item.get("principle") or "")).strip()
        recommend = _localize_zh_text(str(item.get("recommend") or "")).strip()
        avoid = _localize_zh_text(str(item.get("avoid") or "")).strip()
        if not (condition or principle or recommend or avoid):
            continue
        cards.append(
            '<div class="diet-advice-card">'
            '<div class="diet-advice-head">'
            f'<div class="diet-advice-title">{escape(condition or "饮食原则")}</div>'
            + (f'<div class="diet-advice-principle">{escape(principle)}</div>' if principle else "")
            + '</div>'
            '<div class="diet-advice-grid">'
            '<div class="diet-advice-column">'
            '<div class="diet-advice-label">建议优先</div>'
            f'<div class="diet-advice-copy">{escape(recommend or "按医生建议保持稳定饮食")}</div>'
            '</div>'
            '<div class="diet-advice-column">'
            '<div class="diet-advice-label">尽量避免</div>'
            f'<div class="diet-advice-copy">{escape(avoid or "避免突然大幅改变饮食")}</div>'
            '</div>'
            '</div>'
            '</div>'
        )
    if not cards:
        return ""
    return '<div class="diet-advice-list">' + "".join(cards) + '</div>'


def _render_journey_nutrition(
    so: dict,
    meal_items: list,
    meal_plan_html: str,
    current_time_raw: object,
    payload: dict,
    profile_copy: dict | None = None,
) -> str:
    profile_copy = profile_copy or {}
    nutrition_advice = _localize_zh_text(str(so.get("nutrition_advice") or "")).strip()
    focus_html = _render_nutrition_focus_pills(so, profile_copy=profile_copy)
    next_meal_html = _render_next_meal_card(meal_items, nutrition_advice)
    shopping_html = _render_shopping_list_section(payload, so)
    plan_html = ""
    if meal_plan_html:
        plan_html = (
            '<section class="journey-card">'
            '<div class="journey-section-title">膳食计划</div>'
            f'<div class="journey-section-copy" data-copy-key="meal_desc">{escape(_localize_zh_text(str(profile_copy.get("meal_desc") or "给您一些这周更容易参考的早、中、晚餐搭配。")))}</div>'
            f'{meal_plan_html}'
            '</section>'
        )
    diet_table = _render_diet_table(so.get("disease_diet_table") or so.get("diet_table") or [])
    diet_cards = _render_diet_advice_cards(so.get("disease_diet_table") or so.get("diet_table") or [])
    diet_html = (
        '<section class="journey-card diet-table-compact">'
        '<div class="journey-section-title">疾病饮食对照</div>'
        f'<div class="journey-section-copy" data-copy-key="nutrition_diet_desc">{escape(_localize_zh_text(str(profile_copy.get("nutrition_diet_desc") or "先看和当前慢病/用药最相关的饮食边界。")))}</div>'
        f'{diet_cards or diet_table}'
        '</section>'
    ) if (diet_cards or diet_table) else ""
    advice_html = (
        '<section class="journey-card">'
        '<div class="journey-section-title">营养说明</div>'
        f'<div class="journey-section-copy">{escape(nutrition_advice)}</div>'
        '</section>'
    ) if nutrition_advice else ""
    return diet_html + focus_html + next_meal_html + shopping_html + advice_html + plan_html


def _render_journey_why(so: dict, payload: dict, memory: dict, profile_copy: dict | None = None) -> str:
    profile_copy = profile_copy or {}
    profile_html = _render_patient_profile(so.get("patient_profile") or {})
    longitudinal_html = _render_longitudinal_highlights(so)
    context_html = _render_personalized_context(so, payload, memory)
    treatment_html = _render_treatment_theme_detail(so.get("treatment_theme") or {})
    treatment_education_html = _render_treatment_education_card(so.get("treatment_theme") or {})
    sections = []
    if profile_html:
        sections.append(
            '<section class="journey-card">'
            '<div class="journey-section-title">这份报告怎么更贴近您</div>'
            f'<div class="journey-section-copy" data-copy-key="profile_desc">{escape(_localize_zh_text(str(profile_copy.get("profile_desc") or "先根据年龄、认知负担和近期疾病压力，决定这次更适合用哪种表达方式。")))}</div>'
            f'<div class="why-stack mt-3">{profile_html}</div>'
            '</section>'
        )
    if longitudinal_html:
        sections.append(
            '<section class="journey-card">'
            '<div class="journey-section-title">这段时间的变化</div>'
            f'<div class="journey-section-copy" data-copy-key="longitudinal_desc">{escape(_localize_zh_text(str(profile_copy.get("longitudinal_desc") or "把这次回访和近期记录线索放在一起看，更容易知道哪里值得继续保持。")))}</div>'
            f'<div class="why-stack mt-3">{longitudinal_html}</div>'
            '</section>'
        )
    if treatment_html:
        sections.append(
            '<section class="journey-card">'
            '<div class="journey-section-title">治疗主题为什么这样定</div>'
            f'<div class="journey-section-copy" data-copy-key="treatment_desc">{escape(_localize_zh_text(str(profile_copy.get("treatment_desc") or "优先根据长期记忆里的客观治疗信息来定主题，近期记忆只作为变化线索补充。")))}</div>'
            f'<div class="why-stack mt-3">{treatment_html}</div>'
            '</section>'
        )
    if treatment_education_html:
        sections.append(
            '<section class="journey-card">'
            '<div class="journey-section-title">疾病教育</div>'
            f'<div class="journey-section-copy">{escape(_localize_zh_text(str(profile_copy.get("education_desc") or "把当前药物、治疗阶段和常见反应讲清楚，这样前面的建议会更容易理解，也更像是在解释“为什么”。")))}</div>'
            '</section>'
            f'{treatment_education_html}'
        )
    if context_html:
        sections.append(
            '<section class="journey-card">'
            '<div class="journey-section-title">建议依据</div>'
            f'<div class="journey-section-copy" data-copy-key="context_desc">{escape(_localize_zh_text(str(profile_copy.get("context_desc") or "把用药、饮食、活动和监测的依据拆开看。")))}</div>'
            f'<div class="why-stack mt-3">{context_html}</div>'
            '</section>'
        )
    note = _build_supportive_note(so, payload)
    sections.append(f'<div class="why-footer-note">小步坚持，持续改善。{escape(note)}</div>')
    return "".join(sections)


def _render_treatment_education_card(theme: dict) -> str:
    if not isinstance(theme, dict) or not theme:
        return ""
    education = theme.get("education") or {}
    if not isinstance(education, dict):
        return ""

    title = _localize_zh_text(str(education.get("title") or "")).strip()
    body = _localize_zh_text(str(education.get("body") or "")).strip()
    tip = _localize_zh_text(str(education.get("tip") or "")).strip()
    icon = _localize_zh_text(str(education.get("icon") or "\u2728")).strip() or "\u2728"
    page_badge = _localize_zh_text(str(education.get("page_badge") or "1/1")).strip() or "1/1"
    medication_line = _localize_zh_text(str(education.get("medication_line") or "")).strip()
    feedback_item_name = _localize_zh_text(
        str(education.get("feedback_item_name") or title or "\u6062\u590d\u6559\u80b2")
    ).strip()
    feedback_prompt = _localize_zh_text(str(education.get("feedback_prompt") or "")).strip()
    positive_label = _localize_zh_text(
        str(education.get("feedback_positive_label") or "\u6709\u5e2e\u52a9")
    ).strip() or "\u6709\u5e2e\u52a9"
    positive_active_label = _localize_zh_text(
        str(education.get("feedback_positive_active_label") or "\u5df2\u8bb0\u4e0b")
    ).strip() or "\u5df2\u8bb0\u4e0b"
    negative_label = _localize_zh_text(
        str(education.get("feedback_negative_label") or "\u4e0d\u6e05\u695a")
    ).strip() or "\u4e0d\u6e05\u695a"
    negative_active_label = _localize_zh_text(
        str(education.get("feedback_negative_active_label") or "\u5df2\u8bb0\u4e0b")
    ).strip() or "\u5df2\u8bb0\u4e0b"
    visual_asset = str(education.get("visual_asset") or _SUPPORT_PERSON_ASSET).strip() or _SUPPORT_PERSON_ASSET
    visual_label = _localize_zh_text(
        str(education.get("visual_label") or "\u6062\u590d\u6559\u80b2")
    ).strip() or "\u6062\u590d\u6559\u80b2"

    if not (title or body or tip or medication_line):
        return ""

    return (
        '<section class="journey-card treatment-education-card">'
        '<div class="treatment-education-head">'
        '<div>'
        f'<div class="journey-section-kicker">{escape(visual_label)}</div>'
        f'<div class="journey-section-title">{escape(title)}</div>'
        '</div>'
        f'<div class="treatment-education-page">{escape(page_badge)}</div>'
        '</div>'
        '<div class="treatment-education-hero">'
        '<div class="treatment-education-copy">'
        + (
            f'<div class="treatment-education-theme-line">{escape(medication_line)}</div>'
            if medication_line else ""
        )
        + (
            f'<div class="treatment-education-body">{escape(body)}</div>'
            if body else ""
        )
        + (
            '<div class="treatment-education-tip-box">'
            f'<div class="treatment-education-tip-icon">{escape(icon)}</div>'
            '<div>'
            '<div class="treatment-education-tip-label">\u5c0f\u8d34\u58eb</div>'
            f'<div class="treatment-education-tip-text">{escape(tip)}</div>'
            '</div>'
            '</div>'
            if tip else ""
        )
        + (
            '<div class="treatment-education-feedback">'
            f'<div class="treatment-education-feedback-copy">{escape(feedback_prompt)}</div>'
            '<div class="treatment-education-feedback-actions feedback-actions">'
            f'<button class="feedback-btn like" type="button" data-day-idx="-1" data-meal-type="education" data-item-name="{escape(feedback_item_name, quote=True)}" data-default-label="{escape(positive_label, quote=True)}" data-active-label="{escape(positive_active_label, quote=True)}" onclick="saveLikeFromButton(this)">{escape(positive_label)}</button>'
            f'<button class="feedback-btn feedback-skip" type="button" data-day-idx="-1" data-meal-type="education" data-item-name="{escape(feedback_item_name, quote=True)}" data-default-label="{escape(negative_label, quote=True)}" data-active-label="{escape(negative_active_label, quote=True)}" onclick="showFeedbackModalFromButton(this)">{escape(negative_label)}</button>'
            '</div>'
            '</div>'
            if feedback_prompt else ""
        )
        + '</div>'
        '<div class="treatment-education-visual">'
        f'<img class="treatment-education-visual-img" src="{escape(visual_asset, quote=True)}" alt="" loading="lazy" decoding="async">'
        f'<div class="treatment-education-visual-badge">{escape(icon)}</div>'
        '</div>'
        '</div>'
        '</section>'
    )


def _render_journey_why(so: dict, payload: dict, memory: dict, profile_copy: dict | None = None) -> str:
    profile_copy = profile_copy or {}
    profile_html = _render_patient_profile(so.get("patient_profile") or {})
    longitudinal_html = _render_longitudinal_highlights(so)
    context_html = _render_personalized_context(so, payload, memory)
    treatment_html = _render_treatment_theme_detail(so.get("treatment_theme") or {})
    treatment_education_html = _render_treatment_education_card(so.get("treatment_theme") or {})
    sections = []

    if profile_html:
        sections.append(
            '<section class="journey-card why-section-card why-profile-card">'
            '<div class="why-section-head">'
            '<div>'
            '<div class="journey-section-kicker">沟通分流</div>'
            '<div class="journey-section-title">这份报告怎么更贴近您</div>'
            '<div class="journey-section-copy">先根据年龄、认知负担和近期疾病压力，决定这次更适合的表达方式。</div>'
            '</div>'
            '<div class="why-section-dot"></div>'
            '</div>'
            f'<div class="why-stack mt-3">{profile_html}</div>'
            '</section>'
        )
    if treatment_education_html:
        sections.append(f'<div class="why-education-top">{treatment_education_html}</div>')
    if longitudinal_html:
        sections.append(
            '<section class="journey-card why-section-card why-insight-card">'
            '<div class="why-section-head">'
            '<div>'
            '<div class="journey-section-kicker">AI \u6d1e\u5bdf</div>'
            '<div class="journey-section-title">\u6211\u53d1\u73b0\u4e86\u8fd1\u671f\u7684\u4e00\u4e9b\u53d8\u5316</div>'
            '<div class="journey-section-copy">\u5bf9\u7167\u4e0a\u6b21\u548c\u8fd1\u51e0\u5929\u7684\u8bb0\u5f55\uff0c\u770b\u770b\u54ea\u4e9b\u505a\u5f97\u66f4\u7a33\uff0c\u54ea\u4e9b\u53ef\u4ee5\u6162\u6162\u518d\u63d0\u4e00\u70b9\u3002</div>'
            '</div>'
            '<div class="why-section-dot"></div>'
            '</div>'
            f'<div class="why-stack mt-3">{longitudinal_html}</div>'
            '</section>'
        )
    if treatment_html:
        sections.append(
            '<section class="journey-card why-section-card why-theme-card">'
            '<div class="why-section-head">'
            '<div>'
            '<div class="journey-section-kicker">\u6cbb\u7597\u4e3b\u9898</div>'
            '<div class="journey-section-title">\u8fd9\u6b21\u4e3a\u4ec0\u4e48\u4f18\u5148\u5173\u6ce8\u8fd9\u4e9b</div>'
            '<div class="journey-section-copy">\u4f18\u5148\u4f9d\u636e\u957f\u671f\u8bb0\u5fc6\u91cc\u7684\u5ba2\u89c2\u6cbb\u7597\u4fe1\u606f\u5b9a\u4e3b\u9898\uff0c\u8fd1\u671f\u8bb0\u5f55\u53ea\u4f5c\u4e3a\u8f85\u52a9\u7ebf\u7d22\u3002</div>'
            '</div>'
            '</div>'
            f'<div class="why-stack mt-3">{treatment_html}</div>'
            '</section>'
        )
    if context_html:
        sections.append(
            '<section class="journey-card why-section-card why-context-card">'
            '<div class="why-section-head">'
            '<div>'
            '<div class="journey-section-kicker">\u4f9d\u636e\u8bf4\u660e</div>'
            '<div class="journey-section-title">\u5efa\u8bae\u662f\u600e\u4e48\u6765\u7684</div>'
            '<div class="journey-section-copy">\u4f18\u5148\u5c55\u793a\u5177\u4f53\u65e5\u671f\u3001\u5ba2\u89c2\u6307\u6807\u548c\u4f9d\u4ece\u8bb0\u5f55\uff0cmemory.recent \u53ea\u4f5c\u4e3a\u8f85\u52a9\u53c2\u8003\u3002</div>'
            '</div>'
            '</div>'
            f'<div class="why-stack mt-3">{context_html}</div>'
            '</section>'
        )
    if not any([treatment_education_html, longitudinal_html, treatment_html, context_html]):
        sections.append(
            '<section class="journey-card why-section-card why-context-card">'
            '<div class="why-section-head">'
            '<div>'
            '<div class="journey-section-kicker">依据说明</div>'
            '<div class="journey-section-title">这次先依据哪些信息</div>'
            '<div class="journey-section-copy">当前这份记录里，治疗主题、纵向对比和教育卡片还没有足够的客观内容可展开，所以这页先保留沟通分流结果，并继续优先依据本次遵从记录和长期背景信息生成建议。</div>'
            '</div>'
            '<div class="why-section-dot"></div>'
            '</div>'
            '<div class="why-stack mt-3">'
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">🛡️</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">安全防线</div>'
            f'<div class="sub-card-value">{escape(_RECENT_GUARDRAIL_NOTE)}</div>'
            '</div>'
            '</div>'
            '</div>'
            '</div>'
            '</section>'
        )

    note = _build_supportive_note(so, payload)
    sections.append(
        f'<div class="why-footer-note">\u4e0d\u7528\u4e00\u6b21\u505a\u5f97\u5f88\u6ee1\uff0c\u53ea\u8981\u8fd9\u6bb5\u65f6\u95f4\u6bd4\u4e4b\u524d\u66f4\u7a33\u4e00\u70b9\u5c31\u5f88\u597d\u3002{escape(note)}</div>'
    )
    return "".join(sections)


def _render_bottom_nav() -> str:
    items = [
        ("⌂", "首页", "home", True, ""),
        ("▣", "计划", "plan", False, ""),
        ("◇", "依据", "why", False, ""),
        ("♨", "营养", "nutrition", False, ""),
        ("⌁", "趋势", "trends", False, ""),
    ]
    parts = []
    for icon, label, page_key, active, extra_class in items:
        parts.append(
            f'<button class="bottom-tab{extra_class}{" active" if active else ""}" '
            f'data-page-target="{page_key}" onclick="switchJourneyPage(\'{page_key}\')">'
            f'<div class="bottom-tab-icon">{icon}</div>'
            f'<div class="bottom-tab-label">{label}</div>'
            '</button>'
        )
    return f'<div class="bottom-tabbar">{"".join(parts)}</div>'


def _build_supportive_note(so: dict, payload: dict) -> str:
    appetite = _localize_zh_text(str(((so.get("adherence_analysis") or {}).get("appetite") or {}).get("status") or ""))
    steps = (so.get("latest_health_summary") or {}).get("steps_today")
    if "下降" in appetite or "吃不下" in appetite or "Decreased" in appetite:
        return (
            "我更想先关注您的营养状态。最近这段时间胃口一直不太好，身体修复和恢复体力都更需要蛋白质。"
            "今天不用吃很多，如果能额外补一份高蛋白加餐，就已经是很好的开始。"
        )
    if steps not in (None, ""):
        try:
            if float(_extract_numbers(steps)[0]) < 3000:
                return "今天最重要的不是一次做很多，而是把活动和营养都慢慢拉回来。哪怕只是短距离走一走，也是在往恢复前进。"
        except (IndexError, ValueError, TypeError):
            pass
    sections = so.get("assistant_message_sections") or []
    if sections:
        return _localize_zh_text(str(sections[0].get("content") or ""))
    return _localize_zh_text(so.get("assistant_message_patient") or "今天先把对恢复最有帮助的几件事做好，我们一步一步来。")


def _render_hero_intro(so: dict, payload: dict, memory: dict, tone_profile: dict, current_time_raw: str) -> str:
    name = _extract_patient_name(payload)
    greeting = _time_greeting(current_time_raw)
    guidance = so.get("health_guidance") or {}
    summary = _localize_zh_text((guidance.get("summary") if isinstance(guidance, dict) else "") or "")
    if not summary:
        sections = so.get("assistant_message_sections") or []
        summary = _localize_zh_text(str((sections[0].get("content") if sections else "") or "今天先看最重要的恢复重点。"))
    intro = _build_supportive_note(so, payload)
    avatar_text = escape(name[:1] if name and name != "您" else "您")
    return (
        '<div id="homeAnchor" class="px-3 pt-3">'
        '<section class="hero-welcome-card">'
        '<div class="hero-welcome-copy">'
        f'<div class="hero-welcome-eyebrow">{escape(greeting)}</div>'
        f'<h2 class="hero-welcome-title">{escape(name)}，今天先把最重要的几件事做好</h2>'
        f'<p class="hero-welcome-summary">{escape(summary)}</p>'
        f'<div class="hero-welcome-note">{escape(intro)}</div>'
        '<div class="hero-welcome-meta">AI 已为您整理今天的重点，下面三件事最值得先做。</div>'
        '</div>'
        '<div class="hero-welcome-visual">'
        f'<div class="hero-avatar-badge">{avatar_text}</div>'
        '<div class="hero-assistant-orb">AI</div>'
        '</div>'
        '</section>'
        '</div>'
    )


def _render_status_dashboard(so: dict, memory: dict) -> str:
    score = _estimate_status_score(so)
    badge_text, badge_bg, badge_color = _score_tone(score)
    latest = so.get("latest_health_summary") or {}
    adh = so.get("adherence_analysis") or {}
    metrics = [
        _render_dashboard_metric(
            "血压",
            str(latest.get("blood_pressure") or "--"),
            "今天的最新读数",
            "🩺",
            "#7c3aed",
        ),
        _render_dashboard_metric(
            "活动步数",
            f'{latest.get("steps_today") or "--"} 步',
            "先把活动一点点拉回来",
            "👟",
            "#2563eb",
        ),
        _render_dashboard_metric(
            "用药执行",
            _localize_zh_text(str((adh.get("medication") or {}).get("status") or "待观察")),
            "看今天有没有更顺手",
            "💊",
            "#10b981",
        ),
        _render_dashboard_metric(
            "营养状态",
            _localize_zh_text(str((adh.get("appetite") or {}).get("status") or "待观察")),
            "优先照顾食欲和体力",
            "🥛",
            "#f59e0b",
        ),
    ]

    progress_title = "本轮观察重点"
    progress_text = "当前以结构化依从情况和真实信号作为主要观察依据。"
    recent_scores_html = _render_recent_adherence_scores(so)

    return (
        '<div id="statusAnchor" class="px-3 pt-3">'
        '<section class="status-overview-card">'
        '<div class="status-overview-top">'
        '<div>'
        '<div class="status-overview-label">今日整体状态</div>'
        f'<div class="status-overview-score">{score}<span>/100</span></div>'
        f'<div class="status-overview-caption" style="color:{badge_color}">{escape(badge_text)}</div>'
        '</div>'
        '<div class="status-overview-ring">'
        f'<div class="status-overview-ring-fill" style="background:{badge_bg}"></div>'
        f'<div class="status-overview-ring-text">{score}</div>'
        '</div>'
        '</div>'
        '<div class="status-overview-progress">'
        f'<div class="status-overview-progress-bar" style="width:{score}%"></div>'
        '</div>'
        '<div class="status-overview-foot">今天先抓住营养、用药和活动三个核心点，比一次做很多更重要。</div>'
        '</section>'
        '</div>'
        f'{recent_scores_html}'
        '<div id="priorityPlanAnchor" class="px-3 pt-3">'
        '<section class="dashboard-panel">'
        '<div class="dashboard-panel-head">'
        '<div class="dashboard-panel-title">关键指标概览</div>'
        '<div class="dashboard-panel-copy">先看最能代表今天状态的四项。</div>'
        '</div>'
        f'<div class="dashboard-metric-grid">{"".join(metrics)}</div>'
        f'<div class="dashboard-progress-card"><div class="dashboard-progress-title">{escape(progress_title)}</div><div class="dashboard-progress-copy">{escape(progress_text)}</div></div>'
        '</section>'
        '</div>'
    )


def _render_priority_plan(so: dict, payload: dict) -> str:
    recs = so.get("recommendations") or []
    top_recs = recs[:3]
    if not top_recs:
        return ""

    emoji_cycle = ["🥛", "🚶", "🌙", "💊", "🥣", "📋"]
    cards = []
    for idx, rec in enumerate(top_recs, start=1):
        if isinstance(rec, dict):
            text = _clean_recommendation_text(rec.get("text", ""))
            reason = _localize_zh_text(rec.get("reason", ""))
        else:
            text = _clean_recommendation_text(rec)
            reason = ""
        safe_text = escape(text).replace("'", "&#39;")
        cards.append(
            '<div class="priority-task-card">'
            '<div class="priority-task-main">'
            f'<div class="priority-task-index">{idx}</div>'
            '<div class="priority-task-copy">'
            f'<div class="priority-task-title">{escape(text)}</div>'
            + (f'<div class="priority-task-reason">原因：{escape(reason)}</div>' if reason else "")
            + '</div>'
            f'<div class="priority-task-emoji">{emoji_cycle[(idx - 1) % len(emoji_cycle)]}</div>'
            '</div>'
            '<div class="priority-task-actions">'
            f'<button class="priority-task-btn" data-day-idx="-1" data-meal-type="priority" '
            f'data-item-name="{safe_text}" data-default-label="记为重点" data-active-label="已记重点" '
            f'onclick="saveLikeFromButton(this)">记为重点</button>'
            f'<button class="priority-task-btn secondary" data-day-idx="-1" data-meal-type="priority" '
            f'data-item-name="{safe_text}" data-default-label="稍后处理" data-active-label="已标稍后" '
            f'onclick="showFeedbackModalFromButton(this)">稍后处理</button>'
            '</div>'
            '</div>'
        )

    special_note = _build_supportive_note(so, payload)
    return (
        '<div class="px-3 pt-3">'
        '<section class="priority-plan-card">'
        '<div class="priority-plan-head">'
        '<div class="priority-plan-title">今天最值得先做的三件事</div>'
        '<div class="priority-plan-copy">基于您现在的状态和恢复阶段，先从这些开始会更容易。</div>'
        '</div>'
        f'{"".join(cards)}'
        f'<div class="priority-special-note"><span class="priority-special-label">AI 特别提醒</span>{escape(special_note)}</div>'
        '</section>'
        '</div>'
    )


def _render_nutrition_priorities(so: dict) -> str:
    priorities = so.get("nutrition_priorities") or []
    if not isinstance(priorities, list):
        return ""

    cards = []
    for item in priorities[:4]:
        if not isinstance(item, dict):
            continue
        title = _localize_zh_text(str(item.get("title") or "")).strip()
        action = _localize_zh_text(str(item.get("action") or "")).strip()
        reason = _localize_zh_text(str(item.get("reason") or "")).strip()
        if not (title or action or reason):
            continue
        category = str(item.get("category") or "").strip()
        icon = str(item.get("icon") or _NUTRITION_CATEGORY_ICONS.get(category) or "🥗")

        body_parts = []
        if action:
            body_parts.append(
                f'<div class="text-sm text-slate-700 leading-relaxed mb-2">'
                f'{escape(action)}</div>'
            )
        if reason:
            body_parts.append(
                f'<div class="text-xs text-emerald-700 leading-relaxed bg-emerald-50 '
                f'border border-emerald-100 rounded-lg px-3 py-2">'
                f'为什么：{escape(reason)}</div>'
            )

        cards.append(
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            f'<span class="sub-card-icon">{escape(icon)}</span>'
            '<div class="flex-1 min-w-0">'
            f'<div class="sub-card-value" style="font-size:0.92em">{escape(title or action)}</div>'
            '</div>'
            '</div>'
            f'<div class="sub-card-body">{"".join(body_parts)}</div>'
            '</div>'
        )

    return "".join(cards)


def main() -> None:
    _load_env()

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to parse input: {exc}", file=sys.stderr)
        sys.exit(1)

    payload = data.get("payload") or {}
    llm = data.get("llm_result") or {}
    so = llm.get("structured_output") or {}
    _sanitize_latest_health_summary(so, payload)
    _merge_adherence_payload(so, payload)
    profile = _augment_structured_output(so, payload)
    _apply_output_guards(so, has_blood_glucose=_payload_has_blood_glucose(payload))
    memory = payload.get("memory") or {}
    try:
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Template not found: {_TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)

    tone_profile = {}
    ctx = _CONDITION_CONTEXTS.get(str(profile.get("context_key") or "stable_routine"), _CONDITION_CONTEXTS["stable_routine"])
    profile_copy = _build_profile_copy(profile)
    profile_copy_variants = {
        mode: _build_profile_copy({"communication_mode": mode})
        for mode in ("simplified", "standard", "detailed")
    }
    profile_style_meta = _build_profile_style_meta()
    visible = set(_CONDITION_CONTEXTS["stable_routine"]["show_sections"])
    visible.update(ctx["show_sections"])
    visible.update({"profile", "longitudinal"})
    if str(profile.get("communication_mode") or "") == "simplified":
        visible.discard("diet_table")
        visible.discard("reasoning")
    elif str(profile.get("communication_mode") or "") == "standard":
        visible.discard("reasoning")
    else:
        visible.add("reasoning")

    if ctx["tone_override"]:
        tone_profile = {**tone_profile, "style": ctx["tone_override"]}
    profile_tone = str(profile.get("tone_style") or "").strip()
    if profile_tone:
        tone_profile = {**tone_profile, "style": profile_tone}

    escalations = []

    status = so.get("patient_status") or "stable"
    if any(e["level"] == "critical" for e in escalations):
        status = "at_risk"
    elif escalations and status == "stable":
        status = "at_risk"
    if status not in _STATUS_MAP:
        status = "stable"
    badge_class, status_icon, status_text = _STATUS_MAP[status]

    meta = payload.get("meta") or {}
    current_time = _format_time(
        meta.get("current_time") or datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    conditions = so.get("conditions") or []
    location = payload.get("location") or {}
    loc = location.get("current") or {}
    patient_lat = loc.get("lat")
    patient_lon = loc.get("lon")
    has_location = patient_lat not in (None, "") and patient_lon not in (None, "")

    if any(
        kw.lower() in t.lower() or kw in t
        for t in so.get("risk_tags", [])
        for kw in ("活动", "偏低", "activity", "low", "sedentary")
    ):
        ai_map_msg = "您近期活动量偏低，天气不错时可以去附近公园散散步。"
        ai_map_msg_park = ai_map_msg
    else:
        ai_map_msg = "已为您查询附近医疗网点，如有不适请及时就医。"
        ai_map_msg_park = "天气好时去附近公园走走，有助于身心放松。"

    baidu_map_ak = os.environ.get("BAIDU_MAP_AK", "").strip() or "6zXfgKZZiCdrL3MZBH7DGpjemq5IRxRC"
    maps_script = (
        '<script type="text/javascript" '
        f'src="https://api.map.baidu.com/api?v=3.0&ak={escape(baidu_map_ak, quote=True)}"></script>'
    )

    so["weekly_meal_plan"] = _ensure_full_weekly_meal_plan(payload, so)
    if not isinstance(so.get("nutrition_priorities"), list) or not so.get("nutrition_priorities"):
        so["nutrition_priorities"] = _build_fallback_nutrition_priorities(payload, so)
    if not str(so.get("nutrition_advice") or "").strip():
        so["nutrition_advice"] = _build_fallback_nutrition_advice(payload, so)

    meal_items = _localize_zh_value(so.get("weekly_meal_plan") or [])
    if not isinstance(meal_items, list):
        meal_items = []
    has_meal_plan = bool(meal_items)
    meal_json = _json_for_script(meal_items)

    patient_id = meta.get("user_id") or "unknown"

    patient = payload.get("patient") or {}
    preferred_name = str(patient.get("preferred_name") or patient.get("name") or patient.get("display_name") or "").strip() if isinstance(patient, dict) else ""
    if preferred_name:
        tone_profile = {**tone_profile, "preferred_name": preferred_name}
    base_greeting = ctx.get("header_greeting") or "您好！"
    if preferred_name:
        base_trimmed = base_greeting.rstrip("！!。,.， ")
        header_greeting = f"{base_trimmed}，{preferred_name}"
    else:
        header_greeting = base_greeting
    layout_class = ""

    def _module_subsection(title: str, description: str, content: str) -> str:
        if not content or not content.strip():
            return ""
        description_html = (
            f'<div class="module-subsection-copy">{escape(description)}</div>'
            if description else ""
        )
        return (
            '<div class="module-subsection">'
            '<div class="module-subsection-head">'
            f'<div class="module-subsection-title">{escape(title)}</div>'
            '</div>'
            f'{description_html}'
            f'{content}'
            '</div>'
        )

    def _section_card(section_key: str, icon: str, bg_color: str, title: str, summary: str, content: str, expanded: bool = False) -> str:
        if not content or not content.strip():
            return ""
        expanded_class = " expanded" if expanded else ""
        return (
            f'<div class="section-card{expanded_class}" data-section="{section_key}">'
            f'<div class="section-card-header">'
            f'<div class="section-card-icon" style="background:{bg_color}">{icon}</div>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="section-card-title">{escape(title)}</div>'
            f'<div class="section-card-summary">{escape(summary)}</div>'
            f'</div>'
            f'<div class="section-card-arrow">&#9662;</div>'
            f'</div>'
            f'<div class="section-card-body">{content}</div>'
            f'</div>'
        )

    def _vitals_subcards() -> str:
        vd = so.get("latest_health_summary") or {}
        icons = {"blood_pressure": "🩸", "heart_rate": "💓", "blood_oxygen": "🫁",
                 "blood_glucose": "🍬", "steps_today": "👟"}
        labels = {"blood_pressure": "血压", "heart_rate": "心率",
                  "blood_oxygen": "血氧", "blood_glucose": "血糖",
                  "steps_today": "步数"}
        html = ""
        for k in ("blood_pressure", "heart_rate", "blood_oxygen", "blood_glucose", "steps_today"):
            val = vd.get(k, "")
            if val:
                html += (
                    f'<div class="sub-card">'
                    f'<div class="sub-card-header">'
                    f'<span class="sub-card-icon">{icons.get(k, "📊")}</span>'
                    f'<div class="flex-1 min-w-0">'
                    f'<div class="sub-card-label">{labels.get(k, k)}</div>'
                    f'<div class="sub-card-value">{escape(str(val))}</div>'
                    f'</div></div></div>'
                )
        return html if html else '<p class="text-slate-500">暂无数据</p>'

    def _adherence_subcards() -> str:
        adh = so.get("adherence_analysis") or {}
        icons = {"medication": "💊", "appetite": "🍽️", "exercise": "🏃", "monitoring": "📋"}
        labels = {"medication": "用药", "appetite": "食欲与饮食",
                  "exercise": "运动与活动", "monitoring": "健康监测"}
        html = ""
        for k in ("medication", "appetite", "exercise", "monitoring"):
            dim = adh.get(k)
            if not isinstance(dim, dict) or not dim.get("status"):
                continue
            status_text_local = _localize_zh_text(dim["status"])
            is_good = any(w in status_text_local.lower() or w in status_text_local for w in _GOOD_STATUS_KEYWORDS)
            color = "text-emerald-700" if is_good else "text-amber-700"

            detail_parts = []
            for dk in [x for x in dim if x != "status"]:
                val = dim[dk]
                if val:
                    label = _field_label(dk)
                    detail_parts.append(
                        f'<div class="text-sm text-slate-600 mb-1">'
                        f'<span class="font-medium text-slate-500">{label}：</span> {escape(_localize_zh_text(str(val)))}</div>'
                    )
            body_html = "".join(detail_parts)

            html += (
                f'<div class="sub-card">'
                f'<div class="sub-card-header">'
                f'<span class="sub-card-icon">{icons.get(k, "📋")}</span>'
                f'<div class="flex-1 min-w-0">'
                f'<div class="sub-card-label">{labels.get(k, k)}</div>'
                f'<div class="sub-card-value {color}">{escape(status_text_local)}</div>'
                f'</div>'
                f'<span class="sub-card-arrow">▶</span>'
                f'</div>'
            )
            if body_html:
                html += f'<div class="sub-card-body">{body_html}</div>'
            html += '</div>'
        return html

    def _recs_subcards() -> str:
        recs = so.get("recommendations") or []
        if not recs:
            return ""
        html = ""
        if "risk_tags" in visible:
            tags = _render_risk_tags(so.get("risk_tags") or [])
            if tags:
                html += f'<div class="flex flex-wrap gap-2 mb-3">{tags}</div>'
        for r in recs:
            if isinstance(r, dict):
                text = _localize_zh_text(r.get("text", ""))
                reason = _localize_zh_text(r.get("reason", ""))
                category = r.get("category", "")
                icon = _CATEGORY_ICONS.get(category, "💡")
            else:
                text = _localize_zh_text(str(r))
                reason = ""
                icon = "💡"
            safe_text = escape(text).replace("'", "&#39;")

            body_parts = []
            if reason:
                body_parts.append(
                    f'<div class="text-sm text-emerald-700 leading-relaxed italic mb-2">'
                    f'💬 {escape(reason)}</div>'
                )
            body_parts.append(
                f'<div class="feedback-actions" style="flex-direction:row;flex-wrap:wrap">'
                f'<button class="feedback-btn like" title="有帮助" data-day-idx="-1" data-meal-type="rec" '
                f'data-item-name="{safe_text}" data-default-label="适合我" data-active-label="已选择" '
                f'onclick="saveLikeFromButton(this)">适合我</button>'
                f'<button class="feedback-btn feedback-skip" title="不适合我" data-day-idx="-1" data-meal-type="rec" '
                f'data-item-name="{safe_text}" data-default-label="不适合" data-active-label="已跳过" '
                f'onclick="showFeedbackModalFromButton(this)">不适合</button>'
                f'</div>'
            )
            body_html = "".join(body_parts)

            html += (
                f'<div class="sub-card sub-card-static">'
                f'<div class="sub-card-header">'
                f'<span class="sub-card-icon">{icon}</span>'
                f'<div class="flex-1 min-w-0">'
                f'<div class="sub-card-value" style="font-size:0.92em">{escape(text)}</div>'
                f'</div>'
                f'</div>'
                f'<div class="sub-card-body">{body_html}</div>'
                f'</div>'
            )
        reasoning = _localize_zh_text(so.get("reasoning") or "")
        if reasoning and "reasoning" in visible:
            html += (
                f'<div class="text-xs text-slate-500 mt-3 bg-slate-50 rounded-lg p-3 leading-relaxed">'
                f'💭 {escape(reasoning)}</div>'
            )
        return html

    nutrition_advice = _localize_zh_text(str(so.get("nutrition_advice") or "")).strip()
    nutrition_text = (
        '<div class="rounded-xl bg-emerald-50 border border-emerald-100 px-4 py-4 '
        'text-[0.95em] leading-7 text-slate-700">'
        + escape(nutrition_advice)
        + '</div>'
    ) if nutrition_advice else ""
    cuisine_html = (
        '<p class="text-sm text-slate-500 mb-3">选择您喜欢的菜系，后续膳食建议会尽量参考您的口味。</p>'
        '<div class="flex flex-wrap gap-2 mb-3" id="cuisineChips"></div>'
        '<div class="flex items-center gap-2">'
        '<input id="customCuisineInput" type="text" placeholder="添加其他菜系..." '
        'class="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2 '
        'focus:outline-none focus:border-emerald-400 focus:ring-1 focus:ring-emerald-200">'
        '<button onclick="addCustomCuisine()" class="px-3 py-2 rounded-lg bg-emerald-50 '
        'border border-emerald-200 text-emerald-700 text-sm font-medium hover:bg-emerald-100">'
        '+ 添加</button></div>'
    )
    meal_plan_html = (
        '<div class="flex gap-2 mb-4 overflow-x-auto pb-2" id="dayTabs"></div>'
        '<div id="mealContent"></div>'
    ) if has_meal_plan else ""
    submit_cta_html = (
        '<div id="submitCtaShell" class="submit-cta-shell">'
        '<button id="exportFeedbackBtn" onclick="exportFeedbackJSON()" '
        'class="submit-cta-button" disabled>✓ 先选择偏好再提交</button>'
        '<p class="submit-cta-hint" id="submitHint">'
        '请先在上面选择口味或标记适合/不适合</p>'
        '</div>'
    ) if "submit" in visible else ""

    hero_intro_html = _render_hero_intro(so, payload, memory, tone_profile, meta.get("current_time") or "")
    quick_nav_html = _render_quick_nav()
    status_dashboard_html = _render_status_dashboard(so, memory)
    priority_plan_html = _render_priority_plan(so, payload)
    nutrition_spotlight_html = ""
    treatment_detail_html = _render_treatment_theme_detail(so.get("treatment_theme") or {})
    hero_vitals_block = _render_vitals(so.get("latest_health_summary") or {}) if "vitals" in visible else ""
    hero_vitals_html = f'<div class="px-3 pt-3">{hero_vitals_block}</div>' if hero_vitals_block else ""
    memory_overview_html = _render_memory_overview(memory) if "memory" in visible else ""
    top_overview_html = (
        '<div class="px-3 pt-3">'
        '<div class="top-overview-panel rounded-[28px] p-3 shadow-sm">'
        '<div class="flex items-center gap-2 mb-2 px-1">'
        '<span class="top-overview-kicker text-base">🗂️</span>'
        '<span class="text-xs font-bold text-slate-600 uppercase tracking-wide">长期情况</span>'
        '</div>'
        f'{memory_overview_html}'
        '</div>'
        '</div>'
    ) if memory_overview_html else ""
    trend_data = _build_trend_data(payload)
    trend_story_html = _render_trend_story(trend_data)
    trend_data_json = _json_for_script(trend_data)
    bottom_nav_html = _render_bottom_nav()
    current_time_raw = meta.get("current_time") or datetime.now().strftime("%Y-%m-%d %H:%M")
    home_page_html = _journey_page(
        "home",
        "首页",
        _localize_zh_text(str(profile_copy.get("home_subtitle") or "先看今天的状态、执行情况和最新生命体征。")),
        _render_journey_home(so, payload, memory, current_time_raw, profile_copy=profile_copy),
        active=True,
    )
    plan_page_body = _render_journey_plan(so, payload, profile_copy=profile_copy)
    local_resource_html = _render_local_resource_section(payload, so)
    if local_resource_html.strip():
        plan_page_body += local_resource_html
    plan_page_html = _journey_page(
        "plan",
        "今日计划",
        _localize_zh_text(str(profile_copy.get("plan_subtitle") or "今天先集中完成这三件事。")),
        plan_page_body,
    )
    nutrition_page_html = _journey_page(
        "nutrition",
        "营养与饮食建议",
        _localize_zh_text(str(profile_copy.get("nutrition_subtitle") or "查看适合今天的饮食重点和餐食建议。")),
        _render_journey_nutrition(so, meal_items, meal_plan_html, current_time_raw, payload, profile_copy=profile_copy),
    )
    trend_page_html = _journey_page(
        "trends",
        "健康趋势",
        _localize_zh_text(str(profile_copy.get("trend_subtitle") or "查看近期血压、心率和血氧变化。")),
        _render_progress_banner(so, payload) + _render_progress_snapshot(payload, profile_copy=profile_copy) + trend_story_html,
    )
    why_page_html = _journey_page(
        "why",
        "为什么这样建议",
        _localize_zh_text(str(profile_copy.get("why_subtitle") or "了解每条建议与您近期情况的关系。")),
        _render_journey_why(so, payload, memory, profile_copy=profile_copy),
    )

    regrouped_cards = []

    guidance_bundle_html = "".join([
        _module_subsection("这份报告怎么更贴近您", str(profile_copy.get("profile_desc") or "先按年龄、认知负担和近期疾病压力，决定这次更适合的表达方式。"), _render_patient_profile(so.get("patient_profile") or {})) if "profile" in visible else "",
        _module_subsection("当前治疗主题", str(profile_copy.get("treatment_desc") or "把药物、治疗阶段和今天更该关注的点单独拎出来看，会更贴近病人的真实处境。"), treatment_detail_html) if treatment_detail_html else "",
        _module_subsection("为什么这些建议和您有关", str(profile_copy.get("context_desc") or "先把您的病史、当前用药和最近指标放在前面，后面的建议会更容易看懂。"), _render_personalized_context(so, payload, memory)) if ("guidance" in visible or "recommendations" in visible) else "",
        _module_subsection("健康指导", str(profile_copy.get("guidance_desc") or "结合您最近的感受，整理出现在最值得留意的重点。"), _render_health_guidance(so.get("health_guidance") or {}, conditions, tone_profile=tone_profile)) if "guidance" in visible else "",
        _module_subsection("健康建议", str(profile_copy.get("recommendations_desc") or "这些是现在更适合您去做的小步骤。"), _recs_subcards()) if "recommendations" in visible else "",
    ])
    if guidance_bundle_html:
        regrouped_cards.append(
            _section_card(
                "guidance_bundle",
                "💚",
                "#d1fae5",
                "现在怎么做",
                "把重点提醒和建议放在一起，更容易看懂。",
                guidance_bundle_html,
            )
        )

    adherence_body_parts = []
    if "longitudinal" in visible:
        longitudinal_html = _render_longitudinal_highlights(so)
        if longitudinal_html.strip():
            adherence_body_parts.append(
                _module_subsection("这段时间的变化", str(profile_copy.get("longitudinal_desc") or "把这次回访和近期记录线索放在一起看，更容易知道哪里值得继续保持。"), longitudinal_html)
            )
    if "adherence" in visible:
        adherence_html = _adherence_subcards()
        if adherence_html.strip():
            adherence_body_parts.append(
                _module_subsection("执行情况", str(profile_copy.get("adherence_desc") or "看看最近用药、营养、活动和监测情况。"), adherence_html)
            )
    adherence_bundle_html = "".join(adherence_body_parts)
    if adherence_bundle_html:
        regrouped_cards.append(
            _section_card(
                "adherence",
                "📋",
                "#f3e8ff",
                "最近情况",
                "把最近做得怎么样和关键事件放在一起看。",
                adherence_bundle_html,
            )
        )

    nutrition_priorities_html = _render_nutrition_priorities(so)
    nutrition_bundle_html = "".join([
        _module_subsection("今日营养重点", str(profile_copy.get("nutrition_priority_desc") or "根据今天的饮食和回访情况整理。"), nutrition_priorities_html) if ("nutrition" in visible and nutrition_priorities_html) else "",
        _module_subsection("营养建议", str(profile_copy.get("nutrition_advice_desc") or "先看这段时间哪些营养安排更适合您。"), nutrition_text) if ("nutrition" in visible and nutrition_text) else "",
        _module_subsection("营养小贴士", str(profile_copy.get("nutrition_tips_desc") or "都是些更容易用得上的小提醒。"), _render_diet_tips(so.get("diet_tips") or [])) if "diet_tips" in visible else "",
    ])
    if nutrition_bundle_html:
        regrouped_cards.append(
            _section_card(
                "nutrition_bundle",
                "🥗",
                "#ecfdf5",
                "营养重点",
                "把营养建议、对照和小提醒放在一起，更好参考。",
                nutrition_bundle_html,
            )
        )

    meal_bundle_html = "".join([
        _module_subsection("口味偏好", str(profile_copy.get("cuisine_desc") or "选一些您平时更喜欢的口味，后面的膳食建议会更贴近您。"), cuisine_html) if ("cuisine" in visible and has_meal_plan) else "",
        _module_subsection("一周膳食参考", str(profile_copy.get("meal_desc") or "给您一些这周更容易参考的早、中、晚餐搭配。"), meal_plan_html) if ("meal_plan" in visible and meal_plan_html) else "",
    ])
    if meal_bundle_html:
        regrouped_cards.append(
            _section_card(
                "meal_bundle",
                "🍽️",
                "#eff6ff",
                "膳食计划",
                "口味偏好和本周膳食安排都整理在这里。",
                meal_bundle_html,
            )
        )

    cards_html = "\n".join(part for part in regrouped_cards if part)

    report_title = "照护旅程"
    html = template.format(
        report_title=report_title,
        header_greeting=header_greeting,
        layout_class=layout_class,
        patient_id=patient_id,
        patient_id_json=_json_for_script(str(patient_id)),
        current_time=current_time,
        current_time_json=_json_for_script(str(current_time)),
        status_badge_class=badge_class,
        status_icon=status_icon,
        status_text=status_text,
        condition_badges=_render_condition_badges(conditions),
        hero_intro_html=hero_intro_html,
        quick_nav_html=quick_nav_html,
        status_dashboard_html=status_dashboard_html,
        priority_plan_html=priority_plan_html,
        nutrition_spotlight_html=nutrition_spotlight_html,
        hero_vitals_html=hero_vitals_html,
        top_overview_html=top_overview_html,
        trend_story_html=trend_story_html,
        home_page_html=home_page_html,
        plan_page_html=plan_page_html,
        nutrition_page_html=nutrition_page_html,
        trend_page_html=trend_page_html,
        why_page_html=why_page_html,
        escalation_html=_render_escalation_banner(escalations) if "escalation" in visible else "",
        ai_message_html=_render_ai_message(so),
        cards_html=cards_html,
        submit_cta_html=submit_cta_html,
        bottom_nav_html=bottom_nav_html,
        meal_data_json=meal_json,
        trend_data_json=trend_data_json,
        profile_mode_json=_json_for_script(str(profile.get("communication_mode") or "standard")),
        profile_copy_variants_json=_json_for_script(profile_copy_variants),
        profile_style_meta_json=_json_for_script(profile_style_meta),
        maps_script=maps_script,
        guardrail=escape(
            _localize_zh_text(so.get("guardrail"))
            or "本报告由 AI 健康助手生成，仅供参考，不构成医疗建议。如有不适，请及时联系医生或拨打 120。"
        ),
    )

    escalation_records = []
    for esc in escalations:
        escalation_records.append({
            "level": esc["level"],
            "title": esc["title"],
            "message": esc["message"],
            "count": esc["count"],
            "threshold": esc["threshold"],
            "detected_at": meta.get("current_time") or datetime.now().isoformat(),
        })

    result = {
        "structured_output": {
            "title": report_title,
            "category": "adherence",
            "html": html,
            "detail": so,
            "escalations": escalation_records,
        },
    }

    json.dump(_sanitize_json_safe(result), sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
