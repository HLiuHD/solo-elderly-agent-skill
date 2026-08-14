# 康宁贝贝 Skill 架构草案

适用范围：
- 患者端遵从随访
- 紧急情况分流
- 医生确认后的患者回传

目标：
- 让 `Skill` 不只在对话结束后生成报告，也参与对话中的提问、安抚、补信息、升级和回传
- 把行为科学决策、技能路由、个性化表达拆开
- 兼容当前仓库已有的 report renderer 和 memory 输入结构

## 1. MVP 总原则

三层职责分离：

1. 行为科学层
决定“为什么干预”和“干预什么”
核心方法：`COM-B` + `BCT`

2. Skill 路由层
决定“当前调用哪类 skill”
核心输入：长期记忆、短期记忆、当前风险、医生状态、信息缺口

3. 内容生成层
决定“怎么说出来”
核心输出：对话回复、追问、安抚话术、报告、卡片、医生回传说明

一句话总结：
`Router` 选流程，`Planner` 定干预，`Skill` 决表达，`Renderer` 负责最终产物。

## 2. 总体流程

### 2.1 遵从流程

1. 读取长期记忆
2. 合并短期记忆和当轮信号
3. 形成 `PatientSnapshot`
4. 判断是否缺背景信息
5. 用 `InterventionPlanner` 生成本轮干预目标
6. 生成 `SkillPlan`
7. 调用对应 dialogue skill
8. 将本轮信息写入短期记忆
9. 在合适时机调用 report skill 生成总结/卡片/报告

### 2.2 紧急流程

1. 读取长期记忆
2. 接收异常信号和当前用户表达
3. 形成 `PatientSnapshot`
4. `SafetyRouter` 判断是否进入紧急流程
5. 调用 `emergency-calming-dialogue`
6. 生成医生端摘要并发给真人医生
7. 状态切换为 `awaiting_doctor_review`
8. 医生确认或修改后，更新 `CaseState`
9. 调用 `doctor-confirmation-return`
10. 必要时调用 `emergency-instruction-renderer`

## 3. 记忆分层

## 3.1 长期记忆

作用：
- 放患者背景和稳定偏好
- 作为个性化对话和干预策略的基础

建议字段：

```json
{
  "patient_profile": {
    "patient_id": "p_001",
    "preferred_name": "王阿姨",
    "age": 76,
    "gender": "female",
    "living_status": "alone",
    "caregiver_support": "limited"
  },
  "medical_background": {
    "diagnoses": ["高血压", "2型糖尿病"],
    "long_term_medications": ["缬沙坦", "二甲双胍"],
    "allergies": [],
    "past_surgeries": [],
    "important_risks": ["跌倒风险", "夜间低血糖风险"]
  },
  "behavior_profile": {
    "communication_style": "warm_encouraging",
    "information_density": "simple_focused",
    "motivation_style": "positive_reinforcement",
    "known_barriers": ["怕麻烦别人", "不喜欢复杂记录"],
    "known_preferences": ["面食", "晨间沟通"],
    "disliked_interventions": ["长篇教育内容"]
  },
  "care_context": {
    "doctor_team": ["dr_zhang"],
    "preferred_hospital": "xx医院",
    "emergency_contact_available": false
  },
  "memory_completeness": {
    "profile_complete": true,
    "medication_complete": false,
    "preference_complete": false,
    "care_context_complete": true
  }
}
```

说明：
- `memory_completeness` 非常关键，用于判断是否进入 `missing-background-collector`
- 长期记忆不全不是异常，而是一种显式状态

## 3.2 短期记忆

作用：
- 放当前会话、当天状态、最近 24 小时到 14 天内的重要事实
- 用于 follow-up、风险判断、医生摘要和回传

建议字段：

```json
{
  "session_context": {
    "session_id": "sess_001",
    "current_stage": "followup",
    "started_at": "2026-08-03T10:00:00+08:00"
  },
  "today_facts": {
    "took_medication_today": true,
    "medication_notes": "早餐后服用降压药，午饭后忘记测血糖",
    "current_symptoms": ["头晕", "食欲差"],
    "latest_self_report": "今天没什么力气，不太想出门"
  },
  "recent_events": [
    {
      "type": "self_report",
      "time": "2026-08-03T10:05:00+08:00",
      "content": "今天早上吃药了"
    },
    {
      "type": "signal",
      "time": "2026-08-03T09:50:00+08:00",
      "content": "步数明显偏低"
    }
  ],
  "dialogue_state": {
    "last_questions": ["今天早上有没有按时吃药？"],
    "last_user_answers": ["吃了"],
    "open_questions": ["午饭后是否复测血糖"]
  }
}
```

## 4. 核心对象

## 4.1 PatientSnapshot

定义：
当前这一轮所有决策的统一输入对象。

用途：
- router 判断流程
- planner 选择干预机制
- skill 决定语气和提问
- renderer 生成最终产物

建议结构：

```json
{
  "meta": {
    "patient_id": "p_001",
    "lang": "zh",
    "current_time": "2026-08-03T10:10:00+08:00",
    "entry_intent": "adherence_followup"
  },
  "profile": {
    "preferred_name": "王阿姨",
    "age": 76,
    "living_status": "alone",
    "diagnoses": ["高血压", "2型糖尿病"],
    "communication_style": "warm_encouraging"
  },
  "risk_context": {
    "patient_status": "at_risk",
    "risk_tags": ["活动量下降", "头晕", "服药监测不完整"],
    "doctor_required": false,
    "doctor_state": "none"
  },
  "adherence_context": {
    "medication_status": "partial_confirmed",
    "diet_status": "unclear",
    "exercise_status": "reduced",
    "monitoring_status": "missing_data"
  },
  "memory_gaps": [
    "午饭后血糖监测情况不明确",
    "长期药物剂量不完整"
  ],
  "signals": {
    "summary_text": "近24小时步数偏低，主诉轻度头晕",
    "anomalies": ["步数偏低"]
  },
  "latest_health": {
    "blood_pressure": "152/92 mmHg",
    "heart_rate": "76 bpm",
    "blood_glucose": "",
    "steps_today": "1200"
  },
  "user_message": "今天没什么力气，不太想出门"
}
```

## 4.2 InterventionPlan

定义：
这一轮干预的“医学和行为学决策结果”。

建议结构：

```json
{
  "plan_id": "ip_001",
  "scenario": "adherence",
  "com_b_assessment": {
    "capability": {
      "status": "partial_barrier",
      "evidence": ["患者监测动作不完整"]
    },
    "opportunity": {
      "status": "stable",
      "evidence": []
    },
    "motivation": {
      "status": "barrier",
      "evidence": ["表示没力气，不想出门"]
    },
    "behavior": {
      "target_behavior": "当天继续完成基础监测并维持用药"
    }
  },
  "intervention_function": [
    "enablement",
    "persuasion"
  ],
  "bct_strategies": [
    "self_monitoring",
    "feedback",
    "graded_task"
  ],
  "primary_goal": "补齐当日关键信息并降低放弃监测的概率",
  "secondary_goals": [
    "确认午后服药和监测",
    "保持轻量活动"
  ],
  "doctor_handoff_needed": false,
  "priority": "medium"
}
```

## 4.3 SkillPlan

定义：
这一轮要调用什么 skill，以及 skill 应如何表达。

建议结构：

```json
{
  "skill_plan_id": "sp_001",
  "skill_type": "adherence-followup-dialogue",
  "reason": "当前主要问题是动机下降和监测缺口，不需要医生介入",
  "tone": {
    "style": "warm_encouraging",
    "density": "simple_focused",
    "avoid": ["长篇医学解释", "命令式表达"]
  },
  "conversation_goal": "先确认当天关键依从信息，再给一个可执行的小动作",
  "must_cover": [
    "是否完成午后监测",
    "头晕是否持续",
    "是否愿意做一次简单记录"
  ],
  "must_avoid": [
    "制造额外焦虑",
    "给出超出医生授权的药物调整建议"
  ],
  "allowed_outputs": [
    "chat_text",
    "followup_question",
    "lightweight_card"
  ],
  "renderer_hint": "不生成完整报告，只生成本轮随访卡片"
}
```

## 4.4 CaseState

定义：
用于紧急场景和医生确认链路的状态机对象。

建议结构：

```json
{
  "case_id": "case_001",
  "case_type": "emergency",
  "state": "awaiting_doctor_review",
  "created_at": "2026-08-03T10:12:00+08:00",
  "doctor_review": {
    "status": "pending",
    "assigned_doctor_id": "dr_zhang",
    "doctor_note": ""
  },
  "patient_visible_status": {
    "title": "已通知医生",
    "message": "我们已经把您的情况发给医生，请先按页面提示休息并留意症状变化。"
  },
  "next_action": "wait_for_doctor_feedback"
}
```

推荐状态枚举：

- `collecting_info`
- `followup_active`
- `awaiting_doctor_review`
- `doctor_confirmed`
- `doctor_modified_plan`
- `handoff_completed`
- `report_generated`

## 5. Router 设计

## 5.1 SafetyRouter

优先级最高，先判断要不要走紧急流程。

建议规则：

- 若出现高危体征或强烈危险主诉，直接进 `emergency`
- 若用户已在紧急流且医生未回复，优先维持 `awaiting_doctor_review`
- 若医生已确认，优先进入 `doctor-confirmation-return`

输出示例：

```json
{
  "route": "emergency",
  "reason": "用户主诉胸闷且血压异常，需进入医生复核流程",
  "doctor_handoff_needed": true
}
```

## 5.2 AdherenceRouter

在非紧急场景下判断当前更适合哪类对话 skill。

建议判定维度：

- 背景信息完整度
- 当前依从问题类型
- 障碍来源是能力、机会还是动机
- 是否已有连续多轮未完成行为
- 是否适合生成正式报告

输出候选：

- `missing-background-collector`
- `adherence-followup-dialogue`
- `behavior-barrier-explainer`
- `habit-activation-dialogue`
- `patient-report-renderer`

## 6. 推荐 Skill 架构表

| Skill 名称 | 类型 | 触发时机 | 主要输入 | 主要输出 | 备注 |
| --- | --- | --- | --- | --- | --- |
| `missing-background-collector` | dialogue | 长期记忆关键字段缺失时 | `PatientSnapshot` | 2到3个高价值补充问题 | 不生成报告 |
| `adherence-followup-dialogue` | dialogue | 常规随访 | `PatientSnapshot` + `SkillPlan` | 追问、鼓励、下一步动作 | 遵从主入口 |
| `behavior-barrier-explainer` | dialogue | 已识别障碍但患者不理解时 | `InterventionPlan` | 简短解释 + 减负建议 | 偏教育型 |
| `habit-activation-dialogue` | dialogue | 需要推动一个小行为时 | `InterventionPlan` | 小目标、提醒建议 | 偏行动激活 |
| `emergency-calming-dialogue` | dialogue | 紧急事件识别后 | `PatientSnapshot` + `CaseState` | 安抚、立即行动指引 | 与医生流联动 |
| `doctor-summary-builder` | handoff | 需要发给真人医生时 | `PatientSnapshot` | 医生端摘要 JSON | 给医生，不给患者 |
| `doctor-confirmation-return` | dialogue | 医生确认或修改建议后 | `CaseState` + 医生备注 | 面向患者的确认说明 | 必须有状态机 |
| `patient-report-renderer` | render | 需要正式患者报告时 | `PatientSnapshot` + `InterventionPlan` | HTML/卡片/总结页 | 对应现有 report skill |
| `emergency-instruction-renderer` | render | 紧急场景需要结构化页面时 | `CaseState` + 医生状态 | 紧急指引页 | 对应现有 emergency skill |

## 7. 遵从 MVP 的推荐落地方式

先做最小闭环，不要一开始铺太大。

### 第一阶段

- 保留现有 report renderer
- 新增 `PatientSnapshot`
- 新增 `InterventionPlan`
- 新增 `SkillPlan`
- 新增 `adherence-followup-dialogue`

### 第二阶段

- 新增 `missing-background-collector`
- 把长期记忆完整度接入 router
- 让不同年龄、独居状态、偏好进入 tone 控制

### 第三阶段

- 接入行为反馈闭环
- 比较不同 BCT 策略的效果
- 再考虑细化更多 skill

## 8. 紧急流程 MVP 的推荐落地方式

紧急场景重点不是“更长的说明”，而是“更清楚的状态推进”。

建议拆成 4 个步骤：

1. `emergency-calming-dialogue`
对患者说明发生了什么，现在先做什么。

2. `doctor-summary-builder`
把关键信息结构化发给真人医生。

3. `CaseState` 更新
状态切换为 `awaiting_doctor_review`。

4. `doctor-confirmation-return`
医生确认后，把确认信息清楚地返回给患者界面。

推荐医生状态枚举：

- `notified`
- `reviewing`
- `confirmed`
- `modified_plan`
- `escalate_to_er`

患者端回传文案建议只做三类：

- 已收到：医生已收到，正在查看
- 已确认：医生已确认当前建议
- 已修改：医生更新了建议，请以最新提示为准

## 9. 与当前仓库的映射

当前已有模块：

- [orchestrator.py](C:/Users/henry/Desktop/Agent Skill/orchestrator.py)
  - 适合继续承载流程编排
- [adherence-report-zh/SKILL.md](C:/Users/henry/Desktop/Agent Skill/adherence-report-zh/SKILL.md)
  - 可保留为 `patient-report-renderer`
- [emergency-instruction-zh/SKILL.md](C:/Users/henry/Desktop/Agent Skill/emergency-instruction-zh/SKILL.md)
  - 可保留为 `emergency-instruction-renderer`
- [skill_input_example.md](C:/Users/henry/Desktop/Agent Skill/skill_input_example.md)
  - 可扩展为 `PatientSnapshot` 输入规范

建议新增但先不必一次做完的模块：

- `router.py`
- `planner.py`
- `state_machine.py`
- `skills/adherence-followup-dialogue/SKILL.md`
- `skills/doctor-confirmation-return/SKILL.md`

## 10. 推荐的最小输入规范

如果只做 MVP，建议先统一成下面这组顶层对象：

```json
{
  "meta": {},
  "long_term_memory": {},
  "short_term_memory": {},
  "signals": {},
  "latest_health": {},
  "case_state": {},
  "doctor_feedback": {},
  "latest_user_message": ""
}
```

然后由 orchestrator 在运行时组装出：

- `PatientSnapshot`
- `InterventionPlan`
- `SkillPlan`

不要让上游直接手写这 3 个对象。
它们应该是系统内部统一生成的中间层。

## 11. 推荐优先级

如果只选 3 件最值得先做的事：

1. 定义 `PatientSnapshot`
2. 做 `adherence-followup-dialogue`
3. 做紧急场景的 `CaseState + doctor-confirmation-return`

原因：
- 这三件事最直接把 skill 从“报告后处理”前移到“对话核心”
- 它们不要求你们立刻补全所有长期记忆
- 它们能同时覆盖遵从和紧急两个主场景

## 12. 一个判断标准

如果系统每轮只能回答“报告生成好了”，那它还是 renderer 驱动。

如果系统每轮能够先回答下面三个问题，它才开始接近真正的 agent：

1. 我现在处于哪种流程状态？
2. 我这轮最该补什么信息或推动什么行为？
3. 我该调用哪类 skill 来说这句话？

