"""Thin GitHub Actions adapter: write reports before returning a failing status."""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from contract_diff import InputError, compare
from contract_diff.cli import exit_code, load, markdown_cell, render


def append_environment_file(name: str, content: str) -> None:
    target = os.environ.get(name)
    if target:
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write(content)


def main() -> int:
    report_path = os.environ.get("CONTRACT_DIFF_REPORT", "contract-diff-report.json")
    report = {"status": "error", "exit_code": 2, "summary": None, "findings": []}
    status = 2
    try:
        old = os.environ.get("CONTRACT_DIFF_OLD", "")
        new = os.environ.get("CONTRACT_DIFF_NEW", "")
        threshold = os.environ.get("CONTRACT_DIFF_FAIL_ON", "review")
        if not old or not new:
            raise InputError("old and new contract paths are required")
        if threshold not in {"breaking", "review"}:
            raise InputError("fail-on must be breaking or review")
        if not report_path:
            raise InputError("report path must not be empty")
        if Path(report_path).resolve() in {Path(old).resolve(), Path(new).resolve()}:
            raise InputError("report path must not overwrite an input contract")
        findings = compare(load(Path(old)), load(Path(new)))
        status = exit_code(findings, threshold)
        report = json.loads(render(findings, "json"))
        summary = report["summary"]
        result = "breaking" if summary["breaking"] else "review" if summary["review"] else "compatible"
        report.update(status=result, exit_code=status)
        markdown = render(findings, "markdown") + "\n"
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        status = 2
        report = {"status": "error", "exit_code": 2, "summary": None, "findings": [], "error": str(exc)}
        markdown = "## API contract comparison\n\nInput error: " + markdown_cell(str(exc)) + "\n"
        print(f"contract-diff: {exc}", file=sys.stderr)

    try:
        # Never replace either contract, including on an input error.
        protected = {Path(value).resolve() for value in (os.environ.get("CONTRACT_DIFF_OLD"), os.environ.get("CONTRACT_DIFF_NEW")) if value}
        if report_path and Path(report_path).resolve() not in protected:
            target = Path(report_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        elif report_path:
            raise InputError("report path must not overwrite an input contract")
        else:
            raise InputError("report path must not be empty")
        append_environment_file("GITHUB_STEP_SUMMARY", markdown + "\n")
        counts = report["summary"] or {"breaking": "", "review": ""}
        append_environment_file("GITHUB_OUTPUT", f"status={report['status']}\nbreaking={counts['breaking']}\nreview={counts['review']}\nexit_code={status}\n")
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"contract-diff: could not write CI report: {exc}", file=sys.stderr)
        # If the JSON file was saved but publishing the summary failed, keep
        # the saved execution result consistent with the failing action.
        try:
            if report_path and Path(report_path).resolve() not in protected:
                failed = {"status": "error", "exit_code": 2, "summary": None, "findings": report["findings"], "error": str(exc)}
                Path(report_path).write_text(json.dumps(failed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            pass
        return 2
    print(markdown, end="")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
