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
        self.assertEqual(set(structured_output), {"title", "category", "html"})
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
                self.assertNotIn("fetch(", html)
                self.assertNotIn("method: \"POST\"", html)
                self.assertNotIn("Authorization", html)
                self.assertNotIn("MEMORY_API", html)
                self.assertNotIn("SKILL_FEEDBACK_API", html)
                self.assertNotIn("AGENT_SERVICE_TOKEN", html)
                self.assertNotIn("downloadPayload", html)

    def test_templates_include_mobile_app_layout_guards(self) -> None:
        template_paths = [
            ROOT / "adherence-report-en/templates/report.html",
            ROOT / "adherence-report-zh/templates/report.html",
        ]

        required_css = [
            "overflow-wrap:anywhere",
            "background:#f5f4fa",
            "border-radius:18px",
            "grid-template-columns:repeat(2,minmax(0,1fr))",
            ".meal-card > .flex",
            ".feedback-btn",
            "#customCuisineInput",
            "@media (max-width: 380px)",
        ]

        for template_path in template_paths:
            with self.subTest(template=str(template_path.relative_to(ROOT))):
                html = template_path.read_text(encoding="utf-8")
                for css in required_css:
                    self.assertIn(css, html)

    def test_feedback_controls_use_app_action_buttons(self) -> None:
        template_paths = [
            ROOT / "adherence-report-en/templates/report.html",
            ROOT / "adherence-report-zh/templates/report.html",
        ]

        for template_path in template_paths:
            with self.subTest(template=str(template_path.relative_to(ROOT))):
                html = template_path.read_text(encoding="utf-8")
                self.assertIn("feedback-action", html)
                self.assertIn("feedback-action-positive", html)
                self.assertIn("feedback-action-negative", html)
                self.assertNotIn(">👍</button>", html)
                self.assertNotIn(">👎</button>", html)

    def test_static_recommendation_feedback_buttons_refresh_state(self) -> None:
        cases = [
            ("adherence-report-en/scripts/render_report.py", "adherence-report-en/test_input.json"),
            ("adherence-report-zh/scripts/render_report.py", "adherence-report-zh/test_input.json"),
        ]

        for script_path, input_path in cases:
            with self.subTest(script_path=script_path):
                result = render_json(script_path, input_path)
                html = result["structured_output"]["html"]
                self.assertIn("data-feedback-key=", html)
                self.assertIn('data-feedback-type="like"', html)
                self.assertIn('data-feedback-type="dislike"', html)
                self.assertIn("saveLikeFromButton(this)", html)
                self.assertIn("showFeedbackModalFromButton(this)", html)
                self.assertIn("refreshStaticFeedbackButtons", html)

    def test_selected_feedback_state_overrides_runtime_button_styles(self) -> None:
        template_paths = [
            ROOT / "adherence-report-en/templates/report.html",
            ROOT / "adherence-report-zh/templates/report.html",
        ]

        for template_path in template_paths:
            with self.subTest(template=str(template_path.relative_to(ROOT))):
                html = template_path.read_text(encoding="utf-8")
                self.assertIn(".feedback-btn.liked", html)
                self.assertIn("background-color:#5b3fd6 !important", html)
                self.assertIn("color:#fff !important", html)
                self.assertIn(".feedback-btn.disliked", html)
                self.assertIn("background-color:#b5472b !important", html)
                self.assertIn("box-shadow:0 0 0 3px", html)
                self.assertIn(
                    "transition:transform .18s ease, filter .18s ease, box-shadow .18s ease",
                    html,
                )
                self.assertNotIn(".feedback-btn {{ opacity:1; transition:all .18s ease", html)
