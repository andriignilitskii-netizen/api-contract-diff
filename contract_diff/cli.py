import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

from .engine import Finding, InputError, compare


def load(path: Path) -> dict:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InputError(f"{path}: duplicate JSON key {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise InputError(f"{path}: invalid JSON number {value}")

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise InputError(f"{path}: JSON number exceeds supported floating-point range")
        return result

    with path.open(encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=unique_object, parse_constant=invalid_constant, parse_float=finite_float)


def markdown_cell(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "&#124;").replace("`", "&#96;").replace("\n", " ").replace("\r", " ")


def render(findings: list[Finding], format_name: str) -> str:
    breaking = sum(f.severity == "breaking" for f in findings)
    review = len(findings) - breaking
    summary = f"{breaking} breaking, {review} review"
    if format_name == "json":
        return json.dumps({"summary": {"breaking": breaking, "review": review}, "findings": [asdict(f) for f in findings]}, indent=2, ensure_ascii=False)
    if format_name == "markdown":
        lines = ["## API contract comparison", "", summary, "", "| Severity | Operation | Code | Location | Detail |", "| --- | --- | --- | --- | --- |"]
        lines.extend("| " + " | ".join(markdown_cell(v) for v in (f.severity, f.operation, f.code, f.pointer, f.message)) + " |" for f in findings)
        if not findings:
            lines.append("\nNo incompatibilities detected by the supported structural rules.")
        return "\n".join(lines)
    lines = [summary]
    for finding in findings:
        lines.extend([f"{finding.severity.upper()} {finding.operation} [{finding.code}]", f"  {finding.pointer}", f"  {finding.message}"])
    if not findings:
        lines.append("No incompatibilities detected by the supported structural rules.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare OpenAPI 3.1 JSON contracts for compatibility with existing clients.")
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    parser.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    parser.add_argument("--fail-on", choices=("breaking", "review"), default="breaking", help="review also fails on unsupported rules and ambiguous changes")
    args = parser.parse_args(argv)
    try:
        findings = compare(load(args.old), load(args.new))
    except (OSError, UnicodeError, json.JSONDecodeError, InputError, RecursionError) as exc:
        print(f"contract-diff: {exc}", file=sys.stderr)
        return 2
    print(render(findings, args.format))
    return int(any(f.severity == "breaking" or args.fail_on == "review" for f in findings))
