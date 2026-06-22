#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "output" / "clinical-trial-inputs"
OUTPUT_DIR = ROOT / "output" / "clinical-trial-pages"
INPUT_EXPORT_DIR = OUTPUT_DIR / "inputs"

ADHERENCE_ZH_RENDERER = ROOT / "adherence-report-zh" / "scripts" / "render_report.py"
ADHERENCE_EN_RENDERER = ROOT / "adherence-report-en" / "scripts" / "render_report.py"
EMERGENCY_ZH_RENDERER = ROOT / "emergency-instruction-zh" / "scripts" / "render_instruction.py"
EMERGENCY_EN_RENDERER = ROOT / "emergency-instruction-en" / "scripts" / "render_instruction.py"


EMILY_GI_GUIDANCE_ZH = (
    "由于 ADC 靶点在消化道广泛分布，或肠道黏膜更新较快，这类恶心、腹泻和进食减少很常见。"
    "这几天的重点是把进食拆小、把补液做足、把血糖波动和脱水一起盯住。"
)
EMILY_GI_GUIDANCE_EN = (
    "Because ADC targets are widely expressed in the gastrointestinal tract, or because the gut lining turns over quickly, "
    "nausea, diarrhea, and reduced intake can show up early. The immediate priorities are smaller meals, steady hydration, "
    "and close tracking of both glucose swings and dehydration risk."
)

SHARED_ADC_NUTRITION_ZH = (
    "ADC（抗体偶联药物）由于将靶向抗体与强效小分子细胞毒素结合，在杀伤肿瘤的同时，"
    "也可能因为脱靶效应或毒素释放，引发胃肠道、肝肾、骨髓及肺部等毒性反应。"
    "科学补充营养的核心原则是：高蛋白、易消化、少食多餐，并根据具体副作用做针对性调整。"
)
SHARED_ADC_NUTRITION_EN = (
    "Antibody-drug conjugates (ADCs) combine a targeted antibody with a potent cytotoxic payload. "
    "While they can attack tumors effectively, off-target effects or payload release may also trigger gastrointestinal, "
    "hepatic, renal, marrow, or lung toxicity. The core nutrition principles are: higher protein, easy digestion, "
    "small frequent meals, and side-effect-specific adjustments."
)
SHARED_ADC_GI_DETAIL_ZH = (
    "由于 ADC 靶点在消化道广泛分布，或肠道黏膜更新较快，恶心、腹泻和进食减少都很常见。"
    "建议少量多餐、保持清淡，避免油腻、油炸及辛辣刺激性食物，每日可进食 5 到 6 顿、避免过饱。"
    "食物优先选择蒸鱼、水煮鸡胸肉、豆腐、蒸蛋等优质高蛋白且容易消化的搭配，并多补充富含维生素的瓜类蔬菜。"
    "若腹泻明显，要警惕脱水与电解质流失，可饮用口服补液盐，或米汤加少量盐；此时先避开牛奶和乳制品，"
    "以免乳糖进一步增加肠道负担。若恶心严重，避免在进餐时饮用大量液体，汤水等流食尽量放在餐前或餐后 30 分钟以上。"
)
SHARED_ADC_GI_DETAIL_EN = (
    "Because ADC targets may be broadly expressed in the gastrointestinal tract, or because the gut lining turns over quickly, "
    "nausea, diarrhea, and reduced intake are common. Use small, frequent, bland meals; avoid greasy, fried, and spicy foods; "
    "and aim for 5 to 6 eating moments per day without overfilling. Prioritize steamed fish, poached chicken breast, tofu, "
    "steamed egg, and vitamin-rich gourd vegetables for higher-protein, easier-to-digest choices. If diarrhea becomes significant, "
    "watch for dehydration and electrolyte loss and use oral rehydration solution, or lightly salted rice broth. Avoid milk and dairy "
    "because lactose can worsen gut burden. If nausea is severe, avoid large amounts of fluid during meals and move soups and other liquid foods "
    "to at least 30 minutes before or after eating."
)
SHARED_ADC_GUIDANCE_TIPS_ZH = [
    {"text": "把三餐拆成 5 到 6 次少量进食", "why": "少量多餐通常比硬吃大餐更容易完成，也更不容易恶心或腹胀。"},
    {"text": "优先补高蛋白、好消化的软食", "why": "蒸鱼、鸡胸肉、豆腐、蒸蛋这类食物能在总量不多时尽量保住营养密度。"},
]
SHARED_ADC_GUIDANCE_TIPS_EN = [
    {"text": "Break meals into 5 to 6 small eating moments", "why": "Small frequent intake is usually easier to tolerate than forcing larger meals and is less likely to worsen nausea or fullness."},
    {"text": "Lead with higher-protein, easy-to-digest softer foods", "why": "Steamed fish, chicken breast, tofu, and steamed egg help preserve nutrition even when total intake is limited."},
]
SHARED_ADC_DIET_TIPS_ZH = [
    {"icon": "🍽️", "title": "少量多餐", "detail": "每日可进食 5 到 6 顿，避免一次吃得太多，减轻恶心、腹胀和餐后不适。"},
    {"icon": "🥚", "title": "高蛋白易消化", "detail": "蒸鱼、水煮鸡胸肉、豆腐、蒸蛋等更适合作为 ADC 治疗期的基础蛋白来源。"},
    {"icon": "🧂", "title": "腹泻时补液补盐", "detail": "严重腹泻会带走水分和电解质，可使用口服补液盐，或米汤加少量盐。"},
    {"icon": "🥛", "title": "腹泻时先避开乳制品", "detail": "牛奶和乳制品中的乳糖可能进一步增加肠道负担。"},
    {"icon": "🥣", "title": "恶心重时错开喝流食", "detail": "如果恶心明显，汤水等流食尽量安排在餐前或餐后 30 分钟以上。"},
]
SHARED_ADC_DIET_TIPS_EN = [
    {"icon": "🍽️", "title": "Small frequent meals", "detail": "Aim for 5 to 6 eating moments per day instead of one or two heavy meals to reduce nausea, bloating, and post-meal discomfort."},
    {"icon": "🥚", "title": "Higher-protein and easy to digest", "detail": "Steamed fish, poached chicken breast, tofu, and steamed egg are practical ADC-treatment protein staples."},
    {"icon": "🧂", "title": "Replace fluids and salt during diarrhea", "detail": "Significant diarrhea causes fluid and electrolyte loss, so use oral rehydration solution or lightly salted rice broth."},
    {"icon": "🥛", "title": "Pause dairy if diarrhea is active", "detail": "Lactose in milk and dairy can add to gut burden when diarrhea is already present."},
    {"icon": "🥣", "title": "Separate larger liquids from meals if nausea is strong", "detail": "Move soups and other liquid foods to at least 30 minutes before or after eating when nausea is severe."},
]
SHARED_ADC_DIET_ROW_ZH = {
    "condition": "ADC 治疗期通用饮食",
    "principle": "高蛋白、易消化、少量多餐",
    "recommend": "蒸鱼、鸡胸肉、豆腐、蒸蛋、清淡瓜类蔬菜、口服补液盐",
    "avoid": "油炸辛辣、过饱、大量餐中饮液、腹泻时乳制品",
}
SHARED_ADC_DIET_ROW_EN = {
    "condition": "General nutrition during ADC treatment",
    "principle": "Higher protein, easy digestion, small frequent meals",
    "recommend": "Steamed fish, chicken breast, tofu, steamed egg, mild gourd vegetables, oral rehydration solution",
    "avoid": "Greasy spicy foods, overeating, large liquids during meals, dairy when diarrhea is active",
}
SHARED_ADC_EMERGENCY_ACTION_ZH = (
    "饮食先按 ADC 胃肠道友好的方式执行：少量多餐、清淡高蛋白；若有腹泻要补口服补液盐（或米汤加少量盐），"
    "若恶心明显则把大量液体和汤水放到餐前或餐后 30 分钟以上。"
)
SHARED_ADC_EMERGENCY_ACTION_EN = (
    "Use an ADC-friendly eating pattern right away: small frequent bland higher-protein meals; if diarrhea is present, add oral rehydration solution or lightly salted rice broth; "
    "if nausea is strong, move larger liquids and soups to at least 30 minutes before or after meals."
)


@dataclass(frozen=True)
class PatientCopy:
    scenario_id: str
    file_stem: str
    display_name: str
    conditions_zh: list[str]
    conditions_en: list[str]
    risk_tags_zh: list[str]
    risk_tags_en: list[str]
    ai_sections_zh: list[dict[str, str]]
    ai_sections_en: list[dict[str, str]]
    adherence_zh: dict[str, dict[str, str]]
    adherence_en: dict[str, dict[str, str]]
    health_guidance_zh: dict[str, Any]
    health_guidance_en: dict[str, Any]
    nutrition_zh: str
    nutrition_en: str
    diet_table_zh: list[dict[str, str]]
    diet_table_en: list[dict[str, str]]
    meal_plan_zh: list[dict[str, Any]]
    meal_plan_en: list[dict[str, Any]]
    diet_tips_zh: list[dict[str, str]]
    diet_tips_en: list[dict[str, str]]
    extra_recommendations_zh: list[dict[str, str]]
    extra_recommendations_en: list[dict[str, str]]
    emergency_note_zh: str
    emergency_note_en: str
    emergency_actions_zh: list[str]
    emergency_actions_en: list[str]
    emergency_monitoring_zh: dict[str, str]
    emergency_monitoring_en: dict[str, str]


PATIENT_OVERRIDES: dict[str, PatientCopy] = {
    "clinical_trial_michael": PatientCopy(
        scenario_id="clinical_trial_michael",
        file_stem="michael",
        display_name="Michael Chen",
        conditions_zh=["高血压", "冠心病", "化疗期间"],
        conditions_en=["Hypertension", "Coronary artery disease", "During chemotherapy"],
        risk_tags_zh=["阵发性心悸", "乏力", "轻度活动后气短", "心率/血压漂移"],
        risk_tags_en=["episodic palpitations", "fatigue", "mild exertional dyspnea", "HR/BP drift"],
        ai_sections_zh=[
            {"type": "good_news", "title": "目前没有急性失稳信号", "content": "目前没有胸痛、晕厥或静息气短，说明虽然需要尽快复核，但暂时还不是最危险的状态。"},
            {"type": "attention", "title": "这更像早期心脏毒性信号", "content": "在既往冠心病和基线 LVEF 低限的背景下，新的心悸、乏力和血压波动，不能简单按普通疲劳看待。"},
            {"type": "plan", "title": "接下来要尽快做什么", "content": "24 小时内优先补齐心电图、超声心动图和心率血压趋势记录，帮助试验团队判断下一周期是否需要调整。"},
            {"type": "encouragement", "title": "先把记录做扎实", "content": "把每次心悸持续多久、是否伴随气短、胸闷或头晕记下来，会让下一步判断快很多。"},
        ],
        ai_sections_en=[
            {"type": "good_news", "title": "No immediate collapse signal", "content": "There is no chest pain, fainting, or breathlessness at rest right now, so this still looks controllable with prompt follow-up."},
            {"type": "attention", "title": "This behaves like an early cardiac toxicity signal", "content": "With prior CAD and a low-normal baseline LVEF, new palpitations plus fatigue and BP drift should not be dismissed as routine treatment tiredness."},
            {"type": "plan", "title": "What should happen next", "content": "Within the next 24 hours, the most useful steps are ECG, echo, and a clear HR/BP log to guide the trial team before the next dose."},
            {"type": "encouragement", "title": "Good records will help", "content": "Tracking how long each palpitation lasts, and whether it comes with shortness of breath or dizziness, will make the next decision much easier."},
        ],
        adherence_zh={
            "medication": {
                "status": "基本按时",
                "issues": "患者表示常规药物持续在服用，没有明显漏服。",
                "adjustments": "继续按原处方服药，若心悸延长或加重，不要自行增减 β 受体阻滞剂，先联系试验团队。",
            },
            "appetite": {
                "status": "轻度受影响",
                "cause_if_known": "乏力与轻度气短可能让整体进食与日常节奏放慢。",
                "suggestions": "选择低盐、温和、容易咀嚼和消化的餐食，减少浓茶、咖啡和高盐加工食品。",
            },
            "exercise": {
                "status": "需要放缓",
                "barriers": "活动后气短和心悸提示近期不适合突然增加运动量。",
                "plan": "先以平地短距离步行为主，避免爬楼、快走和会诱发心悸的强度。",
            },
            "monitoring": {
                "status": "需要加强",
                "gaps": "需要更系统记录心率、血压、心悸持续时间和是否伴随胸闷、头晕、踝部水肿。",
            },
        },
        adherence_en={
            "medication": {
                "status": "Mostly on track",
                "issues": "He reports continuing his regular medications without obvious missed doses.",
                "adjustments": "Keep taking them as prescribed; if palpitations become sustained or more intense, do not self-adjust the beta blocker before speaking with the trial team.",
            },
            "appetite": {
                "status": "Mildly affected",
                "cause_if_known": "Fatigue and exertional symptoms can slow down normal eating and hydration habits.",
                "suggestions": "Prefer lower-salt, gentle meals and avoid heavy caffeine, very salty packaged foods, and large late meals.",
            },
            "exercise": {
                "status": "Should be scaled back",
                "barriers": "Palpitations and mild exertional dyspnea make sudden exercise increases a poor fit this week.",
                "plan": "Keep activity light and steady, with short flat walks instead of stairs, brisk walking, or anything that provokes symptoms.",
            },
            "monitoring": {
                "status": "Needs tighter follow-up",
                "gaps": "He needs a clearer log of HR, BP, palpitation duration, and whether chest pressure, dizziness, or ankle swelling appear.",
            },
        },
        health_guidance_zh={
            "summary": "这份页面更适合把 Michael 当前的情况理解为“需要尽快客观化的早期心脏信号”，重点不是硬扛，而是及时把证据补齐。",
            "tips": [
                {"text": "把心悸发生时间和持续时长记下来", "why": "短暂自限和持续不缓解，对下一步处理意义完全不同。"},
                {"text": "今天先避免高强度活动和爬楼", "why": "近期活动后气短和心率漂移，提示心脏负荷不适合再往上加。"},
                {"text": "吃得清淡、规律补水、减少刺激性饮品", "why": "稳住交感神经兴奋和血压波动，比硬撑更重要。"},
            ],
        },
        health_guidance_en={
            "summary": "This page is best read as an early cardiac signal that needs to be objectified quickly, not something to push through and ignore.",
            "tips": [
                {"text": "Write down each palpitation episode and how long it lasts", "why": "Brief self-limited episodes and prolonged episodes lead to very different next steps."},
                {"text": "Avoid stairs and sudden heavy exertion today", "why": "Recent exertional dyspnea and HR drift suggest the current cardiac load should stay low."},
                {"text": "Use gentle meals, regular fluids, and less stimulant intake", "why": "Steadier hydration and less sympathetic stimulation may reduce extra HR and BP fluctuation."},
            ],
        },
        nutrition_zh="近期饮食以低盐、适度蛋白、少刺激为主。优先选择蒸鱼、鸡胸肉、豆腐、燕麦、软米饭和煮熟蔬菜，避免浓咖啡、能量饮料、重口味外卖和过咸汤面。",
        nutrition_en="For the next few days, aim for lower-salt, moderate-protein, low-stimulant meals. Steamed fish, chicken breast, tofu, oatmeal, soft rice, and cooked vegetables fit better than energy drinks, strong coffee, or very salty take-out foods.",
        diet_table_zh=[
            {"condition": "高血压", "principle": "低盐、规律补水", "recommend": "蒸鱼、燕麦、熟蔬菜、清汤", "avoid": "腌制品、浓汤、重盐外卖"},
            {"condition": "冠心病/心悸风险", "principle": "减少刺激与大起大落", "recommend": "少量多餐、温水、低咖啡因饮品", "avoid": "浓咖啡、能量饮料、暴饮暴食"},
            {"condition": "化疗期恢复", "principle": "足够蛋白与稳定能量", "recommend": "鸡胸肉、豆腐、蒸蛋、软米饭", "avoid": "油炸高脂餐、深夜重餐"},
        ],
        diet_table_en=[
            {"condition": "Hypertension", "principle": "Lower sodium and steady hydration", "recommend": "Steamed fish, oatmeal, cooked vegetables, light soups", "avoid": "Pickled foods, salty broths, heavy take-out"},
            {"condition": "CAD / palpitation risk", "principle": "Reduce stimulants and extremes", "recommend": "Small regular meals, water, low-caffeine drinks", "avoid": "Strong coffee, energy drinks, very large meals"},
            {"condition": "During chemotherapy", "principle": "Enough protein with stable energy", "recommend": "Chicken breast, tofu, steamed egg, soft rice", "avoid": "Fried high-fat meals and very late heavy dinners"},
        ],
        meal_plan_zh=[
            {
                "day": "第1天",
                "breakfast": [{"name": "燕麦配蒸蛋", "icon": "🥣", "condition": "高血压", "benefit": "温和、低盐、帮助稳定上午能量"}],
                "lunch": [{"name": "清蒸鱼配软米饭", "icon": "🐟", "condition": "冠心病", "benefit": "低脂优质蛋白，减少心血管负担"}],
                "dinner": [{"name": "鸡胸肉蔬菜汤", "icon": "🍲", "condition": "化疗期间", "benefit": "补水同时补充蛋白和熟蔬菜"}],
            },
            {
                "day": "第2天",
                "breakfast": [{"name": "香蕉燕麦杯", "icon": "🍌", "condition": "乏力", "benefit": "容易入口，避免空腹太久"}],
                "lunch": [{"name": "豆腐青菜面", "icon": "🍜", "condition": "高血压", "benefit": "用少盐汤底保留水分和碳水"}],
                "dinner": [{"name": "蒸鸡肉南瓜泥", "icon": "🍗", "condition": "化疗期间", "benefit": "软烂好消化，晚间不过饱"}],
            },
            {
                "day": "第3天",
                "breakfast": [{"name": "酸奶替换为温豆浆配全麦吐司", "icon": "🍞", "condition": "心悸风险", "benefit": "避免高糖刺激，保持早餐规律"}],
                "lunch": [{"name": "三文鱼藜麦碗", "icon": "🥗", "condition": "冠心病", "benefit": "更有利于心血管与恢复期蛋白补充"}],
                "dinner": [{"name": "豆腐蒸蛋配西兰花", "icon": "🥚", "condition": "高血压", "benefit": "低盐、好消化，也利于晚间休息"}],
            },
        ],
        meal_plan_en=[
            {
                "day": "Day 1",
                "breakfast": [{"name": "Oatmeal with steamed egg", "icon": "🥣", "condition": "Hypertension", "benefit": "Gentle, lower-salt, and steady for the morning"}],
                "lunch": [{"name": "Steamed fish with soft rice", "icon": "🐟", "condition": "Cardiac risk", "benefit": "Lean protein with less cardiovascular load"}],
                "dinner": [{"name": "Chicken and vegetable soup", "icon": "🍲", "condition": "During chemotherapy", "benefit": "Adds fluids, protein, and cooked vegetables in one meal"}],
            },
            {
                "day": "Day 2",
                "breakfast": [{"name": "Banana oatmeal cup", "icon": "🍌", "condition": "Fatigue", "benefit": "Easy to tolerate and helps avoid a long fasting stretch"}],
                "lunch": [{"name": "Tofu greens noodle bowl", "icon": "🍜", "condition": "Hypertension", "benefit": "Uses a lighter broth while keeping fluids and carbs up"}],
                "dinner": [{"name": "Steamed chicken with pumpkin mash", "icon": "🍗", "condition": "During chemotherapy", "benefit": "Soft, digestible, and not too heavy at night"}],
            },
            {
                "day": "Day 3",
                "breakfast": [{"name": "Warm soy milk with whole-wheat toast", "icon": "🍞", "condition": "Palpitation risk", "benefit": "Regular breakfast without a heavy sugar or caffeine load"}],
                "lunch": [{"name": "Salmon and quinoa bowl", "icon": "🥗", "condition": "CAD", "benefit": "Helpful for protein and heart-friendly fats"}],
                "dinner": [{"name": "Tofu steamed egg with broccoli", "icon": "🥚", "condition": "Hypertension", "benefit": "Low-salt, easy to digest, and evening-friendly"}],
            },
        ],
        diet_tips_zh=[
            {"icon": "🫗", "title": "补水要分散进行", "detail": "不要等口渴才喝，全天少量多次补水更有利于减少心率波动。"},
            {"icon": "☕", "title": "这几天减少刺激物", "detail": "浓咖啡、能量饮料和过量酒精都可能让心悸更明显。"},
            {"icon": "🧂", "title": "盐味再降一点", "detail": "血压已经有漂移，能少一点咸味，就给药物多一点发挥空间。"},
            {"icon": "📝", "title": "把症状和饮食放在同一本记录里", "detail": "有些人会发现大餐、熬夜或咖啡因与心悸发生时间有关。"},
        ],
        diet_tips_en=[
            {"icon": "🫗", "title": "Spread fluids through the day", "detail": "Small frequent drinks work better than waiting until you are very thirsty."},
            {"icon": "☕", "title": "Scale back stimulants", "detail": "Strong coffee, energy drinks, and excess alcohol can make palpitations feel worse."},
            {"icon": "🧂", "title": "Trim sodium a little more", "detail": "BP is already drifting, so lower-salt meals give the medication more room to work."},
            {"icon": "📝", "title": "Track food and symptoms together", "detail": "Some people notice palpitations cluster after large meals, poor sleep, or caffeine."},
        ],
        extra_recommendations_zh=[
            {"text": "今天开始记录每次心悸持续多久", "reason": "这是区分短暂波动还是需要升级处理的重要线索。", "category": "monitoring"},
            {"text": "如果出现胸痛、晕厥或静息气短，直接升级就医", "reason": "这些都是需要立刻跳出“居家观察”路径的红线信号。", "category": "monitoring"},
        ],
        extra_recommendations_en=[
            {"text": "Start timing each palpitation episode today", "reason": "Duration is one of the fastest ways to separate a short-lived fluctuation from something that needs escalation.", "category": "monitoring"},
            {"text": "Escalate immediately for chest pain, fainting, or breathlessness at rest", "reason": "Those are red-flag symptoms that move this out of the home-observation lane.", "category": "monitoring"},
        ],
        emergency_note_zh="试验团队建议在 24 小时内完成心电图、超声心动图和趋势记录复核；在结果明确前，按早期心脏毒性信号处理更稳妥。",
        emergency_note_en="The trial team should review ECG, echo, and the HR/BP trend within 24 hours; until then, it is safer to treat this as an early cardiac toxicity signal.",
        emergency_actions_zh=[
            "今天开始记录心悸持续时间、发生时的心率/血压，以及是否伴随胸闷、头晕或气短。",
            "继续按原处方服用美托洛尔和降压药，不要自行加量或停药。",
            "若心悸持续数分钟以上、出现胸痛、晕厥、静息气短或踝部肿胀，立即联系试验团队或前往急诊。",
        ],
        emergency_actions_en=[
            "Start a log today with palpitation duration, HR/BP at the time, and whether chest pressure, dizziness, or shortness of breath appears.",
            "Keep taking metoprolol and blood-pressure medications as prescribed; do not self-adjust the dose.",
            "If palpitations become sustained, or chest pain, fainting, breathlessness at rest, or ankle swelling appears, contact the trial team or emergency care immediately.",
        ],
        emergency_monitoring_zh={
            "what_to_monitor": "心率、血压、心悸持续时间、活动后气短、踝部水肿",
            "frequency": "今天开始每次发作时记录，至少早晚各复测一次",
            "next_checkin": "24 小时内完成试验团队/心内方向复核",
        },
        emergency_monitoring_en={
            "what_to_monitor": "Heart rate, blood pressure, palpitation duration, exertional dyspnea, and ankle swelling",
            "frequency": "Log each episode today and recheck at least morning and evening",
            "next_checkin": "Trial-team or cardiology review within 24 hours",
        },
    ),
    "clinical_trial_emily": PatientCopy(
        scenario_id="clinical_trial_emily",
        file_stem="emily",
        display_name="Emily Carter",
        conditions_zh=["2型糖尿病", "化疗期间"],
        conditions_en=["Type 2 diabetes", "During chemotherapy"],
        risk_tags_zh=["恶心", "进食减少", "体位性头晕", "血糖向低值漂移"],
        risk_tags_en=["nausea", "poor oral intake", "orthostatic dizziness", "glucose drifting low"],
        ai_sections_zh=[
            {"type": "good_news", "title": "目前还来得及在家里主动处理", "content": "现在最重要的是尽快把补液、止吐和血糖监测做起来，在症状升级前把风险压住。"},
            {"type": "attention", "title": "这不是单纯胃口差", "content": "在 ADC 背景下，恶心和吃不下会同时带来脱水和血糖失衡，对有糖尿病的人尤其需要提前介入。"},
            {"type": "plan", "title": "处理顺序", "content": "先用好止吐药、改成少量多餐，再同步盯住体位性血压、尿量和指尖血糖。"},
            {"type": "encouragement", "title": "目标不是硬吃，而是稳住", "content": "哪怕每次只吃几口、每次只喝几口，只要能慢慢把液体和热量补回来，就是有效进展。"},
        ],
        ai_sections_en=[
            {"type": "good_news", "title": "There is still time to get ahead of this at home", "content": "The priority is to control nausea, restore fluids, and monitor glucose before this becomes a bigger dehydration or hypoglycemia event."},
            {"type": "attention", "title": "This is more than a poor appetite day", "content": "In an ADC setting, nausea plus poor intake creates two risks at once for a diabetic patient: dehydration and unstable glucose."},
            {"type": "plan", "title": "Order of operations", "content": "Use the antiemetic early, switch to small frequent intake, and track orthostatic BP, urine output, and fingerstick glucose together."},
            {"type": "encouragement", "title": "The goal is stability, not forcing big meals", "content": "Even a few bites and a few sips at a time count if they help fluids and calories slowly come back up."},
        ],
        adherence_zh={
            "medication": {
                "status": "需要动态调整",
                "issues": "进食减少时继续使用二甲双胍，会把低血糖和脱水风险一起推高。",
                "adjustments": "止吐和进食恢复前，务必尽快和试验团队确认是否需要暂缓二甲双胍或调整用药时机。",
            },
            "appetite": {
                "status": "明显下降",
                "cause_if_known": "ADC 相关胃肠道毒性叠加既往化疗后恶心史，近期饮水和进食量都下降。",
                "suggestions": "改成 5 到 6 次少量进食，用温热、清淡、软烂、高蛋白食物先把能量和液体补回来。",
            },
            "exercise": {
                "status": "暂不适合增加",
                "barriers": "体位性头晕和轻度心动过速提示容量不足，现阶段先以安全起身和短距离活动为主。",
                "plan": "起身前先坐床边缓一会儿，今天不安排额外运动量。",
            },
            "monitoring": {
                "status": "需要立即强化",
                "gaps": "要同步记录餐前后血糖、饮水量、尿量、体位性血压心率和体重变化。",
            },
        },
        adherence_en={
            "medication": {
                "status": "Needs dynamic adjustment",
                "issues": "Continuing metformin while intake is poor can push both dehydration and low-glucose risk higher.",
                "adjustments": "Before intake recovers, the trial team should clarify whether metformin should be held or retimed.",
            },
            "appetite": {
                "status": "Clearly reduced",
                "cause_if_known": "Likely DXd-class GI toxicity layered on top of a known history of chemotherapy-related nausea.",
                "suggestions": "Shift to 5 to 6 small eating opportunities with warm, bland, softer, higher-protein foods.",
            },
            "exercise": {
                "status": "Not ready to increase",
                "barriers": "Orthostatic dizziness and mild tachycardia suggest volume depletion, so safety comes before extra activity.",
                "plan": "Pause before standing, keep movement short and supervised, and skip intentional exercise today.",
            },
            "monitoring": {
                "status": "Needs immediate tightening",
                "gaps": "Track pre/post-meal glucose, fluid intake, urine output, orthostatic BP/HR, and day-to-day weight change together.",
            },
        },
        health_guidance_zh={
            "summary": "Emily 现在的核心不是“吃不下”这一件事，而是 ADC 胃肠道毒性、脱水和糖尿病血糖波动正在互相放大，需要同时处理。",
            "tips": [
                {"text": "把三餐拆成 5 到 6 次少量进食", "why": "少量多餐比硬吃一整餐更容易缓解恶心，也更利于血糖稳定。"},
                {"text": "优先用蒸鱼、鸡胸肉、豆腐、蒸蛋这类高蛋白软食", "why": "这些食物更容易消化，也能在吃得不多时提高营养密度。"},
                {"text": "严重恶心时，把汤水放到餐前或餐后 30 分钟", "why": "进餐时大量饮液会让胃更胀、更容易反胃。"},
            ],
        },
        health_guidance_en={
            "summary": "Emily's problem is not just 'poor appetite' — ADC GI toxicity, dehydration, and diabetes-related glucose swings are amplifying one another and need to be managed together.",
            "tips": [
                {"text": "Break meals into 5 to 6 small eating moments", "why": "Small frequent intake is often easier to tolerate than forcing one full meal and can smooth glucose swings."},
                {"text": "Prioritize steamed fish, chicken breast, tofu, and steamed egg", "why": "They are easier to digest and add more protein when total intake is low."},
                {"text": "If nausea is strong, move soups and larger fluids away from meals", "why": "Drinking a lot during meals can worsen fullness and gagging."},
            ],
        },
        nutrition_zh=EMILY_GI_GUIDANCE_ZH + " 少量多餐与清淡饮食很关键：避免油腻、油炸和辛辣刺激食物；优先选择蒸鱼、水煮鸡胸肉、豆腐、蒸蛋和富含维生素的瓜类蔬菜。",
        nutrition_en=EMILY_GI_GUIDANCE_EN + " Small frequent bland meals matter most: avoid greasy, fried, and spicy foods; prefer steamed fish, poached chicken breast, tofu, steamed egg, and vitamin-rich gourd vegetables.",
        diet_table_zh=[
            {"condition": "ADC 胃肠道毒性", "principle": "清淡、软烂、少量多餐", "recommend": "蒸蛋、豆腐、米粥、清蒸鱼、鸡胸肉", "avoid": "油炸、辛辣、重口味、特别油腻的菜"},
            {"condition": "脱水/腹泻风险", "principle": "补液和电解质并重", "recommend": "口服补液盐、米汤加少量盐、清汤", "avoid": "只喝甜饮料、不补盐分"},
            {"condition": "糖尿病合并进食差", "principle": "平稳补碳水、避免空腹硬扛", "recommend": "少量主食配蛋白、定时测糖", "avoid": "长时间不吃又照常降糖用药"},
        ],
        diet_table_en=[
            {"condition": "ADC GI toxicity", "principle": "Bland, soft, small frequent intake", "recommend": "Steamed egg, tofu, rice porridge, steamed fish, chicken breast", "avoid": "Greasy, fried, spicy, and very rich foods"},
            {"condition": "Dehydration / diarrhea risk", "principle": "Replace fluids and electrolytes together", "recommend": "Oral rehydration solution, lightly salted rice broth, clear soups", "avoid": "Only sugary drinks without any electrolyte replacement"},
            {"condition": "Diabetes with poor intake", "principle": "Steady carbs without long fasting", "recommend": "Small starch portions paired with protein and scheduled glucose checks", "avoid": "Long fasting while taking usual glucose-lowering medication unchanged"},
        ],
        meal_plan_zh=[
            {
                "day": "第1天",
                "breakfast": [{"name": "小碗白粥配蒸蛋", "icon": "🥣", "condition": "恶心", "benefit": "温和、容易入口，减少早晨反胃"}],
                "lunch": [{"name": "清蒸鱼配软米饭", "icon": "🐟", "condition": "进食减少", "benefit": "高蛋白且比油煎食物更好消化"}],
                "dinner": [{"name": "豆腐南瓜羹", "icon": "🍲", "condition": "ADC 胃肠道毒性", "benefit": "补液同时提供软烂碳水和蛋白"}],
            },
            {
                "day": "第2天",
                "breakfast": [{"name": "苏打饼干配温豆浆", "icon": "🍘", "condition": "恶心", "benefit": "少量碳水先垫底，减少空腹恶心"}],
                "lunch": [{"name": "水煮鸡胸肉配丝瓜", "icon": "🍗", "condition": "脱水风险", "benefit": "清淡高蛋白，搭配含水量高的瓜类蔬菜"}],
                "dinner": [{"name": "米汤加少量盐配蒸蛋", "icon": "🥚", "condition": "体位性头晕", "benefit": "补液和电解质，避免晚上完全吃不下"}],
            },
            {
                "day": "第3天",
                "breakfast": [{"name": "香蕉燕麦泥", "icon": "🍌", "condition": "血糖向低值漂移", "benefit": "少量温和碳水，帮助避免晨间低糖"}],
                "lunch": [{"name": "嫩豆腐鸡丝面", "icon": "🍜", "condition": "进食差", "benefit": "软烂好吞咽，比干硬食物更容易完成一餐"}],
                "dinner": [{"name": "清蒸鳕鱼配冬瓜", "icon": "🐟", "condition": "ADC 胃肠道毒性", "benefit": "低油低刺激，又能补足蛋白"}],
            },
        ],
        meal_plan_en=[
            {
                "day": "Day 1",
                "breakfast": [{"name": "Rice porridge with steamed egg", "icon": "🥣", "condition": "Nausea", "benefit": "Warm, gentle, and easier to tolerate first thing in the day"}],
                "lunch": [{"name": "Steamed fish with soft rice", "icon": "🐟", "condition": "Poor intake", "benefit": "Higher-protein and easier to digest than fried foods"}],
                "dinner": [{"name": "Tofu pumpkin soup", "icon": "🍲", "condition": "ADC GI toxicity", "benefit": "Adds fluids while staying soft and mild"}],
            },
            {
                "day": "Day 2",
                "breakfast": [{"name": "Plain crackers with warm soy milk", "icon": "🍘", "condition": "Nausea", "benefit": "A small starch first can reduce empty-stomach gagging"}],
                "lunch": [{"name": "Poached chicken breast with gourd vegetables", "icon": "🍗", "condition": "Dehydration risk", "benefit": "Light, higher-protein, and paired with water-rich vegetables"}],
                "dinner": [{"name": "Lightly salted rice broth with steamed egg", "icon": "🥚", "condition": "Orthostatic dizziness", "benefit": "Helps replace fluids and electrolytes without a heavy meal"}],
            },
            {
                "day": "Day 3",
                "breakfast": [{"name": "Mashed banana oatmeal", "icon": "🍌", "condition": "Glucose drifting low", "benefit": "Adds gentle carbs to reduce morning glucose dips"}],
                "lunch": [{"name": "Soft noodle bowl with tofu and chicken", "icon": "🍜", "condition": "Poor intake", "benefit": "Soft texture is easier to finish than dry solid foods"}],
                "dinner": [{"name": "Steamed cod with winter melon", "icon": "🐟", "condition": "ADC GI toxicity", "benefit": "Low-fat, low-irritation, and protein-dense"}],
            },
        ],
        diet_tips_zh=[
            {"icon": "🍽️", "title": "一天吃 5 到 6 次", "detail": "每次少一点，比强迫自己吃大餐更容易完成，也更不容易恶心。"},
            {"icon": "🥚", "title": "高蛋白但要软和", "detail": "蒸蛋、豆腐、蒸鱼和鸡胸肉能在吃得少的时候提高营养密度。"},
            {"icon": "🧂", "title": "腹泻时记得补盐", "detail": "严重腹泻会丢失水和电解质，口服补液盐或米汤加少量盐更合适。"},
            {"icon": "🥛", "title": "先避开牛奶和乳制品", "detail": "乳糖可能加重腹泻和肠道负担，尤其在胃肠道反应明显时。"},
            {"icon": "🥣", "title": "汤水和主食分开喝", "detail": "严重恶心时，尽量把大口喝汤放到餐前或餐后 30 分钟以上。"},
        ],
        diet_tips_en=[
            {"icon": "🍽️", "title": "Aim for 5 to 6 eating moments", "detail": "Small frequent intake is often more achievable than forcing one large meal."},
            {"icon": "🥚", "title": "Keep protein gentle and soft", "detail": "Steamed egg, tofu, steamed fish, and chicken breast add more nutrition when total intake is low."},
            {"icon": "🧂", "title": "Replace salt when diarrhea is heavy", "detail": "Serious diarrhea causes water and electrolyte losses, so oral rehydration solution or lightly salted rice broth fits better."},
            {"icon": "🥛", "title": "Pause milk and dairy for now", "detail": "Lactose can add to diarrhea and gut burden while GI toxicity is active."},
            {"icon": "🥣", "title": "Separate larger fluids from meals", "detail": "If nausea is severe, move soups and bigger drinks to at least 30 minutes before or after eating."},
        ],
        extra_recommendations_zh=[
            {"text": "今天开始少量频饮，目标是把饮水量慢慢拉回平时", "reason": "目前体位性头晕和轻度心动过速，更像早期容量不足。", "category": "diet"},
            {"text": "若几乎吃不下，请优先和试验团队确认二甲双胍处理", "reason": "进食差时继续按原量服药，会增加低血糖和脱水风险。", "category": "medication"},
        ],
        extra_recommendations_en=[
            {"text": "Start frequent small sips today and work fluids back toward your usual amount", "reason": "Orthostatic dizziness and mild tachycardia fit early volume depletion.", "category": "diet"},
            {"text": "If you are barely eating, ask the trial team how to handle metformin", "reason": "Poor intake plus the usual dose can increase low-glucose and dehydration risk.", "category": "medication"},
        ],
        emergency_note_zh="这更像 ADC 胃肠道毒性触发的双线风险：一边是脱水，一边是进食差背景下的血糖不稳。今天就要把止吐、补液和测糖同时拉起来。",
        emergency_note_en="This behaves like DXd-class GI toxicity creating a two-front problem: dehydration on one side and unstable glucose on the other. Antiemetics, hydration, and glucose checks all need to start today.",
        emergency_actions_zh=[
            "按医嘱尽早使用止吐药，改成少量多餐；恶心重时把大口喝汤和大量液体放到餐前或餐后 30 分钟以上。",
            "全天少量频饮，必要时使用口服补液盐；如果有腹泻，可用米汤加少量盐帮助补液和电解质。",
            "今天重点记录体位性血压/心率、餐前后血糖、饮水量、尿量和体重；若无法留住液体、血糖 < 4 mmol/L、昏厥或尿量明显减少，立即联系试验团队或急诊。",
        ],
        emergency_actions_en=[
            "Use the antiemetic early, switch to small frequent meals, and if nausea is strong, move larger fluids to at least 30 minutes before or after eating.",
            "Sip fluids all day and use oral rehydration solution if needed; if diarrhea appears, lightly salted rice broth can help replace both fluid and electrolytes.",
            "Track orthostatic BP/HR, pre/post-meal glucose, fluid intake, urine output, and weight today; if you cannot keep fluids down, glucose falls below 4 mmol/L, you faint, or urine output drops sharply, contact the trial team or emergency care immediately.",
        ],
        emergency_monitoring_zh={
            "what_to_monitor": "体位性血压/心率、餐前后血糖、饮水量、尿量、体重、是否能留住液体",
            "frequency": "今天开始每餐前后和起身不适时记录；饮水与尿量全天累计",
            "next_checkin": "24 小时内由试验团队复核，必要时安排门诊补液",
        },
        emergency_monitoring_en={
            "what_to_monitor": "Orthostatic BP/HR, pre/post-meal glucose, fluid intake, urine output, weight, and whether fluids stay down",
            "frequency": "Start today with checks around meals and whenever standing symptoms occur; total fluids and urine should be tracked through the day",
            "next_checkin": "Trial-team review within 24 hours, with outpatient hydration if needed",
        },
    ),
    "clinical_trial_jason": PatientCopy(
        scenario_id="clinical_trial_jason",
        file_stem="jason",
        display_name="Jason Miller",
        conditions_zh=["肺储备下降", "化疗期间"],
        conditions_en=["Reduced pulmonary reserve", "During chemotherapy"],
        risk_tags_zh=["活动后气短", "干咳", "血氧轻度下降", "乏力"],
        risk_tags_en=["exertional dyspnea", "dry cough", "slight SpO2 drop", "fatigue"],
        ai_sections_zh=[
            {"type": "good_news", "title": "现在还不是静息性呼吸困难", "content": "目前血氧虽然较基线下降，但还没有静息气短和发热，说明仍处在可以尽快追踪和处理的窗口。"},
            {"type": "attention", "title": "要把它当作早期肺毒性信号", "content": "在 DXd 类药物背景下，轻度活动后气短加干咳和血氧漂移，不能简单按体能下降处理。"},
            {"type": "plan", "title": "这 48 到 72 小时最重要", "content": "重点观察血氧是否继续下降、咳嗽是否加重、气短是否从活动后转到静息时。"},
            {"type": "encouragement", "title": "先把气息留给恢复", "content": "这几天饮食要轻一些、活动要慢一些，目标是减少额外呼吸负荷。"},
        ],
        ai_sections_en=[
            {"type": "good_news", "title": "This is not resting respiratory distress yet", "content": "SpO2 is lower than baseline, but there is still no resting dyspnea or fever, so there is still a useful tracking window."},
            {"type": "attention", "title": "Treat it like an early lung-toxicity signal", "content": "With a DXd-class ADC, mild exertional dyspnea plus dry cough and SpO2 drift should not be brushed off as simple deconditioning."},
            {"type": "plan", "title": "The next 48 to 72 hours matter most", "content": "Watch for oxygen falling further, cough worsening, or symptoms shifting from exertional to resting."},
            {"type": "encouragement", "title": "Save breathing reserve for recovery", "content": "Lighter meals and slower activity this week can reduce extra respiratory load while the picture becomes clearer."},
        ],
        adherence_zh={
            "medication": {
                "status": "基础用药延续",
                "issues": "当前更大的问题不是漏服，而是需要尽快识别是否出现 ADC 相关肺毒性。",
                "adjustments": "没有试验团队新指示前先按原方案服药，但若症状升级，要立即联系团队确认是否需要暂停下一次给药。",
            },
            "appetite": {
                "status": "轻度受影响",
                "cause_if_known": "气短和乏力会让吃饭变慢，也容易因为说话或活动多了而更累。",
                "suggestions": "餐量可以小一点，但尽量保证蛋白和总热量，不要因为怕累就整天不吃。"},
            "exercise": {
                "status": "需要保守",
                "barriers": "现阶段呼吸储备下降，活动后气短和干咳是主要限制。",
                "plan": "先以室内短距离、节奏慢的活动为主，避免爬楼和快走。"},
            "monitoring": {
                "status": "需要更密切",
                "gaps": "要每天记录静息与活动后血氧、体温、咳嗽频率和步行耐量。"},
        },
        adherence_en={
            "medication": {
                "status": "Baseline medicines continued",
                "issues": "The bigger issue is not missed medication but quickly identifying whether this is early ADC-related lung toxicity.",
                "adjustments": "Keep current medicines steady unless the trial team changes them, but escalate quickly if symptoms worsen before the next dose.",
            },
            "appetite": {
                "status": "Mildly affected",
                "cause_if_known": "Dyspnea and fatigue can slow down normal eating and make meals feel more tiring.",
                "suggestions": "Meals can stay smaller, but try not to let total protein and calories drop too far."},
            "exercise": {
                "status": "Should stay conservative",
                "barriers": "Reduced respiratory reserve plus exertional dyspnea and dry cough are the main current limits.",
                "plan": "Use slower, shorter indoor movement and avoid stairs or brisk walking for now."},
            "monitoring": {
                "status": "Needs closer watching",
                "gaps": "He should log resting and post-activity SpO2, temperature, cough frequency, and walking tolerance every day."},
        },
        health_guidance_zh={
            "summary": "Jason 当前最重要的是把“轻度气短 + 干咳 + 血氧漂移”看成可能的早期肺毒性线索，主动追踪，而不是等它自己过去。",
            "tips": [
                {"text": "每天都测一次静息和活动后血氧", "why": "对肺毒性来说，趋势往往比某一次单点更有意义。"},
                {"text": "吃得少一点没关系，但别吃得太油太撑", "why": "过饱会增加呼吸负担，轻一点反而更容易完成。"},
                {"text": "今天先避免爬楼和快走", "why": "把有限的呼吸储备留给恢复，比硬练更重要。"},
            ],
        },
        health_guidance_en={
            "summary": "For Jason, the key is to treat mild dyspnea, dry cough, and SpO2 drift as a possible early lung-toxicity signal and track it actively instead of waiting it out.",
            "tips": [
                {"text": "Check both resting and post-activity oxygen every day", "why": "For lung toxicity, the trend often matters more than a single point."},
                {"text": "Lighter meals are fine, but avoid very greasy or overly large meals", "why": "Overfilling the stomach can make breathing feel harder."},
                {"text": "Skip stairs and brisk walking today", "why": "Protecting breathing reserve matters more than pushing activity right now."},
            ],
        },
        nutrition_zh="饮食重点是轻负担但别掉营养。优先选择温热、易咀嚼、不过于油腻的蛋白来源，如蒸鱼、鸡肉、豆腐、软面和熟蔬菜；进餐时放慢速度，避免一次吃得过饱影响呼吸。",
        nutrition_en="The food goal is lower breathing burden without losing nutrition. Choose warm, easy-to-chew, lower-fat protein options like steamed fish, chicken, tofu, soft noodles, and cooked vegetables, and slow meals down so a full stomach does not worsen breathing.",
        diet_table_zh=[
            {"condition": "肺储备下降", "principle": "轻负担、分次进食", "recommend": "软面、蒸鱼、豆腐、熟蔬菜", "avoid": "太油、太撑、边走边吃"},
            {"condition": "乏力恢复期", "principle": "少量高蛋白", "recommend": "鸡肉、鸡蛋、豆类、温汤", "avoid": "空腹太久、只吃零食"},
            {"condition": "化疗期间", "principle": "稳定能量和水分", "recommend": "清淡主食、温水、分散补液", "avoid": "刺激性饮料、熬夜后不吃早餐"},
        ],
        diet_table_en=[
            {"condition": "Reduced pulmonary reserve", "principle": "Lower load and split intake", "recommend": "Soft noodles, steamed fish, tofu, cooked vegetables", "avoid": "Very greasy food, overly large meals, and eating while rushing"},
            {"condition": "Fatigue recovery", "principle": "Small higher-protein meals", "recommend": "Chicken, eggs, beans, warm soups", "avoid": "Long fasts and snack-only days"},
            {"condition": "During chemotherapy", "principle": "Steady energy and hydration", "recommend": "Simple starches, warm water, spaced fluids", "avoid": "Irritating drinks and skipping breakfast after poor sleep"},
        ],
        meal_plan_zh=[
            {
                "day": "第1天",
                "breakfast": [{"name": "软面配蒸蛋", "icon": "🍜", "condition": "乏力", "benefit": "容易入口，不会太撑"}],
                "lunch": [{"name": "清蒸鱼配南瓜", "icon": "🐟", "condition": "肺储备下降", "benefit": "高蛋白又不过油，减少餐后负担"}],
                "dinner": [{"name": "豆腐鸡丝汤", "icon": "🍲", "condition": "化疗期间", "benefit": "补液同时提供温和蛋白"}],
            },
            {
                "day": "第2天",
                "breakfast": [{"name": "香蕉燕麦粥", "icon": "🥣", "condition": "活动后气短", "benefit": "早晨温和补能量，减少空腹乏力"}],
                "lunch": [{"name": "鸡肉蔬菜粥", "icon": "🍚", "condition": "干咳", "benefit": "质地软，更适合说话少、慢慢吃"}],
                "dinner": [{"name": "清炒豆腐配软米饭", "icon": "🍚", "condition": "化疗期间", "benefit": "晚餐不油不重，避免吃完更喘"}],
            },
            {
                "day": "第3天",
                "breakfast": [{"name": "全麦吐司配温豆浆", "icon": "🍞", "condition": "乏力", "benefit": "少量碳水和蛋白，维持上午体力"}],
                "lunch": [{"name": "鳕鱼土豆泥", "icon": "🐟", "condition": "肺储备下降", "benefit": "吃得慢一点也容易完成"}],
                "dinner": [{"name": "鸡丝冬瓜汤面", "icon": "🍜", "condition": "活动后气短", "benefit": "温热、软烂，减少餐后胸闷感"}],
            },
        ],
        meal_plan_en=[
            {
                "day": "Day 1",
                "breakfast": [{"name": "Soft noodles with steamed egg", "icon": "🍜", "condition": "Fatigue", "benefit": "Easy to eat and not overly filling"}],
                "lunch": [{"name": "Steamed fish with pumpkin", "icon": "🐟", "condition": "Reduced pulmonary reserve", "benefit": "Higher-protein and lower-fat with less post-meal load"}],
                "dinner": [{"name": "Tofu chicken soup", "icon": "🍲", "condition": "During chemotherapy", "benefit": "Adds warm fluids and gentle protein"}],
            },
            {
                "day": "Day 2",
                "breakfast": [{"name": "Banana oatmeal porridge", "icon": "🥣", "condition": "Exertional dyspnea", "benefit": "Gentle morning energy without feeling too heavy"}],
                "lunch": [{"name": "Chicken vegetable congee", "icon": "🍚", "condition": "Dry cough", "benefit": "Soft texture is easier when meals need to stay slow"}],
                "dinner": [{"name": "Light tofu with soft rice", "icon": "🍚", "condition": "During chemotherapy", "benefit": "Keeps dinner lighter so breathing is not worse after eating"}],
            },
            {
                "day": "Day 3",
                "breakfast": [{"name": "Whole-wheat toast with warm soy milk", "icon": "🍞", "condition": "Fatigue", "benefit": "Adds some carbohydrate and protein for the morning"}],
                "lunch": [{"name": "Cod with mashed potato", "icon": "🐟", "condition": "Reduced pulmonary reserve", "benefit": "Simple, softer, and easier to finish slowly"}],
                "dinner": [{"name": "Chicken winter-melon noodle soup", "icon": "🍜", "condition": "Exertional dyspnea", "benefit": "Warm and soft, with less chance of post-meal tight breathing"}],
            },
        ],
        diet_tips_zh=[
            {"icon": "🌬️", "title": "吃饭速度放慢", "detail": "说话多、吃得急、吃得太撑，都会让气短感觉更明显。"},
            {"icon": "🍲", "title": "优先温热软食", "detail": "温汤面、软粥、蒸鱼和豆腐更容易在疲劳时完成。"},
            {"icon": "🧃", "title": "水分分散喝", "detail": "全天小口补液，比临时猛灌更舒服，也更容易坚持。"},
            {"icon": "📉", "title": "把血氧和步行耐量一起看", "detail": "有时候血氧变化不大，但步行耐量下降会更早提示问题。"},
        ],
        diet_tips_en=[
            {"icon": "🌬️", "title": "Slow meals down", "detail": "Talking a lot, eating too fast, or overfilling the stomach can make breathlessness feel worse."},
            {"icon": "🍲", "title": "Favor warm softer foods", "detail": "Warm soups, soft porridge, steamed fish, and tofu are easier to finish on a fatigued day."},
            {"icon": "🧃", "title": "Space fluids through the day", "detail": "Small frequent drinks are usually more comfortable than trying to catch up all at once."},
            {"icon": "📉", "title": "Watch walking tolerance with oxygen", "detail": "Sometimes walking capacity drops before oxygen numbers look dramatic."},
        ],
        extra_recommendations_zh=[
            {"text": "每日记录静息和活动后血氧", "reason": "这能更早发现从轻度信号转向真正进展的趋势。", "category": "monitoring"},
            {"text": "只要气短开始影响静息状态，就不要再在家观察", "reason": "从活动后转为静息时不适，是需要升级处理的重要分界点。", "category": "monitoring"},
        ],
        extra_recommendations_en=[
            {"text": "Record both resting and post-activity oxygen each day", "reason": "That is one of the fastest ways to catch a trend before it becomes obvious clinically.", "category": "monitoring"},
            {"text": "Do not stay in home-observation mode if breathlessness shifts to rest", "reason": "A change from exertional to resting symptoms is a major escalation boundary.", "category": "monitoring"},
        ],
        emergency_note_zh="虽然现在还不是急性呼吸衰竭，但这符合 DXd 类药物早期肺毒性需要主动追踪的模式；近期任何血氧继续下降或发热，都要提高警惕。",
        emergency_note_en="This is not acute respiratory failure right now, but it does fit the early pattern of DXd-class lung toxicity that needs active tracking; any further oxygen drop or fever should trigger a lower threshold to escalate.",
        emergency_actions_zh=[
            "从今天开始记录静息和活动后血氧、心率、体温、咳嗽频率，以及走同样距离时是不是更累。",
            "这几天活动要慢，先避免爬楼、快走和会明显诱发气短的事情。",
            "如果血氧降到 92% 以下、出现静息气短、发热或胸痛，立即联系试验团队或前往急诊。",
        ],
        emergency_actions_en=[
            "Start tracking resting and post-activity oxygen, heart rate, temperature, cough frequency, and whether the same walking distance feels harder.",
            "Keep activity slower for the next few days and avoid stairs, brisk walking, or anything that clearly provokes dyspnea.",
            "If oxygen falls below 92%, or resting shortness of breath, fever, or chest pain appears, contact the trial team or emergency care immediately.",
        ],
        emergency_monitoring_zh={
            "what_to_monitor": "静息/活动后血氧、体温、咳嗽频率、步行耐量、是否转为静息气短",
            "frequency": "每天至少早晚各一次，活动后额外补测",
            "next_checkin": "24 小时内由试验团队复核；一旦进展，尽快安排 HRCT 方向评估",
        },
        emergency_monitoring_en={
            "what_to_monitor": "Resting/post-activity oxygen, temperature, cough frequency, walking tolerance, and whether dyspnea shifts to rest",
            "frequency": "At least morning and evening daily, plus an extra check after exertion",
            "next_checkin": "Trial-team review within 24 hours, with HRCT-directed escalation if symptoms progress",
        },
    ),
}


def read_source(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def choose_lang(value: Any, lang: str) -> str:
    if isinstance(value, dict):
        return str(value.get(lang) or value.get("zh") or value.get("en") or "")
    return str(value or "")


def vitals_from_source(source: dict[str, Any]) -> dict[str, str]:
    vs = source.get("signals", {}).get("vital_signs", {}) or {}
    current = {}
    sbp = vs.get("sbp")
    dbp = vs.get("dbp")
    if sbp is not None and dbp is not None:
        current["blood_pressure"] = f"{sbp}/{dbp}"
    if vs.get("heartrate") is not None:
        current["heart_rate"] = str(vs["heartrate"])
    if vs.get("o2sat") is not None:
        current["blood_oxygen"] = str(vs["o2sat"])
    if vs.get("temperature") is not None:
        current["temperature"] = str(vs["temperature"])
    for series in source.get("trial_context", {}).get("chart_series", []) or []:
        key = series.get("key")
        data = series.get("data") or []
        if not data:
            continue
        if key == "glucose":
            current["blood_glucose"] = str(data[-1])
    return current


def memory_payload(source: dict[str, Any], lang: str, display_name: str, preferred_context: str = "stable_routine") -> dict[str, Any]:
    demo = source.get("patient", {}).get("demographics", {}) or {}
    diagnoses = source.get("patient", {}).get("medical_history", {}).get("diagnoses", []) or []
    meds = source.get("patient", {}).get("meds", []) or []
    symptoms = source.get("symptoms", {}).get("system_identified", []) or []
    memory_evidence = source.get("trial_context", {}).get("memory_evidence", []) or []
    diagnosis_text = "；".join(diagnoses) if lang == "zh" else "; ".join(diagnoses)
    meds_text = "；".join(meds) if lang == "zh" else "; ".join(meds)
    symptom_text = "、".join(symptoms) if lang == "zh" else ", ".join(symptoms)
    sex = choose_lang({"zh": {"男": "男性", "女": "女性"}.get(demo.get("性别", ""), demo.get("性别", "")), "en": {"男": "male", "女": "female"}.get(demo.get("性别", ""), "")}, lang)
    age = demo.get("年龄")

    if lang == "zh":
        profile = f"{display_name}，{age} 岁{sex}。当前主要基础情况：{diagnosis_text}。近期用药：{meds_text}。"
        dynamics = f"当前系统重点关注：{symptom_text}。{choose_lang(source.get('signals', {}).get('summary_text', ''), lang)}"
    else:
        profile = f"{display_name}, {age}-year-old {sex}. Baseline conditions: {diagnosis_text}. Current medications: {meds_text}."
        dynamics = f"Current monitoring focus: {symptom_text}. {source.get('signals', {}).get('summary_text', '')}"

    key_events = []
    complaint = source.get("patient", {}).get("chief_complaint") or source.get("scenario", {}).get("initial_query") or ""
    if complaint:
        key_events.append({"date": datetime.now().date().isoformat(), "type": "symptom", "description": complaint})
    for item in memory_evidence:
        key_events.append(
            {
                "date": item.get("date", ""),
                "type": "alert",
                "description": choose_lang(item.get("content"), lang),
            }
        )
    return {
        "patient_long_term_profile": profile,
        "recent_health_dynamics": dynamics,
        "key_events": key_events[:8],
        "tone_profile": {
            "condition_context": preferred_context,
            "preferred_name": display_name.split()[0],
        },
    }


def translate_patient_suggestions(source: dict[str, Any], lang: str) -> list[dict[str, str]]:
    blocks = source.get("suggestions", {}).get("patient", []) or []
    items: list[dict[str, str]] = []
    for block in blocks:
        for chunk in block.get("output_json", []) or []:
            category = (chunk.get("category") or "").lower()
            for advice in chunk.get("advice", []) or []:
                if lang == "zh":
                    translated = {
                        "Self-monitoring": "自我监测",
                        "When to seek help": "何时立即求助",
                    }.get(chunk.get("category"), chunk.get("category", "建议"))
                    items.append({"text": choose_lang(advice, lang), "reason": f"来自{translated}模块的试验期建议。", "category": "monitoring" if "monitor" in category else "lifestyle"})
                else:
                    items.append({"text": advice, "reason": f"Pulled forward from the trial-page {chunk.get('category', 'patient guidance').lower()} block.", "category": "monitoring" if "monitor" in category else "lifestyle"})
    return items


def emergency_red_flag_text(source: dict[str, Any], lang: str) -> str:
    flags = source.get("trial_context", {}).get("individual_trajectory", {}).get("red_flags", {}).get("patient", []) or []
    texts = [choose_lang(item, lang) for item in flags]
    sep = "；" if lang == "zh" else " "
    return sep.join(texts)


def merge_tips(base: list[dict[str, str]], shared: list[dict[str, str]]) -> list[dict[str, str]]:
    merged = list(base)
    seen = {item.get("title") or item.get("text") for item in merged}
    for item in shared:
        key = item.get("title") or item.get("text")
        if key not in seen:
            merged.append(deepcopy(item))
            seen.add(key)
    return merged


def merge_guidance_tips(base: list[dict[str, str]], shared: list[dict[str, str]]) -> list[dict[str, str]]:
    merged = list(base)
    seen = {item.get("text") for item in merged}
    for item in shared:
        if item.get("text") not in seen:
            merged.append(deepcopy(item))
            seen.add(item.get("text"))
    return merged


def immediate_actions(source: dict[str, Any], override: PatientCopy, lang: str) -> list[str]:
    actions = list(override.emergency_actions_zh if lang == "zh" else override.emergency_actions_en)
    shared_action = SHARED_ADC_EMERGENCY_ACTION_ZH if lang == "zh" else SHARED_ADC_EMERGENCY_ACTION_EN
    if shared_action not in actions:
        actions.append(shared_action)
    return actions


def build_adherence_input(source: dict[str, Any], override: PatientCopy, lang: str) -> dict[str, Any]:
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    vitals = vitals_from_source(source)
    risk_tags = override.risk_tags_zh if lang == "zh" else override.risk_tags_en
    sections = override.ai_sections_zh if lang == "zh" else override.ai_sections_en
    adherence = deepcopy(override.adherence_zh if lang == "zh" else override.adherence_en)
    guidance = deepcopy(override.health_guidance_zh if lang == "zh" else override.health_guidance_en)
    nutrition = override.nutrition_zh if lang == "zh" else override.nutrition_en
    diet_table = deepcopy(override.diet_table_zh if lang == "zh" else override.diet_table_en)
    meal_plan = deepcopy(override.meal_plan_zh if lang == "zh" else override.meal_plan_en)
    diet_tips = deepcopy(override.diet_tips_zh if lang == "zh" else override.diet_tips_en)
    extra = deepcopy(override.extra_recommendations_zh if lang == "zh" else override.extra_recommendations_en)
    recommendations = translate_patient_suggestions(source, lang) + extra

    if lang == "zh":
        guidance["summary"] = SHARED_ADC_NUTRITION_ZH + guidance["summary"]
        guidance["tips"] = merge_guidance_tips(guidance.get("tips", []), SHARED_ADC_GUIDANCE_TIPS_ZH)
        nutrition = SHARED_ADC_NUTRITION_ZH + SHARED_ADC_GI_DETAIL_ZH + nutrition
        diet_table = [SHARED_ADC_DIET_ROW_ZH] + diet_table
        diet_tips = merge_tips(diet_tips, SHARED_ADC_DIET_TIPS_ZH)
    else:
        guidance["summary"] = SHARED_ADC_NUTRITION_EN + " " + guidance["summary"]
        guidance["tips"] = merge_guidance_tips(guidance.get("tips", []), SHARED_ADC_GUIDANCE_TIPS_EN)
        nutrition = SHARED_ADC_NUTRITION_EN + " " + SHARED_ADC_GI_DETAIL_EN + " " + nutrition
        diet_table = [SHARED_ADC_DIET_ROW_EN] + diet_table
        diet_tips = merge_tips(diet_tips, SHARED_ADC_DIET_TIPS_EN)

    triage = source.get("triage", {}) or {}
    trial = source.get("trial_context", {}).get("trial", {}) or {}
    vitals_summary = {
        "blood_pressure": vitals.get("blood_pressure", ""),
        "heart_rate": vitals.get("heart_rate", ""),
        "blood_oxygen": vitals.get("blood_oxygen", ""),
        "blood_glucose": vitals.get("blood_glucose", ""),
        "steps_today": "",
    }

    if lang == "zh":
        reasoning = (
            f"{override.display_name} 当前处于 {trial.get('drug', 'ADC')} {trial.get('cycle', '')} 治疗窗口。"
            f" 页面核心判断来自试验原始分诊：{triage.get('rationale', '')}"
        )
        guardrail = "本页面基于试验审核数据重组生成，仅供辅助理解，不替代试验团队、主诊医生或急诊评估。"
        conditions = override.conditions_zh
    else:
        reasoning = (
            f"{override.display_name} is in the {trial.get('drug', 'ADC')} {trial.get('cycle', '')} treatment window. "
            f"The core interpretation is adapted from the trial-triage rationale: {triage.get('rationale', '')}"
        )
        guardrail = "This page is restructured from clinical-trial review data for supportive understanding only. It does not replace the trial team, treating clinician, or emergency assessment."
        conditions = override.conditions_en

    return {
        "payload": {
            "meta": {
                "current_time": current_time,
                "user_id": source.get("scenario", {}).get("user_id") or source.get("scenario", {}).get("scenario_id") or override.file_stem,
            },
            "memory": memory_payload(source, lang, override.display_name),
            "location": {},
        },
        "llm_result": {
            "structured_output": {
                "patient_status": "at_risk",
                "risk_tags": risk_tags,
                "assistant_message_sections": sections,
                "adherence_analysis": {"period": trial.get("cycle", "Current cycle"), **adherence},
                "recommendations": recommendations,
                "nutrition_advice": nutrition,
                "latest_health_summary": vitals_summary,
                "conditions": conditions,
                "diet_table": diet_table,
                "weekly_meal_plan": meal_plan,
                "diet_tips": diet_tips,
                "reasoning": reasoning,
                "guardrail": guardrail,
                "health_guidance": guidance,
            }
        },
    }


def build_emergency_input(source: dict[str, Any], override: PatientCopy, lang: str) -> dict[str, Any]:
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    vitals = vitals_from_source(source)
    triage = source.get("triage", {}) or {}
    trajectory = source.get("trial_context", {}).get("individual_trajectory", {}) or {}
    onset = choose_lang(source.get("trial_context", {}).get("adverse_event", {}).get("onset"), lang)
    causes = triage.get("likely_causes", []) or []
    causes_text = ("；" if lang == "zh" else "; ").join(causes)

    if lang == "zh":
        summary = f"{onset} 当前更像：{causes_text}。"
        note = override.emergency_note_zh
        monitoring = override.emergency_monitoring_zh
        conditions = override.conditions_zh
        care_text = emergency_red_flag_text(source, lang) or "若症状持续加重，请直接联系试验团队或尽快前往最近急诊。"
        guardrail = "此页为临床试验安全审核场景下的患者提示页，仅帮助整理下一步行动，不替代急诊与正式医疗判断。"
    else:
        summary = f"{onset} The most likely working explanations right now are: {causes_text}."
        note = override.emergency_note_en
        monitoring = override.emergency_monitoring_en
        conditions = override.conditions_en
        care_text = emergency_red_flag_text(source, lang) or "If symptoms continue to worsen, contact the trial team directly or go to the nearest emergency department."
        guardrail = "This page is a patient-facing summary for a clinical-trial safety review scenario. It supports next-step understanding but does not replace emergency care or formal medical judgment."

    return {
        "payload": {
            "meta": {
                "current_time": current_time,
            },
            "location": {},
        },
        "llm_result": {
            "structured_output": {
                "patient_status": "at_risk",
                "conditions": conditions,
                "situation_summary": summary,
                "physician_status": "notified",
                "physician_note": note,
                "latest_vitals": {
                    "blood_pressure": vitals.get("blood_pressure", ""),
                    "heart_rate": vitals.get("heart_rate", ""),
                    "blood_oxygen": vitals.get("blood_oxygen", ""),
                    "blood_glucose": vitals.get("blood_glucose", ""),
                },
                "immediate_actions": immediate_actions(source, override, lang),
                "monitoring_plan": monitoring,
                "nearest_care_instructions": care_text,
                "guardrail": guardrail,
            }
        },
    }


def run_renderer(renderer: Path, payload: dict[str, Any]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(renderer)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=True,
    )
    if completed.stderr.strip():
        print(completed.stderr.strip(), file=sys.stderr)
    return json.loads(completed.stdout)


def render_one(source: dict[str, Any], override: PatientCopy) -> list[tuple[str, Path]]:
    outputs: list[tuple[str, Path]] = []
    configs = [
        ("adherence_zh", "zh", ADHERENCE_ZH_RENDERER, build_adherence_input(source, override, "zh")),
        ("adherence_en", "en", ADHERENCE_EN_RENDERER, build_adherence_input(source, override, "en")),
        ("emergency_zh", "zh", EMERGENCY_ZH_RENDERER, build_emergency_input(source, override, "zh")),
        ("emergency_en", "en", EMERGENCY_EN_RENDERER, build_emergency_input(source, override, "en")),
    ]

    for kind, _, renderer, payload in configs:
        INPUT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        input_path = INPUT_EXPORT_DIR / f"{override.file_stem}_{kind}.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        result = run_renderer(renderer, payload)
        html = result["structured_output"]["html"]
        html_path = OUTPUT_DIR / f"{override.file_stem}_{kind}.html"
        html_path.write_text(html, encoding="utf-8")
        outputs.append((kind, html_path))

    return outputs


def write_index(rendered: dict[str, list[tuple[str, Path]]]) -> None:
    rows = []
    for patient, files in rendered.items():
        links = []
        for kind, path in files:
            label = {
                "adherence_zh": "依从性中文",
                "adherence_en": "Adherence EN",
                "emergency_zh": "紧急指引中文",
                "emergency_en": "Emergency EN",
            }.get(kind, kind)
            links.append(f'<a href="{path.name}" class="link">{label}</a>')
        rows.append(f"<tr><td>{patient}</td><td>{' '.join(links)}</td></tr>")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Clinical Trial Pages</title>
  <style>
    body {{
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      background: #f8fafc;
      color: #0f172a;
      margin: 0;
      padding: 32px;
    }}
    .wrap {{
      max-width: 960px;
      margin: 0 auto;
      background: white;
      border: 1px solid #e2e8f0;
      border-radius: 18px;
      padding: 28px;
      box-shadow: 0 12px 40px rgba(15, 23, 42, 0.06);
    }}
    h1 {{ margin-top: 0; font-size: 1.8rem; }}
    p {{ color: #475569; line-height: 1.7; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
    th, td {{ padding: 14px 12px; border-bottom: 1px solid #e2e8f0; text-align: left; vertical-align: top; }}
    th {{ color: #334155; font-size: 0.95rem; }}
    .link {{
      display: inline-block;
      margin: 6px 10px 6px 0;
      padding: 8px 12px;
      border-radius: 999px;
      text-decoration: none;
      background: #ecfeff;
      color: #0f766e;
      border: 1px solid #99f6e4;
      font-size: 0.92rem;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Clinical Trial To Existing Page Formats</h1>
    <p>下表汇总了 3 位患者映射到现有 4 套页面后的输出文件。原始转换输入 JSON 也同步写到了 <code>output/clinical-trial-pages/inputs</code>，便于后续继续改字段或重跑。</p>
    <table>
      <thead><tr><th>Patient</th><th>Generated Pages</th></tr></thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
  </div>
</body>
</html>
"""
    (OUTPUT_DIR / "index.html").write_text(html, encoding="utf-8")


def main() -> None:
    rendered: dict[str, list[tuple[str, Path]]] = {}
    for scenario_id, override in PATIENT_OVERRIDES.items():
        source_path = INPUT_DIR / f"{override.file_stem}.json"
        source_blob = read_source(source_path)
        source = source_blob.get("data") or {}
        rendered[override.display_name] = render_one(source, override)
    write_index(rendered)
    print(json.dumps({name: [str(path) for _, path in files] for name, files in rendered.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
