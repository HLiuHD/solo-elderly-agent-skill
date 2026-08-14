# 康宁贝贝 JSON Schema Guide

这份文档把 4 个核心中间层对象整理成标准 JSON Schema，方便你们做：

- orchestrator 中间层校验
- skill 输入输出契约固定
- 前后端联调
- memory patch 和状态机调试

## Schema 文件

- [patient_snapshot.schema.json](</C:/Users/henry/Desktop/Agent Skill/schemas/patient_snapshot.schema.json>)
- [intervention_plan.schema.json](</C:/Users/henry/Desktop/Agent Skill/schemas/intervention_plan.schema.json>)
- [skill_plan.schema.json](</C:/Users/henry/Desktop/Agent Skill/schemas/skill_plan.schema.json>)
- [case_state.schema.json](</C:/Users/henry/Desktop/Agent Skill/schemas/case_state.schema.json>)

## 使用建议

推荐把这 4 个对象作为系统内部中间层，而不是让上游直接手写。

建议顺序：

1. 上游提供原始输入
   - `long_term_memory`
   - `short_term_memory`
   - `signals`
   - `latest_health`
   - `doctor_feedback`
   - `latest_user_message`

2. orchestrator 生成并校验
   - `PatientSnapshot`
   - `InterventionPlan`
   - `SkillPlan`
   - `CaseState`

3. dialogue skill 和 renderer 只消费这些中间对象

## 对象分工

### `PatientSnapshot`

作用：
- 当前这一轮统一视图
- 给 router、planner、skill 共用

建议来源：
- 长期记忆
- 短期记忆
- 当前信号
- 最新用户表达

### `InterventionPlan`

作用：
- 承载 `COM-B / BCT` 决策结果
- 明确本轮主要目标和是否需要医生介入

### `SkillPlan`

作用：
- 决定调用哪类 skill
- 限制语气、输出形式和本轮必须覆盖内容

### `CaseState`

作用：
- 管理紧急链路和医生确认回传
- 让前端和 skill 都知道当前状态

## MVP 校验优先级

如果只先接最关键的两段，我建议优先校验：

1. `PatientSnapshot`
2. `CaseState`

原因：
- 一个决定对话路由
- 一个决定紧急场景状态推进

## 后续可继续补的 Schema

如果你们后面要扩展，可以再加这些：

- `doctor_summary.schema.json`
- `memory_patch.schema.json`
- `dialogue_turn_output.schema.json`
- `report_render_request.schema.json`

