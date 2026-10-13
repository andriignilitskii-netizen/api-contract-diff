# GitHub Action

The composite action runs the same comparison engine as the CLI. It writes a job summary, saves a JSON report, and returns the comparison's exit code. It needs Python 3.11+ already available as `python`; there is no package installation or network resolution during comparison.

## Workflow example

The two paths below should point to a baseline contract and the proposed contract in your checked-out workspace.

```yaml
name: Contract check
on: [pull_request]
permissions:
  contents: read
jobs:
  compare:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: '3.12'
      - id: diff
        uses: andriignilitskii-netizen/api-contract-diff@main
        with:
          old: contracts/baseline.json
          new: contracts/proposed.json
          fail-on: review
          report: artifacts/contract-diff.json
```

`@main` tracks development. Pin a reviewed commit SHA when adopting the action in a release workflow. Both schemas should be validated before this step; the checker deliberately supports only a subset of OpenAPI 3.1.

## Inputs and outputs

| Input | Default | Meaning |
| --- | --- | --- |
| `old` | Required | Baseline OpenAPI 3.1 JSON file |
| `new` | Required | Proposed OpenAPI 3.1 JSON file |
| `fail-on` | `review` | `review` rejects breaking and review findings; `breaking` rejects only breaking findings |
| `report` | `contract-diff-report.json` | Destination for a JSON execution report |

Paths are relative to the workflow's working directory, or absolute paths. Inputs are passed through environment variables rather than inserted into shell commands. The report path cannot resolve to either input file.

Outputs are `status`, `breaking`, `review`, and `exit_code`. Status is `compatible`, `breaking`, `review`, or `error`. Counts are empty on errors. A `review` status can return `0` only when the caller explicitly chooses `fail-on: breaking`.

The JSON report includes the same findings as CLI JSON output, plus `status` and `exit_code`. On an input error, it contains an error message and `summary: null`; unknown counts are not reported as zero. An unwritable report or summary makes the action fail with `2`.

## Failure reports and CI testing

Breaking findings return `1`, but the report and summary are written first. The action does not suppress the failure. Follow-up reporting steps can use `if: always()` to inspect or retain the saved JSON file.

The [repository workflow](../.github/workflows/ci.yml) tests the action itself with one compatible fixture and one breaking fixture. The breaking step has `continue-on-error: true` only so the test can verify its expected failure and inspect the report. The workflow then asserts that the step failed for a contract incompatibility. Release gates should use the ordinary failing behavior shown above.

[Action adapter tests](../tests/test_action.py) also cover review thresholds, malformed input, missing configuration, paths with spaces, input protection, and failed report writes. No token, repository write permission, or PR comment permission is required.

GitHub interfaces used here: [composite action metadata](https://docs.github.com/en/actions/reference/workflows-and-actions/metadata-syntax) and [job summaries/environment files](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands).
