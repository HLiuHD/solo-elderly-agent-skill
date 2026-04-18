# Skill 开发指南

## Skill 是什么

一句话：**skill = 一个 Python 脚本 + 一次 LLM 调用，打包在一起，输入输出格式固定。**

不是 agent，不是微服务，不需要自己起 HTTP 服务器。你只需要写一个文件夹、放几个文件，系统就能自动调度。


## Skill 怎么工作

每个 skill 最多分三步执行，中间那步（LLM）是必须的，前后两步是可选的：

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   pre_llm    │────▶│     LLM      │────▶│   post_llm   │
│  (可选脚本)   │     │  (必须执行)   │     │  (可选脚本)   │
│              │     │              │     │              │
│ 作用：提前拉数据│     │ 作用：生成结果  │     │ 作用：后处理   │
│ 比如抓网页     │     │ 比如写摘要     │     │ 比如渲染 HTML  │
└──────────────┘     └──────────────┘     └──────────────┘
      ▲                                         │
      │           系统自动传入 payload              │
      └─────────────── stdin JSON ──────────────▶│
                                                 ▼
                                          最终返回给前端：
                                          {name, message, structured_output}
```

**两个现成的例子帮你理解：**

| 示范 | 模式 | 流程 | 适合场景 |
|------|------|------|---------|
| **health-report** | 只有 post_llm | LLM 生成报告数据 → 脚本渲染成 HTML | 报告、总结、网页型结果 |
| **news-extractor** | 只有 pre_llm | 脚本先抓网页 → LLM 基于抓到的内容写摘要 | 需要先拉外部数据再让 LLM 处理 |


## 创建一个新 skill：4 步完成

### 第 1 步：建文件夹

```
my-skill/
├── SKILL.md              ← 必须有，定义 skill 的名字、触发条件、LLM 指令
└── scripts/
    └── pre_llm.py        ← 可选，看你需要 pre_llm 还是 post_llm 还是都不要
```

### 第 2 步：写 SKILL.md

这个文件分两部分——上面是配置头（YAML），下面是给 LLM 看的指令（Markdown）：

```yaml
---
name: my-skill
description: 当用户要求 XXX 时触发（这句话决定了系统会不会把请求分配给你的 skill）
scripts:
  pre_llm: scripts/pre_llm.py    # 没有就删掉这行
  post_llm: scripts/post_llm.py  # 没有就删掉这行
---

# My Skill

## 输入原则
- 优先使用 script_data（如果有 pre_llm 的话）
- 缺少数据时说明缺失，不要编造

## 输出要求
- 严格 JSON
- 必须包含 message 和 structured_output 两个字段

## 表达约束
- 默认中文
```

> **`description` 很重要！** 系统根据这句话判断用户消息是否应该触发你的 skill。写得不清楚，就不会被触发。

### 第 3 步：写脚本（如果需要的话）

**pre_llm 脚本**（在 LLM 之前跑，用来提前准备数据）：

```python
import json, sys

# 系统会把完整 payload 通过 stdin 传给你
payload = json.load(sys.stdin)

# 你的处理逻辑...
user_msg = payload.get("latest_user_message", "")

# 输出 JSON 到 stdout，系统会自动挂到 payload["script_data"]
json.dump({"my_data": "xxx"}, sys.stdout, ensure_ascii=False)
```

**post_llm 脚本**（在 LLM 之后跑，用来加工 LLM 的输出）：

```python
import json, sys

# 系统会传入 {"payload": {...}, "llm_result": {...}}
data = json.load(sys.stdin)
llm_result = data.get("llm_result") or {}
structured_output = llm_result.get("structured_output") or {}

# 加工后输出，系统只会取 structured_output 合并回去
json.dump({
    "structured_output": {
        **structured_output,
        "html": "<div>渲染后的内容</div>",
    }
}, sys.stdout, ensure_ascii=False)
```

### 第 4 步：验证

```bash
uv run python verify.py --skill-dir ./my-skill
```

看到 `PASS` 就行了。


## 脚本需要装第三方包怎么办

如果你的脚本只用 Python 标准库，什么都不用加。

如果需要第三方包（比如 `httpx`），在 skill 目录下加一个 `pyproject.toml`：

```toml
[project]
name = "my-skill"
version = "0.1.0"
description = "my skill scripts"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
]
```

然后运行一次 `uv lock` 生成 `uv.lock` 文件。

系统检测到 `pyproject.toml` 后会自动用 `uv run python` 执行你的脚本，依赖会自动安装，不需要手动管理 `.venv`。

> 参考 `examples/news-extractor/`，它就是这么做的。


## 输入：系统会给你什么数据

系统会自动构造一个 payload JSON 传给你的 skill，长这样：

```json
{
  "meta": {
    "user_id": "用户ID",
    "session_id": "会话ID",
    "lang": "zh",
    "current_time": "2026-04-15T10:00:00"
  },
  "memory": {
    "patient_long_term_profile": "患者基本信息、病史、用药...",
    "recent_health_dynamics": "近期健康变化..."
  },
  "latest_health": {
    "blood_pressure": "138/85",
    "heart_rate": 72,
    "blood_oxygen": 97,
    "blood_glucose": 7.8,
    "steps": 3850
  },
  "adherence_analysis": { ... },
  "outlier_analysis": { ... },
  "signals": { ... },
  "location": { ... },
  "latest_user_message": "用户说的话",
  "recent_dialog_summary": ""
}
```

**注意：**
- 不是每个字段都有值，很多可能是 `null` 或空字符串，你的 skill 要能容忍这种情况
- 用到什么就取什么，不用全部关心
- 如果你的 pre_llm 脚本补充了数据，它会出现在 `payload["script_data"]` 里


## 输出：你必须返回什么格式

**这是最重要的规则。** 不管你的 skill 做什么，最终返回给前端的格式固定是：

```json
{
  "name": "my-skill",
  "message": "给用户看的一句话",
  "structured_output": {
    // 你的具体数据放这里，格式自定义
  }
}
```

其中：
- `name` — 系统自动填，不用管
- `message` — **必须有**，一句话告诉用户结果（比如"您的报告已生成"）
- `structured_output` — **必须有**，是一个对象，具体内容你自己定义

常见的放法：
- 要返回 HTML → `structured_output.html`
- 要返回结构化明细 → `structured_output.detail`

> `message` 和 `structured_output` 是系统强制校验的，缺了会报错。


## 不能做什么（边界）

- **不要自己起 HTTP 服务或自定义执行器** — 统一用系统的 runtime
- **不要跑异步或长时间任务** — skill 是同步一次性的，默认 120 秒超时
- **不要编造数据** — 没有就说没有
- **不要在 structured_output 之外加自定义字段** — 前端只认 `{name, message, structured_output}`
- **脚本不能引用 skill 文件夹之外的文件** — 系统会拦截


## 可选：给 LLM 额外的参考资料

如果你想让 LLM 在生成时参考一些文本资料（比如指南、模板），可以放在这两个目录下：

```
my-skill/
├── references/    ← 放参考文档（.md, .txt, .json 等）
└── assets/        ← 放文本模板片段
```

这两个目录下的文本文件会**自动注入到 LLM 的 prompt 里**。

> 如果你有模板文件是给脚本读的（不是给 LLM 看的），放在 `templates/` 目录下，它不会被自动注入。参考 `health-report/templates/report.html`。


## 完整的目录结构参考

```
my-skill/
├── SKILL.md                ← 必须有
├── scripts/
│   ├── pre_llm.py          ← 可选
│   └── post_llm.py         ← 可选
├── references/             ← 可选，自动注入 LLM prompt
├── assets/                 ← 可选，自动注入 LLM prompt
├── templates/              ← 可选，仅供脚本读取
├── pyproject.toml          ← 可选，有第三方依赖时加
└── uv.lock                 ← 可选，和 pyproject.toml 配套
```


## Checklist：上线前检查

- [ ] `SKILL.md` 存在，frontmatter 里的 `name` 和 `description` 填好了
- [ ] `description` 写得足够清楚（系统靠它判断是否触发你的 skill）
- [ ] LLM 输出包含 `message` + `structured_output`
- [ ] 脚本只引用 skill 目录内的文件
- [ ] 脚本能在 120 秒内完成
- [ ] 缺少数据时不编造，而是明确说明
- [ ] 用 `verify.py` 跑通了
