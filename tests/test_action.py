import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / ".github/action/runner.py"


class ActionTests(unittest.TestCase):
    def invoke(self, directory, old, new, threshold="review", extra=None):
        root = Path(directory)
        env = os.environ.copy()
        env.update(CONTRACT_DIFF_OLD=str(old), CONTRACT_DIFF_NEW=str(new), CONTRACT_DIFF_FAIL_ON=threshold,
                   CONTRACT_DIFF_REPORT=str(root / "reports/result.json"), GITHUB_OUTPUT=str(root / "outputs"),
                   GITHUB_STEP_SUMMARY=str(root / "summary.md"))
        env.update(extra or {})
        return subprocess.run([sys.executable, str(RUNNER)], cwd=root, env=env, capture_output=True, text=True)

    def test_compatible_contract_passes_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.invoke(root, ROOT / "examples/baseline.json", ROOT / "examples/compatible.json")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((root / "reports/result.json").read_text())
            self.assertEqual(report["status"], "compatible")
            self.assertEqual(report["summary"], {"breaking": 0, "review": 0})
            self.assertIn("exit_code=0", (root / "outputs").read_text())
            self.assertIn("No incompatibilities detected", (root / "summary.md").read_text())

    def test_breaking_contract_still_writes_report_before_failing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.invoke(root, ROOT / "examples/baseline.json", ROOT / "examples/breaking.json")
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads((root / "reports/result.json").read_text())
            self.assertEqual(report["status"], "breaking")
            self.assertEqual(report["summary"]["breaking"], 8)
            self.assertIn("PARAMETER_REQUIRED", (root / "summary.md").read_text())
            self.assertIn("status=breaking", (root / "outputs").read_text())

    def test_review_threshold_and_cli_agree(self):
        document = {"openapi": "3.1.1", "info": {}, "paths": {"/x": {"post": {"requestBody": {"content": {"application/json": {"schema": {"oneOf": [{"type": "string"}]}}}}, "responses": {"200": {"description": "OK"}}}}}}
        for threshold, expected in (("review", 1), ("breaking", 0)):
            with self.subTest(threshold=threshold), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "contract.json"
                path.write_text(json.dumps(document))
                result = self.invoke(root, path, path, threshold)
                cli = subprocess.run([sys.executable, "-m", "contract_diff", str(path), str(path), "--fail-on", threshold], cwd=ROOT, capture_output=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(result.returncode, cli.returncode)
                self.assertEqual(json.loads((root / "reports/result.json").read_text())["status"], "review")

    def test_invalid_input_has_error_report_and_unknown_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "invalid.json"
            path.write_text('{"openapi":')
            result = self.invoke(root, path, path)
            self.assertEqual(result.returncode, 2)
            report = json.loads((root / "reports/result.json").read_text())
            self.assertEqual(report["status"], "error")
            self.assertIsNone(report["summary"])
            self.assertIn("exit_code=2", (root / "outputs").read_text())

    def test_empty_required_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(directory, "", "")
            self.assertEqual(result.returncode, 2)
            self.assertIn("paths are required", result.stderr)

    def test_paths_with_spaces_are_plain_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "contract with spaces.json"
            path.write_bytes((ROOT / "examples/baseline.json").read_bytes())
            result = self.invoke(root, path, path)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_report_cannot_overwrite_a_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "contract.json"
            original = (ROOT / "examples/baseline.json").read_bytes()
            path.write_bytes(original)
            result = self.invoke(root, path, path, extra={"CONTRACT_DIFF_REPORT": str(path)})
            self.assertEqual(result.returncode, 2)
            self.assertEqual(path.read_bytes(), original)

    def test_failed_report_write_does_not_pass_the_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocker = root / "not-a-directory"
            blocker.write_text("x")
            result = self.invoke(root, ROOT / "examples/baseline.json", ROOT / "examples/compatible.json", extra={"CONTRACT_DIFF_REPORT": str(blocker / "result.json")})
            self.assertEqual(result.returncode, 2)
            self.assertIn("could not write CI report", result.stderr)

    def test_missing_github_environment_files_still_supports_local_run(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(directory, ROOT / "examples/baseline.json", ROOT / "examples/compatible.json", extra={"GITHUB_OUTPUT": "", "GITHUB_STEP_SUMMARY": ""})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("0 breaking, 0 review", result.stdout)

    def test_summary_write_error_does_not_leave_a_success_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.invoke(root, ROOT / "examples/baseline.json", ROOT / "examples/compatible.json", extra={"GITHUB_STEP_SUMMARY": str(root)})
            self.assertEqual(result.returncode, 2)
            report = json.loads((root / "reports/result.json").read_text())
            self.assertEqual(report["status"], "error")
            self.assertEqual(report["exit_code"], 2)

    def test_unknown_failure_threshold_is_configuration_error(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(directory, ROOT / "examples/baseline.json", ROOT / "examples/compatible.json", threshold="ignore")
            self.assertEqual(result.returncode, 2)
            self.assertIn("fail-on must be", result.stderr)


if __name__ == "__main__":
    unittest.main()
