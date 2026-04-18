#!/usr/bin/env python3
"""
Standalone skill verification harness.

Replicates the real SkillRuntime + SkillManager three-phase pipeline:
    1. pre_llm  script  (optional)
    2. LLM generation   (required)
    3. post_llm script  (optional)

Only needs an OpenAI-compatible API key.  Reads skills from ./examples/.

Usage:
    # Set your key (OpenAI or any compatible endpoint)
    export OPENAI_API_KEY="sk-..."

    # Optionally override base URL / model
    export OPENAI_BASE_URL="https://api.openai.com/v1"
    export SKILL_VERIFY_MODEL="gpt-4o-mini"

    # Run both example skills
    uv run python verify.py

    # Run a specific skill
    uv run python verify.py --skill health-report
    uv run python verify.py --skill news-extractor

    # Run your own skill directory
    uv run python verify.py --skill-dir ./examples/health-report

    # Save the health-report HTML output
    uv run python verify.py --skill health-report --save-html
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

# ---------------------------------------------------------------------------
# Constants (mirroring real runtime)
# ---------------------------------------------------------------------------
_DEFAULT_TIMEOUT = 120
_DEFAULT_MAX_OUTPUT_BYTES = 512_000
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
_SUPPORTED_RESOURCE_SUFFIXES = {".md", ".txt", ".html", ".json", ".yaml", ".yml"}


# ---------------------------------------------------------------------------
# SkillRuntime — exact same logic as the real one
# ---------------------------------------------------------------------------
class SkillRuntime:
    """Execute skill scripts in a subprocess, passing payload via stdin."""

    def __init__(self, timeout: int = _DEFAULT_TIMEOUT, max_output: int = _DEFAULT_MAX_OUTPUT_BYTES):
        self.timeout = timeout
        self.max_output = max_output

    def execute(self, script_path: Path, payload_json: str, *, cwd: Path) -> dict:
        resolved = script_path.resolve()
        cwd_resolved = cwd.resolve()
        if not resolved.is_relative_to(cwd_resolved) and resolved != cwd_resolved:
            raise ValueError(f"Script path escapes skill directory: {resolved} not under {cwd_resolved}")
        if not resolved.is_file():
            raise FileNotFoundError(f"Script not found: {resolved}")

        cmd = self._build_command(resolved, cwd_resolved)
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd, input=payload_json, capture_output=True, text=True,
                timeout=self.timeout, cwd=str(cwd_resolved), encoding="utf-8",
            )
        except subprocess.TimeoutExpired:
            elapsed = int((time.perf_counter() - started) * 1000)
            return {"ok": False, "exit_code": -1, "stdout": "", "stderr": f"Timed out after {self.timeout}s", "elapsed_ms": elapsed}

        elapsed = int((time.perf_counter() - started) * 1000)
        stdout = self._truncate(proc.stdout)
        stderr = self._truncate(proc.stderr)
        return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "stdout": stdout, "stderr": stderr, "elapsed_ms": elapsed}

    @staticmethod
    def _build_command(script_path: Path, cwd: Path) -> list[str]:
        if (cwd / "pyproject.toml").is_file() and shutil.which("uv"):
            return ["uv", "run", "python", str(script_path)]
        return [sys.executable, str(script_path)]

    def _truncate(self, text: str) -> str:
        raw = text.encode("utf-8", errors="replace")
        if len(raw) > self.max_output:
            return raw[: self.max_output].decode("utf-8", errors="ignore") + "\n[truncated]"
        return text

    @staticmethod
    def parse_output(stdout: str) -> dict:
        stdout = stdout.strip()
        if not stdout:
            return {}
        try:
            data = json.loads(stdout)
            return data if isinstance(data, dict) else {"raw_output": data}
        except (json.JSONDecodeError, ValueError):
            return {"raw_output": stdout}


# ---------------------------------------------------------------------------
# Skill loading — exact same SKILL.md parsing
# ---------------------------------------------------------------------------
def load_skill(skill_dir: Path) -> dict:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md not found in {skill_dir}")

    raw = skill_md.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(raw)
    if m is None:
        raise ValueError(f"Missing YAML frontmatter in {skill_md}")

    meta = yaml.safe_load(m.group(1))
    instructions = m.group(2).strip()
    scripts_cfg = meta.get("scripts") or {}

    def _resolve_script(key: str) -> Optional[Path]:
        rel = scripts_cfg.get(key)
        if rel is None:
            return None
        p = (skill_dir / rel).resolve()
        if not p.is_relative_to(skill_dir.resolve()):
            raise ValueError(f"Script '{rel}' escapes skill directory")
        if not p.is_file():
            raise ValueError(f"Script not found: {p}")
        return p

    resources = _load_resources(skill_dir)

    return {
        "name": meta["name"],
        "description": meta["description"],
        "instructions": instructions,
        "dir": skill_dir,
        "pre_llm": _resolve_script("pre_llm"),
        "post_llm": _resolve_script("post_llm"),
        "resources": resources,
    }


def _load_resources(skill_dir: Path) -> list[dict]:
    resources = []
    for folder in ("references", "assets"):
        base = skill_dir / folder
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in _SUPPORTED_RESOURCE_SUFFIXES:
                continue
            try:
                content = p.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if content:
                resources.append({"path": str(p.relative_to(skill_dir)), "content": content})
    return resources


# ---------------------------------------------------------------------------
# Mock payload — matches real SkillContextBuilder output structure
# ---------------------------------------------------------------------------
def build_mock_payload(skill_name: str, user_message: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()

    base = {
        "meta": {
            "user_id": "test-user-001",
            "session_id": "test-session-001",
            "intent": "skill",
            "lang": "zh",
            "current_time": now,
        },
        "memory": {
            "patient_long_term_profile": (
                "张先生，68岁，男性。诊断：高血压2级（5年）、2型糖尿病（3年）。"
                "用药：氨氯地平 5mg qd、二甲双胍 500mg bid。无过敏史。BMI 25.8。"
            ),
            "recent_health_dynamics": (
                "近两周血压控制尚可，偶有晨起偏高（145/92）。血糖餐后偏高（9.2 mmol/L）。"
                "步数日均 4200 步，较上月下降。睡眠质量一般。"
            ),
        },
        "signals": {
            "start_ts": None,
            "end_ts": None,
            "summary_text": "近7天设备数据：血压波动偏大，心率正常范围",
            "anomalies": ["晨起血压偏高"],
        },
        "location": {
            "current": {"lat": 39.9042, "lon": 116.4074, "record_at": now},
            "records": [],
        },
        "adherence_analysis": {
            "medication": {"score": 0.85, "detail": "本周漏服1次（周三晚）"},
            "diet": {"score": 0.7, "detail": "钠摄入偶尔偏高"},
            "exercise": {"score": 0.6, "detail": "步数未达目标（6000步/天）"},
            "monitoring": {"score": 0.9, "detail": "血压监测规律"},
        },
        "outlier_analysis": {
            "anomalies": [
                {"type": "blood_pressure", "value": "148/95", "time": "2026-04-15 06:30", "severity": "moderate"},
            ]
        },
        "latest_health": {
            "blood_pressure": "138/85",
            "heart_rate": 72,
            "blood_oxygen": 97,
            "blood_glucose": 7.8,
            "steps": 3850,
        },
        "latest_user_message": user_message,
        "recent_dialog_summary": "",
    }

    return base


# ---------------------------------------------------------------------------
# Prompt builder — mirrors SkillManager._build_skill_prompt
# ---------------------------------------------------------------------------
def build_skill_prompt(skill: dict, payload: dict) -> str:
    sections = [
        "你现在要执行一个本地 skill。严格遵守下面这份 SKILL.md 的要求，只根据提供的 payload 产出结果。",
        f"[SKILL NAME]\n{skill['name']}",
        f"[SKILL DESCRIPTION]\n{skill['description']}",
        f"[SKILL BODY]\n{skill['instructions']}",
    ]

    if skill["resources"]:
        blocks = [f"## {r['path']}\n{r['content']}" for r in skill["resources"]]
        sections.append("[SKILL RESOURCES]\n" + "\n\n".join(blocks))

    if "script_data" in payload:
        sections.append(
            "[SCRIPT DATA]\n"
            "payload 中的 `script_data` 字段由 pre_llm 脚本自动采集，包含实时数据。"
            "请优先使用 script_data 中的数据来生成结果。"
        )

    sections.append(
        "[RUNTIME REQUIREMENT]\n"
        "不要输出解释，不要输出 markdown 代码块，只输出严格 JSON。\n"
        "输出必须包含这些顶层字段：message, structured_output。\n"
        "message 是给用户看的一句话；structured_output 是对象，包含 SKILL.md 要求的所有分析数据。\n"
        "如果 payload 里没有足够信息，明确说明缺失，不要编造。"
    )
    sections.append("[PAYLOAD]\n" + json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# LLM call via OpenAI SDK — response_format enforces our contract
# ---------------------------------------------------------------------------
def call_llm(prompt: str, skill_name: str) -> dict:
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", None)
    model = os.environ.get("SKILL_VERIFY_MODEL", "gpt-4o-mini")

    if not api_key:
        print("\n[ERROR] OPENAI_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url=base_url)

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": f"{skill_name}_result",
                "schema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                        "structured_output": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["message", "structured_output"],
                    "additionalProperties": False,
                },
            },
        },
        temperature=0,
    )

    raw = response.choices[0].message.content or "{}"
    data = json.loads(raw)

    # Validate contract
    if not isinstance(data.get("message"), str):
        raise RuntimeError(f"LLM returned invalid 'message' field")
    if not isinstance(data.get("structured_output"), dict):
        raise RuntimeError(f"LLM returned invalid 'structured_output' field")

    return data


# ---------------------------------------------------------------------------
# Three-phase pipeline — mirrors SkillManager.run_skill
# ---------------------------------------------------------------------------
def run_skill(skill: dict, payload: dict, *, save_html: bool = False) -> dict:
    runtime = SkillRuntime()
    skill_dir = skill["dir"]
    name = skill["name"]

    # --- Phase 1: pre_llm ---
    if skill["pre_llm"] is not None:
        print(f"  [1/3] Running pre_llm: {skill['pre_llm'].name} ...")
        result = runtime.execute(
            skill["pre_llm"],
            json.dumps(payload, ensure_ascii=False, default=str),
            cwd=skill_dir,
        )
        if not result["ok"]:
            raise RuntimeError(f"pre_llm failed (exit={result['exit_code']}): {result['stderr'][:300]}")
        payload["script_data"] = SkillRuntime.parse_output(result["stdout"])
        print(f"       Done in {result['elapsed_ms']}ms, script_data keys: {list(payload['script_data'].keys())}")
    else:
        print(f"  [1/3] No pre_llm script — skipped")

    # --- Phase 2: LLM ---
    print(f"  [2/3] Calling LLM ...")
    prompt = build_skill_prompt(skill, payload)
    started = time.perf_counter()
    llm_result = call_llm(prompt, name)
    elapsed = int((time.perf_counter() - started) * 1000)
    print(f"       Done in {elapsed}ms")
    print(f"       message: {llm_result['message']}")
    print(f"       structured_output keys: {list(llm_result['structured_output'].keys())}")

    # --- Phase 3: post_llm ---
    if skill["post_llm"] is not None:
        print(f"  [3/3] Running post_llm: {skill['post_llm'].name} ...")
        post_input = {"payload": payload, "llm_result": llm_result}
        result = runtime.execute(
            skill["post_llm"],
            json.dumps(post_input, ensure_ascii=False, default=str),
            cwd=skill_dir,
        )
        if result["ok"]:
            post_data = SkillRuntime.parse_output(result["stdout"])
            if "structured_output" in post_data and isinstance(post_data["structured_output"], dict):
                llm_result["structured_output"].update(post_data["structured_output"])
            print(f"       Done in {result['elapsed_ms']}ms, merged keys: {list(llm_result['structured_output'].keys())}")
        else:
            print(f"       [WARN] post_llm failed (non-fatal): {result['stderr'][:200]}")
    else:
        print(f"  [3/3] No post_llm script — skipped")

    # Build final client-facing response (mirrors build_skill_response)
    final = {
        "name": name,
        "message": llm_result["message"],
        "structured_output": llm_result["structured_output"],
    }

    # Optionally save HTML
    html = final["structured_output"].get("html")
    if save_html and html:
        out_path = Path(f"{name}-output.html")
        out_path.write_text(html, encoding="utf-8")
        print(f"\n  HTML saved to: {out_path.resolve()}")

    return final


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_result(name: str, result: dict) -> list[str]:
    """Check that the result matches the client-facing contract."""
    errors = []
    if result.get("name") != name:
        errors.append(f"name mismatch: expected '{name}', got '{result.get('name')}'")
    if not isinstance(result.get("message"), str) or not result["message"].strip():
        errors.append("'message' is missing or empty")
    so = result.get("structured_output")
    if not isinstance(so, dict):
        errors.append("'structured_output' is not a dict")
    return errors


# ---------------------------------------------------------------------------
# Skill discovery
# ---------------------------------------------------------------------------
_EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"

_DEFAULT_USER_MESSAGES = {
    "health-report": "帮我生成一份健康报告",
    "news-extractor": "帮我提取这篇新闻的内容 https://news.ycombinator.com/item?id=44013750",
}


def discover_skills() -> list[Path]:
    if not _EXAMPLES_DIR.exists():
        return []
    return sorted(p.parent for p in _EXAMPLES_DIR.glob("*/SKILL.md"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Skill verification harness — runs the same three-phase pipeline as the real system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Environment variables:
              OPENAI_API_KEY       Required. Your OpenAI API key.
              OPENAI_BASE_URL      Optional. Override the API endpoint.
              SKILL_VERIFY_MODEL   Optional. Model to use (default: gpt-4o-mini).

            Examples:
              uv run python verify.py                          # run all example skills
              uv run python verify.py --skill health-report    # run one skill
              uv run python verify.py --skill health-report --save-html
              uv run python verify.py --skill-dir /path/to/my-skill
        """),
    )
    parser.add_argument("--skill", type=str, help="Run a specific example skill by name")
    parser.add_argument("--skill-dir", type=str, help="Run a skill from a custom directory path")
    parser.add_argument("--message", type=str, help="Override the user message in the mock payload")
    parser.add_argument("--save-html", action="store_true", help="Save HTML output to file (if skill produces it)")
    parser.add_argument("--dry-run", action="store_true", help="Run pre/post scripts only, skip LLM call")
    args = parser.parse_args()

    print("=" * 60)
    print("  Skill Dev Kit — Verification Harness")
    print("=" * 60)

    # Determine which skills to run
    if args.skill_dir:
        skill_dirs = [Path(args.skill_dir)]
    elif args.skill:
        d = _EXAMPLES_DIR / args.skill
        if not d.exists():
            print(f"\n[ERROR] Skill directory not found: {d}")
            sys.exit(1)
        skill_dirs = [d]
    else:
        skill_dirs = discover_skills()
        if not skill_dirs:
            print("\n[ERROR] No skills found in ./examples/")
            sys.exit(1)

    all_passed = True

    for skill_dir in skill_dirs:
        print(f"\n{'─' * 60}")
        skill = load_skill(skill_dir)
        name = skill["name"]
        print(f"  Skill: {name}")
        print(f"  Dir:   {skill_dir}")
        print(f"  pre_llm:  {'yes — ' + skill['pre_llm'].name if skill['pre_llm'] else 'none'}")
        print(f"  post_llm: {'yes — ' + skill['post_llm'].name if skill['post_llm'] else 'none'}")
        print(f"{'─' * 60}")

        user_msg = args.message or _DEFAULT_USER_MESSAGES.get(name, "请执行这个 skill")
        payload = build_mock_payload(name, user_msg)

        if args.dry_run:
            print("\n  [dry-run] Skipping LLM call, testing scripts only.\n")
            runtime = SkillRuntime()
            if skill["pre_llm"]:
                print(f"  Running pre_llm ...")
                r = runtime.execute(skill["pre_llm"], json.dumps(payload, ensure_ascii=False, default=str), cwd=skill_dir)
                print(f"  ok={r['ok']}, exit={r['exit_code']}, elapsed={r['elapsed_ms']}ms")
                if r["ok"]:
                    sd = SkillRuntime.parse_output(r["stdout"])
                    print(f"  script_data keys: {list(sd.keys())}")
                else:
                    print(f"  stderr: {r['stderr'][:300]}")
                    all_passed = False
            if skill["post_llm"]:
                # Feed a minimal llm_result for post_llm testing
                mock_llm = {
                    "message": "测试消息",
                    "structured_output": {
                        "patient_name": "测试用户",
                        "overall_status": "stable",
                        "overall_summary": "整体健康状况良好",
                        "vitals": [{"label": "血压", "value": "138/85", "unit": "mmHg", "status": "high", "note": "偏高"}],
                        "risk_tags": ["血压偏高"],
                        "recommendations": [{"text": "注意低盐饮食", "priority": "high"}],
                        "reasoning": "根据近期数据综合评估。",
                        "adherence": {
                            "medication": {"status": "good", "detail": "按时服药"},
                            "diet": {"status": "fair", "detail": "钠摄入偶尔偏高"},
                            "exercise": {"status": "fair", "detail": "步数未达标"},
                            "monitoring": {"status": "good", "detail": "监测规律"},
                        },
                        "diet_guidance": [{"condition": "高血压", "principle": "低盐", "recommended": "蔬菜水果", "avoid": "腌制食品"}],
                        "summary_markdown": "整体控制尚可，需注意晨起血压。",
                    },
                }
                print(f"  Running post_llm ...")
                post_input = {"payload": payload, "llm_result": mock_llm}
                r = runtime.execute(skill["post_llm"], json.dumps(post_input, ensure_ascii=False, default=str), cwd=skill_dir)
                print(f"  ok={r['ok']}, exit={r['exit_code']}, elapsed={r['elapsed_ms']}ms")
                if r["ok"]:
                    pd = SkillRuntime.parse_output(r["stdout"])
                    so = pd.get("structured_output", {})
                    print(f"  output keys: {list(so.keys())}")
                    if "html" in so:
                        print(f"  html length: {len(so['html'])} chars")
                        if args.save_html:
                            out = Path(f"{name}-output.html")
                            out.write_text(so["html"], encoding="utf-8")
                            print(f"  HTML saved to: {out.resolve()}")
                else:
                    print(f"  stderr: {r['stderr'][:300]}")
                    all_passed = False
            continue

        try:
            result = run_skill(skill, payload, save_html=args.save_html)
        except Exception as exc:
            print(f"\n  [FAIL] {exc}")
            all_passed = False
            continue

        # Validate
        errors = validate_result(name, result)
        if errors:
            print(f"\n  [FAIL] Contract validation errors:")
            for e in errors:
                print(f"    - {e}")
            all_passed = False
        else:
            print(f"\n  [PASS] Contract validated — {name}")
            print(f"         name: {result['name']}")
            print(f"         message: {result['message']}")
            print(f"         structured_output keys: {list(result['structured_output'].keys())}")

    # Summary
    print(f"\n{'=' * 60}")
    if all_passed:
        print("  ALL SKILLS PASSED")
    else:
        print("  SOME SKILLS FAILED — check output above")
    print(f"{'=' * 60}")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
