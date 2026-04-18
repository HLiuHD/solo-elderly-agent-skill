---
name: health-report
description: 当用户明确要求基于个人健康信息生成完整的健康报告、随访总结、阶段性健康总览、HTML 报告页面或可分享网页时激活。不用于简单设备数据查询、口头解释或单条事件记录。
scripts:
  post_llm: scripts/render_report.py
---

# 健康报告 Skill

根据 payload 中的患者数据，生成一份面向用户的健康报告。

## 设计目标

这是一份给患者本人看的报告——语气亲切、排版清晰、信息密度适中。
不是给医生看的临床文档，不要使用过于专业的术语。

## 输入原则

- 只使用 payload 中提供的数据，不编造任何数值或诊断。
- 数据来源优先级：
  1. `latest_health` — 最新体征（血压、心率、血氧、血糖、步数）
  2. `memory.patient_long_term_profile` — 患者基本信息、病史、用药
  3. `memory.recent_health_dynamics` — 近期健康动态
  4. `adherence_analysis` — 用药/饮食/运动/监测依从性
  5. `signals` — 设备信号、异常标签
  6. `outlier_analysis` — 异常分析结果
- 某个维度无数据时，对应字段留空字符串或空数组，不要编造。

## 输出格式

严格 JSON，顶层字段：

- `message`: 一句话，如"您的健康报告已生成"
- `structured_output`: 对象，包含：
  - `html`: 完整 HTML 报告页面字符串（由 post_llm 脚本生成）
  - `detail`: 对象，包含以下分析数据字段（前端可选处理）：
    - `patient_name`: 从 profile 提取的姓名，无法提取则用"您"
    - `overall_status`: 只允许 "stable" | "attention" | "warning"
    - `overall_summary`: 一句话整体评价（口语化，称呼用"您"）
    - `vitals`: 数组，每项为 `{"label": "血压", "value": "138/82", "unit": "mmHg", "status": "normal|high|low", "note": "正常范围"}`
    - `risk_tags`: 字符串数组，如 ["活动量不足", "血压偏高"]
    - `recommendations`: 数组，每项为 `{"text": "建议内容", "priority": "high|medium|low"}`
    - `reasoning`: 一段 AI 分析依据文本（2-3 句话）
    - `adherence`: 对象，包含四个维度：
      - `medication`: `{"status": "good|fair|poor", "detail": "按时服药，未漏服"}`
      - `diet`: `{"status": "good|fair|poor", "detail": "..."}`
      - `exercise`: `{"status": "good|fair|poor", "detail": "..."}`
      - `monitoring`: `{"status": "good|fair|poor", "detail": "..."}`
    - `diet_guidance`: 数组（可为空），每项为 `{"condition": "高血压", "principle": "低盐饮食", "recommended": "蔬菜、水果", "avoid": "腌制食品"}`
    - `summary_markdown`: 2-3 句话的纯文本摘要

## 表达约束

- 语言跟随 `meta.lang`，默认中文。
- 称呼用"您"，语气像一个关心患者的健康管家。
- 不添加 payload 中没有的医学诊断。
- 数据矛盾时在 reasoning 中指出。
