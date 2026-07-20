---
name: adherence-report-zh
description: 当用户（患者端）在常规随访中要求健康报告、健康总结、个性化营养建议或一周食谱时激活。聚焦近几天/几周的依从性——用药、食欲、运动、监测。不用于紧急或急症分诊场景。
scripts:
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

- 本 skill 当前只支持 MVP payload；旧 payload 字段即使存在也应忽略。
- 只使用 payload 中提供的数据，不编造体征、诊断或数值。
- 生成内容时，**必须优先引用患者自己的具体事实**，而不是只给疾病层面的通用建议。
  - 若 payload 中有病史、手术史、当前用药、药物反应、异常指标、设备异常、监测缺口，`assistant_message_patient`、`health_guidance.summary`、`health_guidance.tips[].why`、`recommendations[].reason` 都应尽量点出这些信息。
  - 推荐语要回答“为什么是这个人现在需要这条建议”，例如：因为术后恢复、因为服药后不适、因为最近血压/血氧变化、因为活动量下降。
- MVP 输入只依赖这些字段：
  1. `memory.archive` — 长期健康档案总摘要，来自 `memory_archive.scenario_answer`
  2. `memory.recent.adherence` — 近期依从动态总摘要，来自 `query_health_memory_by_type.light_summary_answer`
  3. `memory.recent.outlier` — 近期异常动态总摘要，来自 `query_health_memory_by_type.light_summary_answer`
  4. `latest_health` — 真实最新测量值；只展示 payload 中存在的指标
  5. `latest_health_meta` — 最新测量时间、来源、聚合说明
  6. `signal_trends` — 真实信号趋势，窗口为 `week` / `month` / `quarter`
  7. `adherence_analysis` — 当前依从对话结构化结果，输入形态为 `statuses[]` 和 `suggestions[]`
  8. `location`（可选）— 只有存在真实经纬度时才使用
  9. `patient`（可选）— 只有主服务提供时才使用称呼、性别、生日等基本信息
- 不要生成或要求 `ehr` / `clinical_context` / `recent_memory[]` / `topic` / `conversation` 这类重复或膨胀字段。
- 不要从 memory、EHR、病史或通用文案里推断最新体征数值。`latest_health` 没有的指标，输出也不要补。
- `blood_glucose` 只有当 `latest_health.blood_glucose` 或 `signal_trends.*.metrics.blood_glucose` 真实存在时才允许出现；否则不要展示血糖卡片、血糖趋势或血糖结论。
- 糖尿病可以作为长期病史用于主食管理和饮食提醒；但如果没有真实近期血糖监测，不要写“最近血糖偏高/偏低/控制良好”“平稳血糖”“影响血糖控制”等近期血糖结论。
- `adherence_analysis.statuses[]` 和 `adherence_analysis.suggestions[]` 是事实素材，不是页面文案。需要消化、拆分、合并和改写后再进入 `assistant_message_*`、`recommendations`、`nutrition_*`、`weekly_meal_plan`；不要把整段建议原封不动贴进一个卡片。
- 对漏服药物不要直接写“立即补服”“加服”“停药”或具体调整剂量；只能写“按医嘱/药品说明确认漏服处理方式，必要时联系医生或药师”，再给药盒、手机提醒、固定放置位置等执行建议。
- 若 payload 提到华法林/抗凝药，饮食建议必须强调“保持稳定”，不要建议突然增加或减少绿叶菜，不要写“每餐保证 X 克绿叶菜”这类会诱导摄入突变的目标。
- 除非 payload 明确提供，不要输出精确营养数字或硬性份量目标，例如每日食盐 X 克、蔬菜 X 克、热量、宏量营养素、百分比等。
- 不要把相关性写成确定因果；使用“可能相关”“可能增加负担”“建议观察”等措辞，避免“直接原因”“高度相关”“很快恢复”这类过度确定的话。
- 某维度无数据时，使用空字符串或空数组，不要编造。
- 新增上下文必须进入上述 MVP 字段之一，不要新增并行的重复字段。

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
  - `personalized_evidence`（必填）：
    - 3–5 项数组，每项为 `{ "title": "...", "evidence": "...", "why_it_matters": "...", "category": "history|surgery|medication|lab|symptom|monitoring" }`
    - 用来明确告诉患者：当前建议分别是根据哪些病史、药物反应、手术恢复阶段、检查异常或近期监测变化得出的
    - 必须由 `memory.archive` / `memory.recent.*` / `adherence_analysis` / `latest_health` 消化改写而来，不要直接复制长段原文
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
  - `recommendations`：约 5–6 条具体可操作项。优先使用对象形式 `{ "text": "...", "reason": "...", "category": "medication|diet|exercise|monitoring|lifestyle" }`，`reason` 说明为什么适合该患者；也兼容纯字符串。前 3 条会展示为“今天最值得先做的三件事”，必须由 AI 按优先级重新组织，不能只是复制 `suggestions[]`。
  - `nutrition_advice`：一段文字（**中文**，约 50–100 字），结合真实饮食/食欲/疾病事实，不要写成泛泛“清淡饮食”。
  - `nutrition_priorities`：3–4 项数组，每项为 `{ "title": "...", "action": "...", "reason": "...", "category": "low_salt|low_oil|protein|hydration|fiber|meal_rhythm" }`。这是 AI 生成的定性营养重点；不要输出百分比、热量、宏量营养素或“AI 估算”数值，除非 payload 明确提供。
  - `latest_health_summary`：对象，只包含 payload 中真实存在的最新指标。可用键包括 `blood_pressure`, `heart_rate`, `blood_oxygen`, `blood_glucose`, `steps_today`；缺失的键不要输出。renderer 最终会以 `payload.latest_health` 重建这一块
  - `conditions`：字符串数组，如 `["高血压", "2型糖尿病", "高脂血症"]`
  - `diet_table`：`{"condition", "principle", "recommend", "avoid"}` 数组，全部**中文**
  - `weekly_meal_plan`：**仅 3 天**（前端循环至 7 天）。每天：`day`（`"第一天"` / `"第二天"` / `"第三天"`），`breakfast`, `lunch`, `dinner`；每餐为 `{"name", "icon", "condition", "benefit"}` 数组，`benefit` ≤ 约 10 个汉字。食谱应由 AI 根据 payload 中的疾病、饮食问题、食欲/活动状态生成；没有足够依据时返回空数组，不要硬凑。
  - `diet_tips`：`{"icon", "title", "detail"}` 数组，**中文**
  - `reasoning`：2–3 句话（**中文**）
  - `guardrail`：免责声明（**中文**）

## 表达约束

- **语言**：默认中文；若 `meta.lang` 明确设为其他语言则跟随。
- **语气**：默认温暖、务实，像关心患者的家人；当前 MVP payload 不读取 `tone_profile`。
- 引用 payload 中的具体近期事件（如「过去两周，您的食欲比平时低一些……」）。
- 若 payload 中存在具体药名、手术名、时间点、异常指标或医生备注，尽量在文案中保留这些具体锚点，而不是泛化成“您最近情况不太稳定”。
- `recommendations[].reason` 不能只写“适合高血压患者”“适合糖尿病患者”，应尽可能写成“因为您最近……所以这条建议更适合您”。
- `recommendations[]` 可以给行为建议，但不要替代医生下医嘱。尤其是药物漏服，只能建议确认漏服处理方式和建立提醒机制。
- 称呼用「您」。
- 不添加 payload 未支持的诊断。
- 数据源矛盾时在 `reasoning` 中说明。
- 食谱：有足够依据时恰好 **3 天**，依据不足时返回空数组；每条 `benefit` 保持简短。
- 食谱和饮食表遇到华法林时，应优先写“摄入稳定”“不要突然大幅变化”，避免把菠菜、深色绿叶菜等写成突然加量的核心建议。
- 需要 AI 生成的内容包括：首屏总结、三件优先事项、AI 特别提醒、营养重点、营养建议和三天食谱。renderer 只负责隐藏缺失数据和展示结构，不负责创造这些内容。
- 页面附近服务只在 `location.current.lat` 和 `location.current.lon` 存在时展示；除此之外，renderer 行为应与英文版保持一致。

## 参考资料

- `references/ref_adherence.md` — 依从性评估、风险标签、营养指导、语气规范
