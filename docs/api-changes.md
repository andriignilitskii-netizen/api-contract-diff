# API changes that look harmless in a diff

This walkthrough uses the example Inventory API contracts in this repository: [baseline](../examples/baseline.json), [compatible change](../examples/compatible.json), and [breaking change](../examples/breaking.json).

The question is whether a client written against the baseline can keep using the new contract. A schema can still be valid OpenAPI and fail that check.

## A required field needs a client migration

The baseline accepts this request body:

```json
{"name": "API design"}
```

In the proposed breaking contract, `category` becomes required. The same body is now invalid. A default in documentation would not update clients that already send the old body.

`X-Request-ID` changes from optional to required too. Request tracing is useful, but adding a mandatory header means existing clients have to change before the server enforces it.

For a staged rollout, keep the field optional while clients adopt it. Requiring it needs a known migration point or a separately versioned contract. This tool checks the schema change; it cannot tell whether all deployed clients have migrated.

## Request and response enums have opposite rules

Request `category` changes from `book | software` to `book`. A previously accepted request with `"category": "software"` is now rejected.

Response `status` changes from `draft | active` to `draft | active | archived`. The server can now return a value an existing client does not recognize.

The [compatible fixture](../examples/compatible.json) does the reverse: it accepts an additional request category and returns a smaller response enum. Those changes pass the supported structural rules. Whether dropping a response state changes product behavior still needs a separate review.

## Nullable and optional are different promises

The baseline promises a required string `id`. The breaking fixture changes two things:

```diff
- "type": "string"
+ "type": ["string", "null"]

- "required": ["id", "name", "status"]
+ "required": ["name", "status"]
```

Now `id` may be null when present, and it may be missing altogether. A client that safely calls a string method on the old required field has lost both assumptions. The checker reports the type change and the lost required guarantee separately.

## Reproduce the report

```sh
python -m contract_diff examples/baseline.json examples/breaking.json --format markdown --fail-on review
```

The command exits with `1` and reports eight breaking findings:

| Change | Finding |
| --- | --- |
| Removed `GET /health` | `OPERATION_REMOVED` |
| Required `X-Request-ID` header | `PARAMETER_REQUIRED` |
| Narrower request category enum | `ENUM_CHANGED` |
| Name length limit reduced from 80 to 40 | `BOUND_CHANGED` |
| Required request category | `REQUIRED_CHANGED` |
| Nullable response ID | `TYPE_CHANGED` |
| Wider response status enum | `ENUM_CHANGED` |
| Response ID no longer guaranteed | `REQUIRED_CHANGED` |

[Full report](../examples/report.md). The fixture exit codes are checked in [CLI tests](../tests/test_cli.py); the individual request/response rules, inherited parameters, and recursive references are covered in [engine tests](../tests/test_engine.py).

## Put the decision in CI

The [GitHub Action](github-action.md) writes the Markdown summary and a JSON report before returning a failing exit code. The author can see what failed without rerunning the command locally.

Its default threshold is `review`: an unsupported schema keyword blocks the gate until someone reviews it. This matters for `oneOf`, patterns, and other rules where a local structural comparison cannot establish compatibility. [Design notes](decisions.md) explain that boundary.
