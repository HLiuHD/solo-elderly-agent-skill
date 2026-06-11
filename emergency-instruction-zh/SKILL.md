---
name: emergency-instruction-zh
description: 当系统检测到异常体征或紧急/急症分诊，需要向患者传达清晰、简洁的行动指引时激活。这不是完整健康报告，而是紧急场景下的轻量指令页。不用于常规依从性报告。
scripts:
  post_llm: scripts/render_instruction.py
---

# 紧急指令（中文）

触发紧急或急症分诊时，生成**面向患者**的指令页：发生了什么、医生已传达的内容、现在该做什么、如何后续监测。

## 设计目标

这是一份**指令**，不是报告。保持简短、清晰、安抚。
- 患者（独居老人）可能焦虑——语气要 reassuring、支持性。
- 无饮食对照表、无食谱、无冗长分析。只保留当下最重要的事。
- 布局：情况说明 → 医生状态 → 立即行动 → 监测计划 → 就近就医。

## 输入原则

- 只使用 payload 中提供的数据，不编造体征或诊断。
- 数据来源优先级：
  1. `latest_health` — 触发警报的当前体征
  2. `memory.patient_long_term_profile` — 基本信息、病史、用药
  3. `signals` — 设备信号、异常标签、硬件警报
  4. `physician_response` — 医生审核状态与备注（如有）
  5. `location` — 患者位置，用于就近就医指引
- 字段无数据时使用空字符串，不要编造。

## 输出格式

严格 JSON，顶层字段：

- `message`：一句话，如 `"紧急指令已为您准备好。"`
- `structured_output`：对象，包含：
  - `patient_status`：只允许 `"at_risk"` | `"critical"`
  - `situation_summary`：2–3 句话，说明触发原因与当前关切（**中文**）
  - `physician_status`：只允许 `"notified"` | `"reviewed"` | `"approved_plan"` | `"modified_plan"`
  - `physician_note`：医生回复/修改摘要，尚未审核则为空字符串（**中文**）
  - `immediate_actions`：字符串数组，3–5 条当下应做的事（**中文**），如 `"测量血压并记录下来"`、`"若胸痛加重，请立即拨打 120"`
  - `monitoring_plan`：对象，含 `what_to_monitor`（字符串）、`frequency`（字符串，如 `"每 30 分钟一次"`）、`next_checkin`（字符串，如 `"系统将在 2 小时后再次联系您"`）
  - `nearest_care_instructions`：一段关于如何就近就医的文字（**中文**）
  - `latest_vitals`：对象，含 `blood_pressure`, `heart_rate`, `blood_oxygen`, `blood_glucose`，值为带单位的字符串
  - `conditions`：来自 profile 的已知疾病，如 `["高血压", "2型糖尿病"]`
  - `guardrail`：免责声明（**中文**）

## 表达约束

- **语言**：默认中文；若 `meta.lang` 明确设为其他语言则跟随。
- 语气：冷静、清晰、安抚。避免术语。使用「您」。
- 不添加 payload 未支持的诊断。
- 整体输出保持简洁——供紧急时刻快速阅读。

## 参考资料

- `references/ref_emergency.md` — 紧急触发条件与面向患者的升级协议
