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
- 数据来源优先级：
  1. `latest_health` — 最新体征（血压、心率、血氧、血糖、步数）
  2. `memory.patient_long_term_profile` — 基本信息、病史、用药
  3. `memory.recent_health_dynamics` — 近期健康动态
  4. `memory.key_events` — timestamped events（手术、反复症状、告警）
  5. `adherence_analysis` — 用药/饮食/运动/监测依从性
  5. `signals` — 设备信号、异常标签
  6. `outlier_analysis` — 异常分析
  7. `location` — 位置信息
  8. `user_preference`（可选）— 过往收集的患者偏好：菜系偏好、喜欢的建议/食物、不喜欢的建议/食物及原因
  9. `doctor_feedback`（可选）— 最新医生反馈和用药调整
- 若 `latest_health` 为空或全为 null，从 `memory.recent_health_dynamics` 或 `signals.summary_text` 推断最新值并填入 `latest_health_summary`。
- 某维度无数据时，使用空字符串或空数组，不要编造。
- 当 `user_preference.cuisine_preferences` 存在时，`weekly_meal_plan` 必须体现这些菜系偏好。

## 输出格式

严格 JSON，顶层字段：

- `message`：一句话，如 `"您的依从性报告已生成。"`
- `structured_output`：对象，包含：
  - `patient_status`：只允许 `"stable"` | `"at_risk"`（不含 `"critical"`——那属于 emergency-instruction）
  - `risk_tags`：字符串数组，如 `["活动量偏低", "食欲下降"]`
  - `assistant_message_patient`：温暖段落（**中文**，约 100–200 字）：近期依从性总结 + 鼓励 + 关键调整
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
- 语气：支持性、个性化。引用 payload 中的具体近期事件（如「过去两周，您的食欲比平时低一些……」）。
- 称呼用「您」。
- 不添加 payload 未支持的诊断。
- 数据源矛盾时在 `reasoning` 中说明。
- 食谱：恰好 **3 天**；每条 `benefit` 保持简短。

## 参考资料

- `references/ref_adherence.md` — 依从性评估、风险标签、营养指导、语气规范
