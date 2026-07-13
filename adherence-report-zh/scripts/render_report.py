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

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "report.html"
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

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


# ─── Escalation Rules ───────────────────────────────────────────────
# Keep the same renderer-level escalation behavior as the English skill,
# with Chinese keywords and patient-facing copy.
_ESCALATION_RULES = [
    {
        "keywords": ["headache", "head pain", "migraine", "头痛", "偏头痛"],
        "threshold": 3,
        "level": "escalated",
        "title": "反复头痛，需要进一步关注",
        "message": (
            "近期记录中您提到头痛 {count} 次。因为这个症状反复出现，"
            "系统会将它标记为需要更密切观察，并提醒照护团队关注。"
        ),
        "recommendation": "每次出现时，请记录时间、严重程度（1-10 分）以及可能诱因。",
    },
    {
        "keywords": ["dizzy", "dizziness", "lightheaded", "vertigo", "头晕", "眩晕", "发晕"],
        "threshold": 3,
        "level": "escalated",
        "title": "反复头晕，需要进一步关注",
        "message": (
            "近期记录中头晕相关描述出现 {count} 次。"
            "这种模式可能与血压波动或药物副作用有关。"
        ),
        "recommendation": "头晕时先坐下或躺下，并记录是否发生在起身后或服药后。",
    },
    {
        "keywords": ["chest pain", "chest tightness", "chest discomfort", "胸痛", "胸闷", "胸部不适"],
        "threshold": 2,
        "level": "critical",
        "title": "反复胸部不适，需要尽快处理",
        "message": "胸部相关不适近期出现 {count} 次，这需要及时医学评估。",
        "recommendation": "如果现在正在胸痛或胸闷，请立即拨打 120 或联系急救服务。",
    },
    {
        "keywords": ["fall", "fell down", "lost balance", "跌倒", "摔倒", "失去平衡"],
        "threshold": 2,
        "level": "escalated",
        "title": "多次跌倒风险提醒",
        "message": "近期记录中出现 {count} 次跌倒或失衡相关事件，受伤风险会升高。",
        "recommendation": "请尽量扶稳后再行走，清理家中容易绊倒的物品。",
    },
]


def _check_escalations(key_events: list[dict]) -> list[dict]:
    """Scan key_events for recurring symptoms that trigger escalation rules."""
    if not key_events:
        return []

    triggered = []
    event_texts = [
        ev.get("description", "").lower() for ev in key_events
        if ev.get("type") in ("symptom", "alert", "complaint")
    ]

    for rule in _ESCALATION_RULES:
        count = sum(
            1 for text in event_texts
            if any(kw.lower() in text for kw in rule["keywords"])
        )
        if count >= rule["threshold"]:
            triggered.append({
                "level": rule["level"],
                "title": rule["title"],
                "message": rule["message"].format(count=count),
                "recommendation": rule["recommendation"],
                "count": count,
                "threshold": rule["threshold"],
            })
    return triggered


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


def _extract_numbers(value: object) -> list[float]:
    if value is None:
        return []
    cleaned = str(value).replace(",", "")
    return [float(part) for part in re.findall(r"\d+(?:\.\d+)?", cleaned)]


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
    """Render profile + recent trends as always-visible top overview cards."""
    if not memory:
        return ""

    profile = _localize_zh_text(memory.get("patient_long_term_profile") or "")
    dynamics = _localize_zh_text(memory.get("recent_health_dynamics") or "")

    blocks = []

    if profile:
        blocks.append(
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">👤</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">长期资料</div>'
            '<div class="sub-card-value">先了解您的基础情况</div>'
            '</div>'
            '</div>'
            f'<div class="sub-card-body"><div class="text-sm text-slate-700 leading-relaxed">{escape(profile)}</div></div>'
            '</div>'
        )

    if dynamics:
        blocks.append(
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">📈</span>'
            '<div class="flex-1 min-w-0">'
            '<div class="sub-card-label">近期趋势</div>'
            '<div class="sub-card-value">这段时间身体有什么变化</div>'
            '</div>'
            '</div>'
            f'<div class="sub-card-body"><div class="text-sm text-slate-700 leading-relaxed">{escape(dynamics)}</div></div>'
            '</div>'
        )

    return "".join(blocks)


def _render_key_events(memory: dict) -> str:
    """Render key events as a compact timeline list."""
    if not memory:
        return ""

    events = memory.get("key_events") or []
    if not events:
        return ""

    event_icons = {"surgery": "🩺", "symptom": "⚠️", "alert": "🚨", "medication": "💊", "visit": "🏥"}
    events_body = '<div class="space-y-2">'
    for ev in events:
        ev_icon = event_icons.get(ev.get("type", ""), "📌")
        ev_date = ev.get("date", "")
        ev_desc = _localize_zh_text(ev.get("description", ""))
        ev_type = ev.get("type", "")
        type_cls = {
            "surgery": "bg-purple-50 text-purple-700 border-purple-200",
            "alert": "bg-rose-50 text-rose-700 border-rose-200",
            "symptom": "bg-amber-50 text-amber-700 border-amber-200",
            "medication": "bg-blue-50 text-blue-700 border-blue-200",
        }.get(ev_type, "bg-slate-50 text-slate-600 border-slate-200")
        events_body += (
            f'<div class="flex items-start gap-3 rounded-lg p-2.5 border {type_cls}">'
            f'<span class="text-base mt-0.5">{ev_icon}</span>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="text-sm font-semibold">{escape(ev_desc)}</div>'
            f'<div class="text-xs text-slate-400 mt-0.5">{escape(ev_date)}</div>'
            f'</div></div>'
        )
    events_body += '</div>'
    return events_body


def _render_memory(memory: dict) -> str:
    """Backward-compatible combined memory rendering."""
    return _render_memory_overview(memory) + _render_key_events(memory)


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
    key_events = memory.get("key_events") or []
    profile = memory.get("patient_long_term_profile") or ""
    recent_dynamics = memory.get("recent_health_dynamics") or ""
    meds = _extract_medications(profile)
    latest_summary = so.get("latest_health_summary") or {}
    signals = payload.get("signals") or {}
    adherence = so.get("adherence_analysis") or {}

    surgery_event = next(
        (
            ev for ev in key_events
            if ev.get("type") == "surgery"
            or "手术" in str(ev.get("description", ""))
            or "surgery" in str(ev.get("description", "")).lower()
        ),
        None,
    )

    history_chips = []
    if conditions:
        history_chips.extend(conditions[:3])
    if surgery_event:
        history_chips.append(f'{surgery_event.get("date", "")} {surgery_event.get("description", "")}'.strip())
    elif "术后" in profile or "post-surgery" in profile.lower():
        history_chips.append("当前处于术后恢复阶段")

    if history_chips:
        implication_parts = []
        if surgery_event or "术后" in profile or "post-surgery" in profile.lower():
            implication_parts.append("恢复期会更强调蛋白质、容易入口的食物和循序渐进活动")
        if any(c in {"高血压", "Hypertension"} for c in conditions):
            implication_parts.append("营养安排会特别强调少盐")
        if any(c in {"2型糖尿病", "糖尿病", "Type 2 diabetes", "Diabetes"} for c in conditions):
            implication_parts.append("也会提醒规律分餐和减少精制糖")

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
            f'<div class="flex flex-wrap gap-2 mb-3">{"".join(f"<span class=\"context-chip\">{escape(_localize_zh_text(chip))}</span>" for chip in history_chips[:4])}</div>'
            + (
                '<div class="text-xs text-slate-600 bg-slate-50 rounded-xl px-3 py-2 leading-relaxed border border-slate-200">'
                f'所以这里会更强调：{escape("；".join(implication_parts))}</div>'
                if implication_parts else ""
            )
            + '</div></div>'
        )

    med_issue = _stringify_compact((adherence.get("medication") or {}).get("issues"))
    med_adjustment = _stringify_compact((adherence.get("medication") or {}).get("adjustments"))
    if not med_issue:
        med_issue = next(
            (str(ev.get("description", "")).strip() for ev in key_events if "服用" in str(ev.get("description", "")) or "药" in str(ev.get("description", ""))),
            ""
        )

    if meds or med_issue:
        med_body = ""
        if meds:
            med_body += f'<div class="flex flex-wrap gap-2 mb-3">{"".join(f"<span class=\"context-chip\">{escape(med)}</span>" for med in meds)}</div>'
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
    signal_bits = [_localize_zh_text(str(item).strip()) for item in (signals.get("anomalies") or []) if str(item).strip()]
    recent_focus = []
    if metric_bits:
        recent_focus.append("最近记录：" + "，".join(metric_bits[:3]))
    if signal_bits:
        recent_focus.append("设备提示：" + "、".join(signal_bits[:2]))
    if monitoring_gap:
        recent_focus.append("监测提醒：" + monitoring_gap)
    elif recent_dynamics:
        recent_text = _stringify_compact(recent_dynamics)
        recent_focus.append(recent_text[:120] + ("..." if len(recent_text) > 120 else ""))

    if recent_focus:
        implication = []
        if any("血糖" in bit for bit in metric_bits):
            implication.append("营养安排会更强调规律分餐")
        if any("步数" in bit for bit in metric_bits) or any("Activity" in bit or "活动" in bit for bit in signal_bits):
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

    extra_notes = []
    for key, label in (
        ("clinical_notes", "临床备注"),
        ("doctor_notes", "医生备注"),
        ("case_history", "病例重点"),
        ("latest_labs", "最近检查"),
    ):
        text = _stringify_compact(memory.get(key) or payload.get(key))
        if text:
            extra_notes.append((label, text))
    for label, text in extra_notes[:1]:
        cards.append(
            '<div class="sub-card sub-card-static">'
            '<div class="sub-card-header">'
            '<span class="sub-card-icon">🧠</span>'
            '<div class="flex-1 min-w-0">'
            f'<div class="sub-card-label">{escape(_localize_zh_text(label))}</div>'
            '<div class="sub-card-value">如果后面接入更深的病例，这里会直接引用</div>'
            '</div>'
            '</div>'
            f'<div class="sub-card-body"><div class="text-sm text-slate-700 leading-relaxed">{escape(_localize_zh_text(text))}</div></div>'
            '</div>'
        )

    return "".join(cards)


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
                f"onclick=\"saveLike(-1,'tip','{safe_title}', this)\">适合我</button>"
                f'<button class="feedback-btn feedback-skip" title="不适合我" data-day-idx="-1" data-meal-type="tip" '
                f'data-item-name="{safe_title}" data-default-label="不适合" data-active-label="已跳过" '
                f"onclick=\"showFeedbackModal(-1,'tip','{safe_title}', this)\">不适合</button>"
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
    lat = patient_lat if patient_lat else 39.9042
    lon = patient_lon if patient_lon else 116.4074

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
        '<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5 mb-3">'
        '<div class="flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">'
        '<span class="text-lg">📍</span>'
        '<h2 class="text-sm font-bold text-slate-800">附近推荐</h2>'
        "</div>"
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
        "</div>"
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


def _extract_patient_name(memory: dict, tone_profile: dict) -> str:
    preferred = (tone_profile or {}).get("preferred_name") or ""
    if preferred:
        return preferred.strip()

    profile = str((memory or {}).get("patient_long_term_profile") or "").strip()
    if not profile:
        return "您"

    match = re.match(r"\s*([A-Z][A-Za-z]+)", profile)
    if match:
        return match.group(1)

    cn_match = re.match(r"\s*([\u4e00-\u9fff]{2,4})", profile)
    if cn_match:
        return cn_match.group(1)

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


def _render_quick_nav() -> str:
    items = [
        ("🗂️", "首页", "先看总览", "homeAnchor", True),
        ("✅", "计划", "今天重点", "priorityPlanAnchor", False),
        ("🥗", "营养", "补给节奏", "nutritionOverviewAnchor", False),
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


def _infer_nutrition_snapshot(so: dict) -> tuple[list[dict], str]:
    appetite = _localize_zh_text(str(((so.get("adherence_analysis") or {}).get("appetite") or {}).get("status") or ""))
    glucose_nums = _extract_numbers((so.get("latest_health_summary") or {}).get("blood_glucose"))
    steps_nums = _extract_numbers((so.get("latest_health_summary") or {}).get("steps_today"))

    protein = 82
    hydration = 78
    meal_freq = 80
    tolerance = 84

    if "下降" in appetite or "decreased" in appetite.lower():
        protein = 62
        meal_freq = 58
        tolerance = 64
    if glucose_nums and glucose_nums[0] > 7.0:
        meal_freq = min(meal_freq, 66)
    if steps_nums and steps_nums[0] < 3000:
        protein = min(protein + 6, 92)
        hydration = min(hydration + 4, 92)

    items = [
        {"label": "蛋白质", "value": protein, "note": "优先补强", "accent": "#8b5cf6", "track": "#ede9fe"},
        {"label": "补水", "value": hydration, "note": "继续稳定", "accent": "#06b6d4", "track": "#cffafe"},
        {"label": "小餐节奏", "value": meal_freq, "note": "待加强", "accent": "#f59e0b", "track": "#fef3c7"},
        {"label": "胃部耐受", "value": tolerance, "note": "轻柔安排", "accent": "#10b981", "track": "#d1fae5"},
    ]

    story = (
        "今天不需要一次吃很多。先把蛋白质和补水照顾好，再把正餐拆小一点，"
        "通常会比勉强吃完整一大餐更容易坚持，也更符合当前恢复节奏。"
    )
    if protein <= 65:
        story = (
            "今天我更建议先把营养补给放在第一位。哪怕只是额外补一份高蛋白奶、酸奶或鸡蛋，"
            "也会比空着肚子更有助于恢复体力。"
        )
    return items, story


def _render_nutrition_spotlight(so: dict) -> str:
    items, story = _infer_nutrition_snapshot(so)
    rings = []
    for item in items:
        rings.append(
            '<div class="nutrition-ring-card">'
            f'<div class="nutrition-ring" style="--pct:{item["value"]};--ring-accent:{item["accent"]};--ring-track:{item["track"]}">'
            f'<div class="nutrition-ring-inner">{item["value"]}%</div>'
            '</div>'
            f'<div class="nutrition-ring-label">{item["label"]}</div>'
            f'<div class="nutrition-ring-note">{item["note"]}</div>'
            '</div>'
        )

    return (
        '<div id="nutritionOverviewAnchor" class="px-3 pt-3">'
        '<section class="nutrition-spotlight-card">'
        '<div class="nutrition-spotlight-head">'
        '<div>'
        '<div class="nutrition-spotlight-title">今日营养总览</div>'
        '<div class="nutrition-spotlight-copy">把今天最值得优先照顾的营养重点放在前面，看起来会更直观。</div>'
        '</div>'
        '<div class="nutrition-spotlight-badge">AI 估计</div>'
        '</div>'
        f'<div class="nutrition-ring-grid">{"".join(rings)}</div>'
        f'<div class="nutrition-story">{escape(story)}</div>'
        '</section>'
        '</div>'
    )


def _interpolate_series(start: float, end: float, count: int, pattern: list[float]) -> list[float]:
    if count <= 1:
        return [round(end, 1)]
    values = []
    for idx in range(count):
        ratio = idx / (count - 1)
        base = start + (end - start) * ratio
        drift = pattern[idx % len(pattern)]
        values.append(round(base + drift, 1))
    return values


def _build_trend_data(so: dict, payload: dict, memory: dict, current_time_raw: str) -> dict:
    try:
        current_dt = datetime.fromisoformat(str(current_time_raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        current_dt = datetime.now()

    latest = so.get("latest_health_summary") or {}
    steps_value = _extract_numbers(latest.get("steps_today"))
    steps_now = steps_value[0] if steps_value else 1500
    glucose_value = _extract_numbers(latest.get("blood_glucose"))
    glucose_now = glucose_value[0] if glucose_value else 7.2

    ranges = {
        "7": {
            "days": 7,
            "steps": _interpolate_series(2600, steps_now, 7, [120, -60, 80, -90, 40, -50, 0]),
            "glucose": _interpolate_series(max(glucose_now - 0.2, 6.8), glucose_now, 7, [0.08, -0.04, 0.06, -0.02, 0.03, -0.05, 0]),
            "appetite": _interpolate_series(5.3, 4.2, 7, [0.2, -0.1, 0.15, -0.2, 0.1, -0.1, 0]),
            "insight": "最近 7 天里，营养和活动都需要更多支持。",
        },
        "14": {
            "days": 14,
            "steps": _interpolate_series(4000, steps_now, 14, [160, -110, 90, -140, 70, -80, 40]),
            "glucose": _interpolate_series(7.4, glucose_now, 14, [0.1, -0.06, 0.04, 0.02, -0.08, 0.06, -0.02]),
            "appetite": _interpolate_series(6.4, 4.2, 14, [0.25, -0.14, 0.18, -0.22, 0.1, -0.16, 0.05]),
            "insight": "过去 14 天里，活动量和食欲一起走低，今天更需要先稳住营养和体力。",
        },
        "30": {
            "days": 30,
            "steps": _interpolate_series(4300, steps_now, 30, [180, -120, 90, -150, 80, -70, 40, -40]),
            "glucose": _interpolate_series(7.1, glucose_now, 30, [0.08, -0.03, 0.05, -0.05, 0.04, -0.02, 0]),
            "appetite": _interpolate_series(6.8, 4.2, 30, [0.2, -0.08, 0.12, -0.16, 0.08, -0.1, 0.03, -0.05]),
            "insight": "从近 30 天看，恢复节奏变慢主要和食欲下降、活动减少有关。",
        },
        "90": {
            "days": 90,
            "steps": _interpolate_series(4700, steps_now, 12, [140, -90, 60, -80, 50, -40]),
            "glucose": _interpolate_series(6.9, glucose_now, 12, [0.05, -0.02, 0.04, -0.04, 0.03, -0.02]),
            "appetite": _interpolate_series(7.1, 4.2, 12, [0.15, -0.06, 0.08, -0.12, 0.06, -0.05]),
            "insight": "放到更长的恢复阶段看，近期下降更明显，因此更值得早点干预。",
        },
    }

    trend_data: dict[str, dict] = {}
    for key, spec in ranges.items():
        day_count = spec["days"]
        start_label = (current_dt - timedelta(days=day_count - 1)).strftime("%-m/%-d") if os.name != "nt" else (current_dt - timedelta(days=day_count - 1)).strftime("%m/%d").lstrip("0").replace("/0", "/")
        end_label = current_dt.strftime("%-m/%-d") if os.name != "nt" else current_dt.strftime("%m/%d").lstrip("0").replace("/0", "/")

        step_series = spec["steps"]
        glucose_series = spec["glucose"]
        appetite_series = spec["appetite"]

        trend_data[key] = {
            "axis_start": start_label,
            "axis_end": end_label,
            "insight": spec["insight"],
            "metrics": [
                {
                    "icon": "👟",
                    "label": "活动量",
                    "value": f'{int(round(step_series[-1]))} 步',
                    "delta": f'较起点 ↓ {int(round(step_series[0] - step_series[-1]))} 步',
                    "delta_direction": "down",
                    "copy": "这段时间步数持续走低，说明恢复期体力和疼痛管理都需要更多照顾。",
                    "values": [int(round(v)) for v in step_series],
                    "color": "#8b5cf6",
                },
                {
                    "icon": "🧪",
                    "label": "血糖",
                    "value": f'{glucose_series[-1]:.1f} mmol/L',
                    "delta": f'近段时间 {"↓" if glucose_series[-1] <= glucose_series[0] else "↑"} {abs(glucose_series[-1] - glucose_series[0]):.1f}',
                    "delta_direction": "down" if glucose_series[-1] <= glucose_series[0] else "up",
                    "copy": "血糖整体没有明显失控，但仍然需要和进食节奏、用药耐受一起看。",
                    "values": glucose_series,
                    "color": "#f59e0b",
                },
                {
                    "icon": "🥣",
                    "label": "食欲 / 体力",
                    "value": f'{appetite_series[-1]:.1f} / 10',
                    "delta": f'较起点 ↓ {(appetite_series[0] - appetite_series[-1]):.1f}',
                    "delta_direction": "down",
                    "copy": "食欲和体力下降会直接影响恢复速度，所以今天先把营养补上更重要。",
                    "values": appetite_series,
                    "color": "#10b981",
                },
            ],
        }
    return trend_data


def _render_trend_story() -> str:
    return (
        '<div id="trendOverviewAnchor" class="px-3 pt-3">'
        '<section class="trend-card">'
        '<div class="trend-card-head">'
        '<div>'
        '<div class="trend-card-title">恢复趋势</div>'
        '<div class="trend-card-copy">把最近的变化浓缩成更像 app 的趋势视图，方便一眼判断哪里需要优先跟进。</div>'
        '</div>'
        '<div class="trend-insight-chip" id="trendInsightChip">过去 14 天里，活动量和食欲一起走低。</div>'
        '</div>'
        '<div class="trend-range-tabs">'
        '<button class="trend-range-btn" data-range="7" onclick="renderTrendRange(\'7\')">7天</button>'
        '<button class="trend-range-btn active" data-range="14" onclick="renderTrendRange(\'14\')">14天</button>'
        '<button class="trend-range-btn" data-range="30" onclick="renderTrendRange(\'30\')">30天</button>'
        '<button class="trend-range-btn" data-range="90" onclick="renderTrendRange(\'90\')">90天</button>'
        '</div>'
        '<div id="trendMetricStack" class="trend-metric-stack mt-3"></div>'
        '</section>'
        '</div>'
    )


def _render_bottom_nav() -> str:
    items = [
        ("🏠", "首页", "homeAnchor", True),
        ("✅", "计划", "priorityPlanAnchor", False),
        ("🥗", "营养", "nutritionOverviewAnchor", False),
        ("📈", "趋势", "trendOverviewAnchor", False),
        ("🗂️", "概览", "statusAnchor", False),
    ]
    parts = []
    for icon, label, target_id, active in items:
        parts.append(
            f'<button class="bottom-tab{" active" if active else ""}" onclick="jumpToSection(\'{target_id}\')">'
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
    name = _extract_patient_name(memory, tone_profile)
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
        '<div class="hero-assistant-orb">🤖</div>'
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

    key_events = memory.get("key_events") or []
    surgery_event = next((ev for ev in key_events if ev.get("type") == "surgery"), None)
    progress_title = "本轮观察重点"
    progress_text = "当前以最近14天的恢复、营养和活动变化作为主要观察窗口。"
    if surgery_event:
        progress_title = "恢复阶段"
        progress_text = f'{_localize_zh_text(str(surgery_event.get("description") or ""))}后，当前更关注体力、营养和活动恢复。'

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
            text = _localize_zh_text(rec.get("text", ""))
            reason = _localize_zh_text(rec.get("reason", ""))
        else:
            text = _localize_zh_text(str(rec))
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
            f'onclick="saveLike(-1,\'priority\',\'{safe_text}\', this)">记为重点</button>'
            f'<button class="priority-task-btn secondary" data-day-idx="-1" data-meal-type="priority" '
            f'data-item-name="{safe_text}" data-default-label="稍后处理" data-active-label="已标稍后" '
            f'onclick="showFeedbackModal(-1,\'priority\',\'{safe_text}\', this)">稍后处理</button>'
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
    memory = payload.get("memory") or {}
    try:
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Template not found: {_TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)

    tone_profile = memory.get("tone_profile") or {}
    condition_ctx_name = tone_profile.get("condition_context") or "stable_routine"
    ctx = _CONDITION_CONTEXTS.get(condition_ctx_name, _CONDITION_CONTEXTS["stable_routine"])
    visible = ctx["show_sections"]

    if ctx["tone_override"]:
        tone_profile = {**tone_profile, "style": ctx["tone_override"]}

    key_events = memory.get("key_events") or []
    escalations = _check_escalations(key_events)

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
    patient_lat = loc.get("lat", 0)
    patient_lon = loc.get("lon", 0)

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
    maps_script = ""
    if "map" in visible:
        maps_script = (
            '<script type="text/javascript" '
            f'src="https://api.map.baidu.com/api?v=3.0&ak={escape(baidu_map_ak, quote=True)}"></script>'
        )
    map_section = _render_map_section(ai_map_msg, ai_map_msg_park, patient_lat, patient_lon)

    meal_json = json.dumps(_localize_zh_value(so.get("weekly_meal_plan") or []), ensure_ascii=False)

    patient_id = meta.get("user_id") or payload.get("user_id") or payload.get("patient_id") or "unknown"

    preferred_name = (tone_profile or {}).get("preferred_name") or ""
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
                f"onclick=\"saveLike(-1,'rec','{safe_text}', this)\">适合我</button>"
                f'<button class="feedback-btn feedback-skip" title="不适合我" data-day-idx="-1" data-meal-type="rec" '
                f'data-item-name="{safe_text}" data-default-label="不适合" data-active-label="已跳过" '
                f"onclick=\"showFeedbackModal(-1,'rec','{safe_text}', this)\">不适合</button>"
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

    card_defs = [
        ("guidance", "💚", "#d1fae5", "健康指导",
         lambda: _render_health_guidance(so.get("health_guidance") or {}, conditions, tone_profile=tone_profile)),
        ("memory", "🧠", "#e0e7ff", "健康记录",
         lambda: _render_memory(memory)),
        ("vitals", "📊", "#fef3c7", "最新健康数据",
         lambda: _vitals_subcards()),
        ("adherence", "📋", "#f3e8ff", "依从性概览",
         lambda: _adherence_subcards()),
        ("recommendations", "💡", "#dcfce7", "健康建议",
         lambda: _recs_subcards()),
        ("nutrition", "🥗", "#ecfdf5", "营养建议",
         lambda: (
             '<p style="font-size:0.95em;line-height:1.7;color:#334155;padding:8px 0">'
             + escape(_localize_zh_text(so.get("nutrition_advice") or "保持均衡营养，多摄入新鲜蔬菜，注意适量补水。"))
             + '</p>'
         )),
        ("diet_table", "📑", "#fff7ed", "疾病饮食对照",
         lambda: _render_diet_table(so.get("diet_table") or [])),
        ("cuisine", "🍜", "#fdf2f8", "口味偏好",
         lambda: (
             '<p class="text-sm text-slate-500 mb-3">选择您喜欢的菜系，'
             "后续膳食建议会尽量参考您的口味。</p>"
             '<div class="flex flex-wrap gap-2 mb-3" id="cuisineChips"></div>'
             '<div class="flex items-center gap-2">'
             '<input id="customCuisineInput" type="text" placeholder="添加其他菜系..." '
             'class="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2 '
             'focus:outline-none focus:border-emerald-400 focus:ring-1 focus:ring-emerald-200">'
             '<button onclick="addCustomCuisine()" class="px-3 py-2 rounded-lg bg-emerald-50 '
             'border border-emerald-200 text-emerald-700 text-sm font-medium hover:bg-emerald-100">'
             '+ 添加</button></div>'
         )),
        ("meal_plan", "📅", "#eff6ff", "一周膳食参考",
         lambda: (
             '<div class="flex gap-2 mb-4 overflow-x-auto pb-2" id="dayTabs"></div>'
             '<div id="mealContent"></div>'
         )),
        ("diet_tips", "✨", "#f0fdf4", "营养小贴士",
         lambda: _render_diet_tips(so.get("diet_tips") or [])),
        ("map", "🏥", "#f0f9ff", "附近医疗与公园",
         lambda: map_section),
        ("submit", "✓", "#ecfdf5", "提交偏好",
         lambda: (
             '<button id="exportFeedbackBtn" onclick="exportFeedbackJSON()" style="display:none" '
             'class="w-full px-6 py-3 rounded-full text-sm font-bold bg-emerald-600 text-white shadow-md '
             'hover:bg-emerald-700 active:scale-95 transition-all">'
             '✓ 提交我的偏好</button>'
             '<p class="text-xs text-slate-400 mt-2 text-center" id="submitHint" style="display:none">'
             '您的选择会用于下次生成更合适的建议</p>'
         )),
    ]

    vitals_data = so.get("latest_health_summary") or {}
    bp_preview = vitals_data.get("blood_pressure", "")
    hr_preview = vitals_data.get("heart_rate", "")
    vitals_preview = f"血压 {bp_preview}，心率 {hr_preview}" if bp_preview else "血压、心率、血糖等最新数据"

    guidance_data = so.get("health_guidance") or {}
    guidance_summary = _localize_zh_text(guidance_data.get("summary", "")) if isinstance(guidance_data, dict) else ""
    guidance_preview = (guidance_summary or "结合您的疾病和近期情况生成的个性化建议")[:80]
    if len(guidance_summary) > 80:
        guidance_preview += "..."

    card_summaries = {
        "guidance": guidance_preview,
        "memory": "您的长期资料、近期趋势和关键事件",
        "vitals": vitals_preview,
        "adherence": "近期用药、营养、运动和监测情况",
        "recommendations": "适合当前情况的可执行建议",
        "nutrition": "营养重点，以及为什么这样安排",
        "diet_table": "不同疾病对应的饮食原则",
        "cuisine": "告诉我们您喜欢的口味",
        "meal_plan": "一周早、中、晚膳食参考",
        "diet_tips": "更容易坚持的小型营养提醒",
        "map": "附近医院和公园",
        "submit": "保存您的反馈和偏好",
    }

    cards_html_parts = []
    for section_key, icon, bg_color, title, render_fn in card_defs:
        if section_key not in visible:
            continue
        content = render_fn()
        if not content or not content.strip():
            continue

        summary = card_summaries.get(section_key, "")
        cards_html_parts.append(
            f'<div class="section-card" data-section="{section_key}">'
            f'<div class="section-card-header">'
            f'<div class="section-card-icon" style="background:{bg_color}">{icon}</div>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="section-card-title">{title}</div>'
            f'<div class="section-card-summary">{summary}</div>'
            f'</div>'
            f'<div class="section-card-arrow">&#9662;</div>'
            f'</div>'
            f'<div class="section-card-body">{content}</div>'
            f'</div>'
        )

    cards_html = "\n".join(cards_html_parts)

    nutrition_text = (
        '<div class="rounded-xl bg-emerald-50 border border-emerald-100 px-4 py-4 '
        'text-[0.95em] leading-7 text-slate-700">'
        + escape(_localize_zh_text(so.get("nutrition_advice") or "保持均衡营养，多摄入新鲜蔬菜，注意适量补水。"))
        + '</div>'
    )
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
    )
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
    nutrition_spotlight_html = _render_nutrition_spotlight(so)
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
    trend_story_html = _render_trend_story()
    trend_data_json = json.dumps(_build_trend_data(so, payload, memory, meta.get("current_time") or ""), ensure_ascii=False)
    bottom_nav_html = _render_bottom_nav()

    regrouped_cards = []

    guidance_bundle_html = "".join([
        _module_subsection("为什么这些建议和您有关", "先把您的病史、当前用药和最近指标放在前面，后面的建议会更容易看懂。", _render_personalized_context(so, payload, memory)) if ("guidance" in visible or "recommendations" in visible) else "",
        _module_subsection("健康指导", "结合您最近的感受，整理出现在最值得留意的重点。", _render_health_guidance(so.get("health_guidance") or {}, conditions, tone_profile=tone_profile)) if "guidance" in visible else "",
        _module_subsection("健康建议", "这些是现在更适合您去做的小步骤。", _recs_subcards()) if "recommendations" in visible else "",
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
    if "adherence" in visible:
        adherence_html = _adherence_subcards()
        if adherence_html.strip():
            adherence_body_parts.append(
                _module_subsection("执行情况", "看看最近用药、营养、活动和监测情况。", adherence_html)
            )
    key_events_html = _render_key_events(memory) if "memory" in visible else ""
    if key_events_html.strip():
        adherence_body_parts.append(
            _module_subsection("关键事件", "把最近的重要记录放在一起，前后变化会更好理解。", key_events_html)
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

    nutrition_bundle_html = "".join([
        _module_subsection("营养建议", "先看这段时间哪些营养安排更适合您。", nutrition_text) if "nutrition" in visible else "",
        _module_subsection("疾病饮食对照", "哪些食物更适合，哪些先少吃一点。", _render_diet_table(so.get("diet_table") or [])) if "diet_table" in visible else "",
        _module_subsection("营养小贴士", "都是些更容易用得上的小提醒。", _render_diet_tips(so.get("diet_tips") or [])) if "diet_tips" in visible else "",
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
        _module_subsection("口味偏好", "选一些您平时更喜欢的口味，后面的膳食建议会更贴近您。", cuisine_html) if "cuisine" in visible else "",
        _module_subsection("一周膳食参考", "给您一些这周更容易参考的早、中、晚餐搭配。", meal_plan_html) if "meal_plan" in visible else "",
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

    if "map" in visible and map_section.strip():
        regrouped_cards.append(_section_card("map", "🏥", "#f0f9ff", "附近地点", "附近医院和公园，都可以在这里看。", map_section))

    cards_html = "\n".join(part for part in regrouped_cards if part)

    report_title = "依从性报告"
    html = template.format(
        report_title=report_title,
        header_greeting=header_greeting,
        layout_class=layout_class,
        patient_id=patient_id,
        current_time=current_time,
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
        escalation_html=_render_escalation_banner(escalations) if "escalation" in visible else "",
        ai_message_html=_render_ai_message(so),
        cards_html=cards_html,
        submit_cta_html=submit_cta_html,
        bottom_nav_html=bottom_nav_html,
        meal_data_json=meal_json,
        trend_data_json=trend_data_json,
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

    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
