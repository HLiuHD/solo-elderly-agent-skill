import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def render_json(script_path: str, input_path: str) -> dict:
    payload = (ROOT / input_path).read_text(encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ROOT / script_path)],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
        cwd=ROOT,
    )
    return json.loads(proc.stdout)


class SkillSchemaAndSubmitTests(unittest.TestCase):
    def assert_structured_output_shell(self, result: dict, category: str) -> None:
        structured_output = result["structured_output"]
        self.assertIn("title", structured_output)
        self.assertIn("category", structured_output)
        self.assertIn("html", structured_output)
        self.assertEqual(structured_output["category"], category)
        self.assertIsInstance(structured_output["html"], str)
        self.assertGreater(len(structured_output["html"]), 1000)

    def test_adherence_reports_match_main_service_schema(self) -> None:
        cases = [
            ("adherence-report-en/scripts/render_report.py", "adherence-report-en/test_input.json"),
            ("adherence-report-zh/scripts/render_report.py", "adherence-report-zh/test_input.json"),
        ]

        for script_path, input_path in cases:
            with self.subTest(script_path=script_path):
                result = render_json(script_path, input_path)
                self.assert_structured_output_shell(result, "adherence")
                structured_output = result["structured_output"]
                self.assertIsInstance(structured_output.get("detail"), dict)
                self.assertIsInstance(structured_output.get("escalations"), list)

    def test_emergency_instruction_matches_main_service_schema(self) -> None:
        result = render_json(
            "emergency-instruction-en/scripts/render_instruction.py",
            "emergency-instruction-en/test_input.json",
        )

        self.assert_structured_output_shell(result, "outlier")

    def test_submit_buttons_do_not_post_or_require_auth(self) -> None:
        template_paths = [
            ROOT / "adherence-report-en/templates/report.html",
            ROOT / "adherence-report-zh/templates/report.html",
        ]

        for template_path in template_paths:
            with self.subTest(template=str(template_path.relative_to(ROOT))):
                html = template_path.read_text(encoding="utf-8")
                self.assertIn("exportFeedbackJSON", html)
                self.assertIn("window.parent.postMessage", html)
                self.assertIn('type: "skill_feedback"', html)
                self.assertIn("feedback_id", html)
                self.assertIn("skill_feedback_result", html)
                self.assertNotIn("fetch(", html)
                self.assertNotIn("method: \"POST\"", html)
                self.assertNotIn("Authorization", html)
                self.assertNotIn("MEMORY_API", html)
                self.assertNotIn("SKILL_FEEDBACK_API", html)
                self.assertNotIn("AGENT_SERVICE_TOKEN", html)
                self.assertNotIn("downloadPayload", html)
                self.assertNotIn("pendingPreferencePayload", html)

    def test_english_meal_plan_uses_compact_stacked_layout(self) -> None:
        html = (ROOT / "adherence-report-en/templates/report.html").read_text(encoding="utf-8")

        self.assertIn('.section-card[data-section="meal_plan"] #mealContent .grid', html)
        self.assertIn("grid-template-columns:1fr !important", html)
        self.assertIn('.section-card[data-section="meal_plan"] .meal-card', html)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", html)

    def test_english_feedback_controls_use_friendly_text(self) -> None:
        template_html = (ROOT / "adherence-report-en/templates/report.html").read_text(encoding="utf-8")
        rendered_html = render_json(
            "adherence-report-en/scripts/render_report.py",
            "adherence-report-en/test_input.json",
        )["structured_output"]["html"]

        for html in (template_html, rendered_html):
            self.assertIn("Not for me", html)
            self.assertIn("feedback-skip", html)
            self.assertNotIn("👍", html)
            self.assertNotIn("👎", html)

        self.assertIn("Keep this", rendered_html)
        self.assertIn("Useful", rendered_html)

    def test_selected_feedback_state_overrides_runtime_button_styles(self) -> None:
        template_paths = [
            ROOT / "adherence-report-en/templates/report.html",
            ROOT / "adherence-report-zh/templates/report.html",
        ]

        for template_path in template_paths:
            with self.subTest(template=str(template_path.relative_to(ROOT))):
                html = template_path.read_text(encoding="utf-8")
                self.assertIn(".feedback-btn.liked", html)
                self.assertIn(".feedback-btn.disliked", html)
