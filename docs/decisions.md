# Comparison decisions

## Request and response changes point in opposite directions

A server must keep accepting requests that existing clients send. Adding an accepted enum value is fine; removing one rejects a previously valid request.

For responses, the client needs to keep accepting what the new server returns. A new enum value can break an exhaustive switch in a client. A smaller set of possible values is safe under this structural model.

The rules follow this distinction instead of treating every schema change the same way.

## A review finding is part of the result

General JSON Schema containment is much harder than comparing a few fields. `oneOf`, conditional schemas, patterns, and reference siblings can change meaning without a simple local rule. The checker reports a review finding rather than claiming that these cases passed.

An unchanged unsupported constraint still gets a review finding when reached. In release CI, `--fail-on review` prevents that gap from disappearing into a successful exit status.

## Resolve local references, retain report locations

The comparison follows references inside each document independently. It reports the location of the operation using the schema, so a shared component change can produce a finding for each affected endpoint.

Active schema pairs stop structural recursion. A plain reference cycle without a concrete schema is different: it cannot be compared and produces a review finding. Missing local targets are input errors. Remote references are never downloaded.

Locations use JSON Pointer escaping. Parameter locations are report selectors using `location:name`, not array indices that change when parameters are reordered; they are not all resolvable JSON Pointers.

## Keep the first version small

JSON input avoids choosing a YAML parser and its configuration. No network resolution means the result depends on the two files given to the command. No runtime dependencies makes the CLI easy to run in an existing Python job.

The checks are intentionally conservative around removed documented fields and response representations. Exact status keys and media types are compared without attempting negotiation or wildcard coverage. These choices are visible in the report and documented in the README.

## Reference

The object structure and parameter inheritance rules are based on the [OpenAPI 3.1.1 specification](https://spec.openapis.org/oas/v3.1.1.html). Compatibility classifications are this tool's policy, not a guarantee made by that specification.
