# api-contract-diff

[![Tests](https://github.com/andriignilitskii-netizen/api-contract-diff/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/andriignilitskii-netizen/api-contract-diff/actions/workflows/ci.yml)

Compare two OpenAPI 3.1 JSON files before changing an API. The CLI reports structural changes that can break existing clients, with separate `review` findings for rules it cannot decide.

It runs offline and has no runtime dependencies. Python 3.11+.

Start with [the API-change walkthrough](docs/api-changes.md): a required header, narrower request enums, and nullable response IDs. [GitHub Action usage](docs/github-action.md) covers reports and release gates.

## Try it

```sh
python -m contract_diff examples/baseline.json examples/breaking.json
python -m contract_diff examples/baseline.json examples/compatible.json --fail-on review
python -m contract_diff examples/baseline.json examples/breaking.json --format markdown > report.md
```

Run from this repository, or install with `pip install .` and use `contract-diff` instead of `python -m contract_diff`.

An excerpt from the breaking example:

```text
BREAKING POST /items [PARAMETER_REQUIRED]
  /paths/~1items/post/parameters/header:x-request-id/required
  Request parameter became required.
```

Parameter names in report locations are normalized to lowercase for headers. [Full example report](examples/report.md).

## Rules

The comparison asks whether clients using the old contract can keep working with the new server.

| Change | Request | Response |
| --- | --- | --- |
| Type set becomes narrower | Breaking | Allowed |
| Enum gains values | Allowed | Breaking |
| Property becomes required | Breaking | Allowed |
| Required property becomes optional | Allowed | Breaking |
| Bounds become stricter | Breaking | Allowed |

The checker also reports removed operations, parameters, response statuses, and media types. Parameters inherited from path items are combined with operation overrides. Local `$ref` chains are followed; recursive schemas stop at already visited pairs.

Responses have two extra conservative rules: removing a documented optional property needs review, and adding a property to an explicitly closed response object is breaking. New response statuses or representations need review because clients may have to handle them.

## Use in CI

```sh
python -m contract_diff contracts/previous.json contracts/current.json --format json --fail-on review
```

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | No finding reached the selected failure threshold |
| `1` | Breaking change, or review finding with `--fail-on review` |
| `2` | Unreadable file, invalid JSON, unsupported OpenAPI version, or malformed structure used by the checker |

The default threshold is `breaking`; review findings still appear in the output. Use `--fail-on review` when the report gates a release. Output is deterministic and available as text, JSON, or Markdown.

The repository also contains a [composite GitHub Action](action.yml). Its default threshold is `review`, and it writes a job summary and JSON report before returning a failure. [Inputs, outputs, and workflow example](docs/github-action.md).

## Boundaries

This is a focused structural check, not a full OpenAPI validator or a proof of compatibility. Validate the contracts before comparing them, then review behavior changes separately.

- Input is JSON and OpenAPI 3.1 only. Export YAML to JSON first.
- Only matching operations and their shared schemas are compared. Unused components and new operations do not affect old clients and are not checked.
- Local JSON Pointer references are supported. Remote references, anchors, and constraints beside `$ref` produce review findings. Nothing is fetched from the network.
- Schema composition, patterns, `readOnly`/`writeOnly`, custom dialects, response headers, callbacks, webhooks, and other unsupported schema keywords produce review findings when reached.
- `format`, examples, descriptions, and defaults are treated as annotations. Runtime enforcement of those annotations is outside the rules.
- Optional request fields and parameters can be added. This assumes clients send documented fields; the tool does not reason about every possible unknown property in an open object.
- Schema constraints are checked independently, without proving their combined allowed value set. For example, replacing an inclusive bound with an equivalent exclusive bound can produce a conservative finding.
- Media types and response statuses are compared by exact key. Wildcard media ranges need review; the checker does not prove coverage by `default` or `2XX` responses.
- Auth and server changes need review. Business rules, side effects, pagination behavior, latency, and generated SDK differences require their own tests.

[Design notes](docs/decisions.md) explain the direction of the checks and the tradeoffs.

## Development

```sh
python -m unittest discover -s tests -v
```

Tests cover request/response direction, numeric and nullable types, enums, bounds, inherited parameters, reference cycles, escaped pointers, deterministic reports, malformed input, CLI exit codes, and the Actions adapter. CI runs on Python 3.11, 3.12, and 3.13, plus a separate job that exercises the composite action's pass and fail paths.
