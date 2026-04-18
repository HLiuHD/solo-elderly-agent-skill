---
name: news-extractor
description: 当用户要求提取、抓取或分析新闻网页内容时激活。支持任意新闻URL的内容提取和摘要生成。
scripts:
  pre_llm: scripts/fetch_content.py
---

# News Extractor Skill

根据 `script_data` 中提取的网页内容，生成一份结构化摘要。

## 输入原则

- 优先使用 `payload.script_data` 中的实时采集数据（由 pre_llm 脚本提供）。
- `script_data` 包含 `title`（标题）、`paragraphs`（正文段落列表）、`images`（图片URL列表）。
- 不要编造内容；如果信息不足，明确说明。

## 输出要求

返回严格 JSON，顶层字段固定为：

- `message`: 一句话说明已完成提取。
- `structured_output`: 对象，包含：
  - `html`: 可为 null 或留空（news-extractor 不生成 HTML）
  - `detail`: 对象，至少包含：
    - `title`: 文章标题
    - `summary_markdown`: 文章内容摘要（Markdown 格式）
    - `source_url`: 原始链接
    - `paragraph_count`: 正文段落数
    - `image_count`: 图片数量
    - `key_points`: 关键要点列表

## 表达约束

- 语言默认中文。
- 忠实于原文内容，不添加原文没有的信息。
- 摘要控制在 300 字以内。
