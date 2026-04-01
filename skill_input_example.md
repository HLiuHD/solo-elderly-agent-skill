# Skill Input Example

这份文档定义 `solo-elderly` skill 的推荐输入结构。

目标：
- skill 只消费上游整理好的 JSON
- 第一版优先使用最核心的上下文
- 所有输入块保持平级，方便后续扩展

## Recommended Shape

```json
{
  "meta": {
    "user_id": "example_user_001",
    "session_id": "session_20260330_001",
    "intent": "medical_dialog",
    "lang": "zh",
    "current_time": "2026-03-30T09:30:00+08:00"
  },
  "memory": {
    "patient_long_term_profile": "患者，76岁，男性。既往有高血压、2型糖尿病、高脂血症。长期服药，长期生命体征基线相对稳定。",
    "recent_health_dynamics": "近2周内总体依从性尚可，但活动量下降。近期多次提到按时服药、饮食较清淡，无明确急性恶化证据。"
  },
  "signals": {
    "start_ts": "2026-03-23T10:08:03+08:00",
    "end_ts": "2026-03-23T11:08:03+08:00",
    "summary_text": "近1小时信号显示：心率轻度波动，步数偏低，未见明确高危急性异常。",
    "anomalies": [
      "心率轻度波动",
      "活动量偏低"
    ]
  },
  "location": {
    "current": {
      "lat": 39.9042,
      "lon": 116.4074,
      "record_at": "2026-03-30T09:20:00+08:00"
    },
    "records": [
      {
        "latitude": 39.9042,
        "longitude": 116.4074,
        "recordAt": "2026-03-30T09:20:00+08:00",
        "source": "APP",
        "type": "gps"
      }
    ]
  },
  "adherence_analysis": {
    "statuses": [],
    "preferences": [],
    "interventions": [],
    "suggestions": []
  },
  "outlier_analysis": {
    "symptoms": [],
    "triage": null,
    "patient_suggestions": [],
    "doctor_suggestions": []
  },
  "latest_health": {
    "blood_pressure": null,
    "heart_rate": null,
    "blood_oxygen": null,
    "blood_glucose": null,
    "steps": null
  },
  "latest_user_message": "",
  "recent_dialog_summary": ""
}
```

## Core Fields

- `meta`
  - 请求元信息
- `memory`
  - 长期档案和近期动态
- `signals`
  - 当前信号窗口、自然语言总结、异常标签
- `location`
  - 最新位置点和原始位置记录

## Optional Reinforcement Fields

- `adherence_analysis`
  - 来自遵从链路的结构化结果
- `outlier_analysis`
  - 来自异常链路的结构化结果
- `latest_health`
  - 最新原始健康值
- `latest_user_message`
  - 当前最新一轮用户表达
- `recent_dialog_summary`
  - 近期对话摘要

这些字段是补强，不应成为 skill 能否运行的前提。

## Current Mapping In This Repo

- `memory.patient_long_term_profile`
  - 对应 `PipelineState.memory.memory_archive.scenario_answer`
- `memory.recent_health_dynamics`
  - 对应 `PipelineState.memory.search.scenario_answer`
- `signals.*`
  - 对应 `PipelineState.signals`
- `location.*`
  - 可由 openapi 的 `LOCATION` 数据补入
- `adherence_analysis`
  - 可来自 scenario bundle 中的 adherence 聚合结果
- `outlier_analysis`
  - 可来自 scenario bundle 中的 outlier 聚合结果
- `latest_health`
  - 可来自 openapi 的 `health-latest`

## Design Notes

- 第一版最核心的是 `memory + signals + location`
- 其余字段全部保持平级，但默认按可选补强理解
- 位置相关的天气、设施、社区活动等派生查询，不必提前放进 input；拿到 `location` 后由 skill 侧自行处理即可
