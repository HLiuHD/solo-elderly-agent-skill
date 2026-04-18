# Skill Dev Kit

这个工具包帮你快速理解和开发 skill。拿到手就能跑。

## 30 秒上手

```bash
cd skill-dev-kit

# 第一步：设一个 OpenAI key
export OPENAI_API_KEY="sk-..."

# 第二步：跑一下，看看 skill 长什么样
uv run python verify.py
```

跑完你会看到两个示范 skill 依次执行，最后输出 `ALL SKILLS PASSED` 就说明环境没问题。

> 没有 OpenAI key？可以先用 `--dry-run` 只跑脚本部分，不调 LLM：
> ```bash
> uv run python verify.py --dry-run
> ```

## 这个工具包里有什么

```
skill-dev-kit/
├── verify.py                    ← 验证脚本，一键跑通 skill
├── skill-development-guide.md   ← 开发规范（怎么写、有什么规则）
├── pyproject.toml               ← 依赖声明
└── examples/
    ├── health-report/           ← 示范 1：生成健康报告 HTML
    └── news-extractor/          ← 示范 2：抓网页 + 生成摘要
```

## 常用命令

```bash
# 跑全部示范
uv run python verify.py

# 只跑某一个
uv run python verify.py --skill health-report

# 不调 LLM，只测脚本能不能跑
uv run python verify.py --dry-run

# 把生成的 HTML 保存下来看看效果
uv run python verify.py --skill health-report --save-html

# 验证你自己写的新 skill
uv run python verify.py --skill-dir ./my-new-skill
```

## 可选配置

如果你用的不是 OpenAI 官方接口，可以覆盖：

```bash
export OPENAI_BASE_URL="https://your-endpoint/v1"
export SKILL_VERIFY_MODEL="gpt-4o-mini"
```

## 下一步

写 skill 看 [skill-development-guide.md](./skill-development-guide.md)。
