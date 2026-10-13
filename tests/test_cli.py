from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from contract_diff.cli import main, render
from contract_diff import Finding


class CliTests(unittest.TestCase):
    def test_fixture_exit_codes_and_json_output(self):
        root = Path(__file__).resolve().parents[1]
        old = str(root / "examples/baseline.json")
        for filename, expected in (("compatible.json", 0), ("breaking.json", 1)):
            with self.subTest(filename=filename):
                result = subprocess.run([sys.executable, "-m", "contract_diff", old, str(root / "examples" / filename), "--format", "json", "--fail-on", "review"], cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report["summary"]["review"], 0)
                self.assertEqual(bool(report["summary"]["breaking"]), bool(expected))

    def test_invalid_input_returns_two_and_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            for content in ('{"openapi":', '{"a": 1, "a": 2}', '{"number": NaN}', '{"number": 1e999}', '{"openapi": "3.0.0"}'):
                with self.subTest(content=content):
                    path.write_text(content)
                    output, error = StringIO(), StringIO()
                    with redirect_stdout(output), redirect_stderr(error):
                        status = main([str(path), str(path)])
                    self.assertEqual(status, 2)
                    self.assertEqual(output.getvalue(), "")
                    self.assertIn("contract-diff:", error.getvalue())

    def test_review_flag_changes_failure_threshold(self):
        document = {"openapi": "3.1.1", "info": {}, "paths": {"/items": {"post": {"requestBody": {"content": {"application/json": {"schema": {"oneOf": [{"type": "string"}]}}}}, "responses": {"200": {"description": "OK"}}}}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(document))
            with redirect_stdout(StringIO()):
                self.assertEqual(main([str(path), str(path)]), 0)
                self.assertEqual(main([str(path), str(path), "--fail-on", "review"]), 1)

    def test_markdown_escapes_untrusted_contract_names(self):
        finding = Finding("GET /x|<script>", "/`name", "review", "CODE", "line\nbreak")
        report = render([finding], "markdown")
        self.assertIn("&#124;&lt;script&gt;", report)
        self.assertIn("&#96;name", report)
        self.assertNotIn("<script>", report)

    def test_missing_file_is_input_error(self):
        with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
            self.assertEqual(main(["does-not-exist.json", "also-missing.json"]), 2)


if __name__ == "__main__":
    unittest.main()
