---
name: doctor-report
description: 当系统需要为医生生成患者的临床分诊报告、风险评估摘要、随访审核报告时激活。面向临床医生，语言专业简练。不用于患者端的健康报告或营养建议。
scripts:
  post_llm: scripts/render_report.py
---

# 医生端分诊报告 Skill

根据 payload 中的患者数据，生成一份面向临床医生的分诊审核报告，包含患者概况、风险评估、体征数据和干预建议。

## 设计目标

这是一份给临床医生看的专业报告——语言简练、数据完整、逻辑清晰。
重点关注分诊等级判断、风险标签、临床推理和干预建议。

## 输入原则

- 只使用 payload 中提供的数据，不编造任何数值或诊断。
- 数据来源优先级：
  1. `latest_health` — 最新体征（血压、心率、血氧、血糖、步数）
  2. `memory.patient_long_term_profile` — 患者基本信息、病史、用药
  3. `memory.recent_health_dynamics` — 近期健康动态
  4. `signals` — 设备信号摘要、异常标签、信号窗口
  5. `adherence_analysis` — 依从性分析
  6. `outlier_analysis` — 离群值/异常分析
  7. `location` — 患者位置信息
- 某个维度无数据时，明确标注"暂无数据"，不要编造。

## 输出格式

严格 JSON，顶层字段：

- `message`: 一句话，如"患者分诊报告已生成"
- `structured_output`: 对象，包含：
  - `patient_profile`: 对象，包含 `name`, `age`, `gender`, `diagnoses`(数组), `medications`(数组), `baseline_note`
  - `patient_status`: 只允许 "stable" | "at_risk" | "critical"
  - `triage_level`: 只允许 "non_urgent" | "semi_urgent" | "urgent" | "emergency"
  - `risk_tags`: 字符串数组，如 ["心率轻度波动", "活动量偏低"]
  - `assistant_message_doctor`: 给医生的临床备注（150-300字，中文），包含病情摘要、数据解读和建议
  - `reasoning`: 临床推理文本（100-200字），说明分诊判断依据
  - `signals_summary`: 对象，包含 `window`(信号窗口), `description`(信号描述), `anomalies`(异常数组)
  - `latest_vitals`: 对象，包含 `blood_pressure`, `heart_rate`, `blood_oxygen`, `blood_glucose`, `steps`
  - `adherence_analysis`: 对象，包含 `statuses`(数组), `preferences`(数组), `interventions`(数组), `suggestions`(数组)
  - `recommendations`: 字符串数组，5条左右临床级别的干预建议
  - `nutrition_plan_summary`: 对象，包含 `conditions_addressed`(数组), `diet_principles`(数组), `weekly_plan_generated`(bool), `plan_note`
  - `guardrail`: 免责声明文本

## 表达约束

- 语言跟随 `meta.lang`，默认中文。
- 使用专业临床术语，但保持简洁。
- 分诊等级判断必须有明确依据。
- 不添加 payload 中没有的医学诊断。
- 数据矛盾时在 reasoning 中指出并标注不确定性。
