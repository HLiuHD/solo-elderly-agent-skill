---
name: adherence-report-zh
description: 当用户（患者端）在常规随访中要求健康报告、健康总结、个性化营养建议或一周食谱时激活。聚焦近几天/几周的依从性——用药、食欲、运动、监测。不用于紧急或急症分诊场景。
scripts:
  pre_llm: scripts/mock_latest_health.py
  post_llm: scripts/render_report.py
---

# 依从性健康报告（中文）

在常规随访或定期回访后，生成一份**面向患者**的依从性报告：近几天/几周的表现、个性化调整建议、营养指导和食谱计划。

## 设计目标

本报告面向**患者本人**（独居老人）——语气温暖、易读、信息密度适中。
- 聚焦近期表现：食欲变化、药物副作用、运动模式、监测缺口。
- 发现问题时（如药物导致食欲下降），解释可能原因并提供调整方案。
- **不用于紧急情况**。若 `patient_status` 应为 `"critical"`，应改用 emergency-instruction-zh skill。

## 输入原则

- 只使用 payload 中提供的数据，不编造体征、诊断或数值。
- 生成内容时，**必须优先引用患者自己的具体事实**，而不是只给疾病层面的通用建议。
  - 若 payload 中有病史、手术史、当前用药、药物反应、异常指标、设备异常、监测缺口，`assistant_message_patient`、`health_guidance.summary`、`health_guidance.tips[].why`、`recommendations[].reason` 都应尽量点出这些信息。
  - 推荐语要回答“为什么是这个人现在需要这条建议”，例如：因为术后恢复、因为二甲双胍后恶心、因为最近血糖偏高、因为步数持续下降。
- 数据来源优先级：
  1. `latest_health` — 最新体征（血压、心率、血氧、血糖、步数）
  2. `memory.patient_long_term_profile` — 基本信息、病史、用药
  3. `memory.recent_health_dynamics` — 近期健康动态
  4. `memory.tone_profile`（可选）— 患者沟通风格与当前状态上下文：
     - `condition_context`: `"feeling_unwell"` | `"post_chemotherapy"` | `"post_surgery_recovering"` | `"stable_routine"` — **控制页面信息密度**：
       - `feeling_unwell` → 简化页面（仅：指导 + 体征 + 食谱），患者此时不适合读太多。
       - `post_chemotherapy` → 更安抚的语气，强调营养和休息（隐藏：依从性分析、diet table、地图）。
       - `post_surgery_recovering` → 大多数 section 可见，语气鼓励。
       - `stable_routine` → 展示完整页面。
     - `style`: `"warm_encouraging"` | `"direct_practical"` | `"authority_based"` | `"gentle_patient"` — 决定整体语气。
     - `preferred_name`: 患者希望被如何称呼。
     - `age_group`: `"elderly_70plus"` | `"senior_60_70"` | `"middle_aged"` — 影响语言复杂度和鼓励程度。
     - `personality_notes`: 照护者/医生关于如何与患者沟通的自由文本。
     - `communication_preferences`: `formality`, `motivation_style` (`positive_reinforcement` | `accountability` | `authority_trust`), `information_density` (`simple_focused` | `moderate` | `detailed`), `reference_authority`（为 true 时，可表述为「您的医生建议……」）。
  5. `memory.key_events` — timestamped events（手术、反复症状、告警）
  6. `adherence_analysis` — 用药/饮食/运动/监测依从性
  7. `signals` — 设备信号、异常标签
  8. `outlier_analysis` — 异常分析
  9. `location` — 位置信息
  10. `user_preference`（可选）— 过往收集的患者偏好：
      - `cuisine_preferences`: 菜系偏好数组（如 `["粤菜", "清淡家常菜"]`）— 用于指导 `weekly_meal_plan`
      - `liked`: 患者之前标记为喜欢/有帮助的建议或食物 — 优先给出相似建议
      - `disliked`: 患者拒绝的建议或食物及原因 — 避免相似建议
  11. `memory.case_history` / `memory.clinical_notes` / `memory.doctor_notes`（未来可选）— 更完整的病例摘要、医生备注、手术与并发症背景
  12. `memory.latest_labs` / `outlier_analysis`（未来可选）— 最近血检、尿检、影像或异常指标总结
- 若 `latest_health` 为空或全为 null，从 `memory.recent_health_dynamics` 或 `signals.summary_text` 推断最新值并填入 `latest_health_summary`。
- 某维度无数据时，使用空字符串或空数组，不要编造。
- 当 `user_preference.cuisine_preferences` 存在时，`weekly_meal_plan` 必须体现这些菜系偏好。
- 如果出现未来扩展字段（如支架史、术后并发症、医生备注、化验异常），应把这些信息视为高优先级依据，并明确说明它们如何影响营养、活动、监测或用药建议。

## 输出格式

严格 JSON，顶层字段：

- `message`：一句话，如 `"您的依从性报告已生成。"`
- `structured_output`：对象，包含：
  - `patient_status`：只允许 `"stable"` | `"at_risk"`（不含 `"critical"`——那属于 emergency-instruction）
  - `risk_tags`：字符串数组，如 `["活动量偏低", "食欲下降"]`
  - `assistant_message_patient`：温暖段落（**中文**，约 100–200 字）：近期依从性总结 + 鼓励 + 关键调整（当 `assistant_message_sections` 缺失时作为 fallback）
  - `assistant_message_sections`：结构化消息块数组，每项包含：
    - `type`: `"good_news"` | `"attention"` | `"plan"` | `"encouragement"` — 决定 icon 和颜色
    - `title`: 简短标签（如「好消息」「需要留意」「我们准备了什么」「您已经做得很好」）
    - `content`: 该部分 1–2 句话
  - `personalized_evidence`（推荐）：
    - 3–5 项数组，每项为 `{ "title": "...", "evidence": "...", "why_it_matters": "...", "category": "history|surgery|medication|lab|symptom|monitoring" }`
    - 用来明确告诉患者：当前建议分别是根据哪些病史、药物反应、手术恢复阶段、检查异常或近期监测变化得出的
    - 若存在用药反应、术后恢复、检查异常，至少各覆盖 1 项
  - `adherence_analysis`：对象，包含：
    - `period`：字符串，如 `"过去 14 天"`
    - `medication`：对象 `{ "status": "...", "issues": "...", "adjustments": "..." }`
    - `appetite`：对象 `{ "status": "...", "cause_if_known": "...", "suggestions": "..." }`
    - `exercise`：对象 `{ "status": "...", "barriers": "...", "plan": "..." }`
    - `monitoring`：对象 `{ "status": "...", "gaps": "..." }`
  - `health_guidance`：有说服力、结合患者疾病和近期事件的健康指导对象：
    - `summary`：2–3 句，直接对患者说明当前情况和为什么这些建议重要
    - `tips`：数组，每项为 `{ "text": "...", "why": "...", "category": "protein|low_salt|low_oil|hydration|fiber|exercise|rest|monitoring" }`
  - `recommendations`：约 5–6 条具体可操作项。优先使用对象形式 `{ "text": "...", "reason": "...", "category": "medication|diet|exercise|monitoring|lifestyle" }`，`reason` 说明为什么适合该患者；也兼容纯字符串。
  - `nutrition_advice`：一段文字（**中文**，约 50–100 字）
  - `latest_health_summary`：对象，含 `blood_pressure`, `heart_rate`, `blood_oxygen`, `blood_glucose`, `steps_today`，值为带单位的字符串
  - `conditions`：字符串数组，如 `["高血压", "2型糖尿病", "高脂血症"]`
  - `diet_table`：`{"condition", "principle", "recommend", "avoid"}` 数组，全部**中文**
  - `weekly_meal_plan`：**仅 3 天**（前端循环至 7 天）。每天：`day`（`"第一天"` / `"第二天"` / `"第三天"`），`breakfast`, `lunch`, `dinner`；每餐为 `{"name", "icon", "condition", "benefit"}` 数组，`benefit` ≤ 约 10 个汉字
  - `diet_tips`：`{"icon", "title", "detail"}` 数组，**中文**
  - `reasoning`：2–3 句话（**中文**）
  - `guardrail`：免责声明（**中文**）

## 表达约束

- **语言**：默认中文；若 `meta.lang` 明确设为其他语言则跟随。
- **语气自适应（基于 `memory.tone_profile`）：**
  - `warm_encouraging`: 像关心患者的家人，肯定小进步，温和提醒。适合担心给家人添麻烦的老人。
  - `direct_practical`: 直接、务实，少情绪化表达，强调「要做什么、为什么」。
  - `authority_based`: 以照护团队/医生建议的方式表达，如「您的医生建议……」「根据照护团队评估……」。
  - `gentle_patient`: 更轻柔、更有耐心，重复关键点，如「慢慢来」「不用着急，但……」。
  - `tone_profile` 缺失时默认 `warm_encouraging`。
  - `health_guidance.summary` 和 `health_guidance.tips[].why` 必须体现所选语气。
- 引用 payload 中的具体近期事件（如「过去两周，您的食欲比平时低一些……」）。
- 若 payload 中存在具体药名、手术名、时间点、异常指标或医生备注，尽量在文案中保留这些具体锚点，而不是泛化成“您最近情况不太稳定”。
- `recommendations[].reason` 不能只写“适合高血压患者”“适合糖尿病患者”，应尽可能写成“因为您最近……所以这条建议更适合您”。
- 称呼用「您」。
- 不添加 payload 未支持的诊断。
- 数据源矛盾时在 `reasoning` 中说明。
- 食谱：恰好 **3 天**；每条 `benefit` 保持简短。
- 页面附近服务使用百度地图 API（`BAIDU_MAP_AK`）；除此之外，renderer 行为应与英文版保持一致。

## 参考资料

- `references/ref_adherence.md` — 依从性评估、风险标签、营养指导、语气规范
