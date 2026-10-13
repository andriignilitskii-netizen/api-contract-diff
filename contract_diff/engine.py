"""Structural compatibility rules, with explicit review findings for blind spots."""

from dataclasses import dataclass
import json
import re
from typing import Any
from urllib.parse import unquote


METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
TYPES = frozenset({"null", "boolean", "object", "array", "string", "number", "integer"})
ANNOTATIONS = frozenset({"title", "description", "default", "examples", "example", "deprecated", "format", "$comment"})
SUPPORTED = frozenset({"type", "enum", "const", "properties", "required", "items", "additionalProperties", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties"})


class InputError(ValueError):
    """Malformed input in a part of the document used by the comparison."""


@dataclass(frozen=True, order=True)
class Finding:
    operation: str
    pointer: str
    severity: str
    code: str
    message: str


def pointer(parent: str, key: str | int) -> str:
    return parent + "/" + str(key).replace("~", "~0").replace("/", "~1")


def obj(value: Any, where: str) -> dict:
    if not isinstance(value, dict):
        raise InputError(f"{where}: expected an object")
    return value


def array(value: Any, where: str) -> list:
    if not isinstance(value, list):
        raise InputError(f"{where}: expected an array")
    return value


def flag(value: dict, key: str, where: str, default: bool = False) -> bool:
    result = value.get(key, default)
    if not isinstance(result, bool):
        raise InputError(f"{where}/{key}: expected a boolean")
    return result


def enum_key(value: Any) -> str:
    # JSON true and 1 must stay distinct even though Python compares them equal.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number:" + str(value if isinstance(value, int) else int(value) if value.is_integer() else value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class Document:
    def __init__(self, value: Any, label: str):
        self.value = obj(value, label)
        self.label = label
        if not re.fullmatch(r"3\.1\.\d+", str(self.value.get("openapi", ""))):
            raise InputError(f"{label}: only OpenAPI 3.1 JSON documents are supported")
        obj(self.value.get("info"), f"{label}/info")
        obj(self.value.get("paths"), f"{label}/paths")

    def resolve(self, value: Any, where: str, engine: "Engine", operation: str, schema: bool = False) -> Any:
        visited = set()
        while isinstance(value, dict) and "$ref" in value:
            ref = value["$ref"]
            if not isinstance(ref, str):
                raise InputError(f"{self.label}{where}/$ref: expected a string")
            if not ref.startswith("#/"):
                engine.add(operation, where, "review", "UNSUPPORTED_REF", "Only local JSON Pointer references are followed.")
                return None
            if ref in visited:
                engine.add(operation, where, "review", "REF_CYCLE", "Reference chain has no concrete schema or object.")
                return None
            visited.add(ref)
            siblings = set(value) - {"$ref", "summary", "description"}
            if schema and siblings:
                engine.add(operation, where, "review", "REF_SIBLINGS", "Constraints beside $ref need manual review.")
            target: Any = self.value
            try:
                for token in unquote(ref[2:]).split("/"):
                    if re.search(r"~(?![01])", token):
                        raise KeyError(token)
                    token = token.replace("~1", "/").replace("~0", "~")
                    if isinstance(target, list):
                        if not re.fullmatch(r"0|[1-9]\d*", token):
                            raise KeyError(token)
                        target = target[int(token)]
                    elif isinstance(target, dict):
                        target = target[token]
                    else:
                        raise KeyError(token)
            except (KeyError, IndexError) as exc:
                raise InputError(f"{self.label}{where}: unresolved reference {ref}") from exc
            value = target
        return value


class Engine:
    def __init__(self, old: Any, new: Any):
        self.old = Document(old, "old")
        self.new = Document(new, "new")
        self.findings: set[Finding] = set()

    def add(self, operation: str, where: str, severity: str, code: str, message: str) -> None:
        self.findings.add(Finding(operation, where, severity, code, message))

    def object_ref(self, document: Document, value: Any, where: str, operation: str) -> dict | None:
        resolved = document.resolve(value, where, self, operation)
        return None if resolved is None else obj(resolved, document.label + where)

    def operations(self, document: Document) -> dict:
        result = {}
        for path, raw in document.value["paths"].items():
            if path.startswith("x-"):
                continue
            if not path.startswith("/"):
                raise InputError(f"{document.label}/paths: invalid path {path}")
            where = pointer("/paths", path)
            item = self.object_ref(document, raw, where, "API")
            if item is None:
                continue
            for method in sorted(METHODS & item.keys()):
                operation = f"{method.upper()} {path}"
                result[(path, method)] = (item, obj(item[method], document.label + pointer(where, method)))
                for key in ("callbacks",):
                    if key in item[method]:
                        self.add(operation, pointer(where, method), "review", "UNSUPPORTED_OPERATION", f"{key} is outside the comparison scope.")
        return result

    def parameters(self, document: Document, item: dict, operation_obj: dict, where: str, operation: str) -> dict:
        result = {}
        for parent in (item, operation_obj):
            local = set()
            for index, raw in enumerate(array(parent.get("parameters", []), document.label + where + "/parameters")):
                param = self.object_ref(document, raw, pointer(where + "/parameters", index), operation)
                if param is None:
                    continue
                name, location = param.get("name"), param.get("in")
                if not isinstance(name, str) or not isinstance(location, str) or location not in {"query", "header", "path", "cookie"}:
                    raise InputError(f"{document.label}{where}/parameters: invalid name or location")
                required = flag(param, "required", document.label + where)
                if location == "path" and not required:
                    raise InputError(f"{document.label}{where}/parameters: path parameter {name} must be required")
                identity = (location, name.lower() if location == "header" else name)
                if identity in local:
                    raise InputError(f"{document.label}{where}/parameters: duplicate {location} parameter {name}")
                local.add(identity)
                result[identity] = param
        return result

    def media(self, old: dict, new: dict, where: str, operation: str, direction: str) -> None:
        a = obj(old.get("content", {}), "old" + where + "/content")
        b = obj(new.get("content", {}), "new" + where + "/content")
        if any("*" in key for key in a.keys() | b.keys()):
            self.add(operation, where + "/content", "review", "MEDIA_RANGES", "Media type ranges need manual review.")
        for media_type in sorted(a.keys() - b.keys()):
            self.add(operation, pointer(where + "/content", media_type), "breaking", "MEDIA_TYPE_REMOVED", f"Documented {direction} media type was removed.")
        if direction == "response":
            for media_type in sorted(b.keys() - a.keys()):
                self.add(operation, pointer(where + "/content", media_type), "review", "RESPONSE_MEDIA_ADDED", "New response representation may require client handling.")
        for media_type in sorted(a.keys() & b.keys()):
            location = pointer(where + "/content", media_type)
            before = obj(a[media_type], "old" + location)
            after = obj(b[media_type], "new" + location)
            for value in (before, after):
                if value.get("encoding"):
                    self.add(operation, location, "review", "MEDIA_ENCODING", "Encoding rules are outside the comparison scope.")
            self.schema(before.get("schema", {}), after.get("schema", {}), location + "/schema", operation, direction, set())

    def schema(self, old: Any, new: Any, where: str, operation: str, direction: str, active: set) -> None:
        a = self.old.resolve(old, where, self, operation, schema=True)
        b = self.new.resolve(new, where, self, operation, schema=True)
        if a is None or b is None:
            return
        if not isinstance(a, (dict, bool)) or not isinstance(b, (dict, bool)):
            raise InputError(f"{where}: schema must be an object or boolean")
        identity = (id(a), id(b), direction)
        if identity in active:
            return
        active = active | {identity}
        if a is False or b is False:
            breaking = (direction == "request" and a is not False and b is False) or (direction == "response" and a is False and b is not False)
            if breaking:
                self.add(operation, where, "breaking", "BOOLEAN_SCHEMA_CHANGED", f"{direction.capitalize()} values no longer satisfy the previous compatibility direction.")
            return
        a = {} if a is True else a
        b = {} if b is True else b
        for key in sorted((a.keys() | b.keys()) - SUPPORTED - ANNOTATIONS):
            if not key.startswith("x-"):
                self.add(operation, pointer(where, key), "review", "UNSUPPORTED_SCHEMA", f"{key} is outside the structural rule set.")

        def types(value: dict) -> set:
            raw = value.get("type", list(TYPES))
            values = [raw] if isinstance(raw, str) else array(raw, where + "/type")
            if not values or any(not isinstance(t, str) or t not in TYPES for t in values):
                raise InputError(f"{where}/type: invalid schema type")
            result = set(values)
            if "number" in result:
                result.add("integer")
            return result

        old_types, new_types = types(a), types(b)
        incompatible = old_types - new_types if direction == "request" else new_types - old_types
        if incompatible:
            self.add(operation, where + "/type", "breaking", "TYPE_CHANGED", f"{direction.capitalize()} type set changed incompatibly.")

        def choices(value: dict) -> set | None:
            if "const" in value:
                return {enum_key(value["const"])}
            if "enum" in value:
                values = array(value["enum"], where + "/enum")
                if not values:
                    raise InputError(f"{where}/enum: enum must not be empty")
                return {enum_key(v) for v in values}
            return None

        old_enum, new_enum = choices(a), choices(b)
        if "const" in a and "enum" in a or "const" in b and "enum" in b:
            self.add(operation, where, "review", "ENUM_CONST_COMBINATION", "Combined enum and const need manual review.")
        if direction == "request":
            bad_enum = new_enum is not None and (old_enum is None or not old_enum <= new_enum)
        else:
            bad_enum = old_enum is not None and (new_enum is None or not new_enum <= old_enum)
        if bad_enum:
            self.add(operation, where + "/enum", "breaking", "ENUM_CHANGED", f"{direction.capitalize()} enum changed incompatibly.")

        for lower, upper in (("minimum", "maximum"), ("minLength", "maxLength"), ("minItems", "maxItems"), ("minProperties", "maxProperties"), ("exclusiveMinimum", "exclusiveMaximum")):
            for key, is_lower in ((lower, True), (upper, False)):
                for value in (a, b):
                    if key in value and (isinstance(value[key], bool) or not isinstance(value[key], (int, float))):
                        raise InputError(f"{where}/{key}: expected a number")
                old_bound = a.get(key, float("-inf") if is_lower else float("inf"))
                new_bound = b.get(key, float("-inf") if is_lower else float("inf"))
                tightened = new_bound > old_bound if is_lower else new_bound < old_bound
                relaxed = new_bound < old_bound if is_lower else new_bound > old_bound
                incompatible_bound = tightened if direction == "request" else relaxed
                if incompatible_bound:
                    self.add(operation, pointer(where, key), "breaking", "BOUND_CHANGED", f"{direction.capitalize()} bound changed incompatibly.")

        props_a = obj(a.get("properties", {}), "old" + where + "/properties")
        props_b = obj(b.get("properties", {}), "new" + where + "/properties")

        def required(value: dict) -> set:
            values = array(value.get("required", []), where + "/required")
            if any(not isinstance(v, str) for v in values):
                raise InputError(f"{where}/required: expected property names")
            return set(values)

        req_a, req_b = required(a), required(b)
        changed = req_b - req_a if direction == "request" else req_a - req_b
        for name in sorted(changed):
            self.add(operation, pointer(where + "/required", name), "breaking", "REQUIRED_CHANGED", f"Required {direction} property guarantee changed: {name}.")
        for name in sorted(props_a.keys() - props_b.keys()):
            location = pointer(where + "/properties", name)
            if direction == "response":
                severity = "breaking" if name in req_a else "review"
                self.add(operation, location, severity, "PROPERTY_REMOVED", f"Documented response property was removed: {name}.")
            elif b.get("additionalProperties", True) is False:
                self.add(operation, location, "breaking", "PROPERTY_REMOVED", f"Previously accepted request property is now forbidden: {name}.")
            elif isinstance(b.get("additionalProperties"), dict):
                self.schema(props_a[name], b["additionalProperties"], location, operation, direction, active)
        for name in sorted(props_a.keys() & props_b.keys()):
            self.schema(props_a[name], props_b[name], pointer(where + "/properties", name), operation, direction, active)
        for name in sorted(props_b.keys() - props_a.keys()):
            location = pointer(where + "/properties", name)
            if direction == "response" and a.get("additionalProperties", True) is False:
                self.add(operation, location, "breaking", "CLOSED_RESPONSE_EXPANDED", f"Closed response object now declares an additional property: {name}.")
            elif direction == "response" and isinstance(a.get("additionalProperties"), dict):
                self.schema(a["additionalProperties"], props_b[name], location, operation, direction, active)

        if "additionalProperties" in a or "additionalProperties" in b:
            self.schema(a.get("additionalProperties", True), b.get("additionalProperties", True), where + "/additionalProperties", operation, direction, active)
        if "items" in a or "items" in b:
            self.schema(a.get("items", True), b.get("items", True), where + "/items", operation, direction, active)

    def run(self) -> list[Finding]:
        for key in ("servers", "security"):
            if self.old.value.get(key) != self.new.value.get(key):
                self.add("API", pointer("", key), "review", "API_POLICY_CHANGED", f"{key} changed; review routing or authentication separately.")
        for document in (self.old, self.new):
            if document.value.get("webhooks"):
                self.add("API", "/webhooks", "review", "UNSUPPORTED_WEBHOOKS", "Top-level webhooks are outside the comparison scope.")
            if document.value.get("jsonSchemaDialect", "https://spec.openapis.org/oas/3.1/dialect/base") != "https://spec.openapis.org/oas/3.1/dialect/base":
                self.add("API", "/jsonSchemaDialect", "review", "SCHEMA_DIALECT", "Custom schema dialect needs manual review.")
        a, b = self.operations(self.old), self.operations(self.new)
        for path, method in sorted(a.keys() - b.keys()):
            self.add(f"{method.upper()} {path}", pointer(pointer("/paths", path), method), "breaking", "OPERATION_REMOVED", "Documented operation was removed.")
        for path, method in sorted(a.keys() & b.keys()):
            operation = f"{method.upper()} {path}"
            where = pointer(pointer("/paths", path), method)
            item_a, op_a = a[(path, method)]
            item_b, op_b = b[(path, method)]
            for key in ("security", "servers"):
                before = op_a.get(key, item_a.get(key, self.old.value.get(key)))
                after = op_b.get(key, item_b.get(key, self.new.value.get(key)))
                if before != after:
                    self.add(operation, pointer(where, key), "review", "OPERATION_POLICY_CHANGED", f"{key} changed; manual review required.")
            params_a = self.parameters(self.old, item_a, op_a, where, operation)
            params_b = self.parameters(self.new, item_b, op_b, where, operation)
            for identity in sorted(params_a.keys() - params_b.keys()):
                self.add(operation, where + "/parameters", "breaking", "PARAMETER_REMOVED", f"Documented {identity[0]} parameter was removed: {identity[1]}.")
            for identity, after in sorted(params_b.items()):
                before = params_a.get(identity)
                location = pointer(where + "/parameters", ":".join(identity))
                if flag(after, "required", "new" + location) and (before is None or not flag(before, "required", "old" + location)):
                    self.add(operation, location + "/required", "breaking", "PARAMETER_REQUIRED", "Request parameter became required.")
                if before is not None:
                    default_style = "form" if identity[0] in {"query", "cookie"} else "simple"
                    for key, default in (("style", default_style), ("allowReserved", False), ("allowEmptyValue", False)):
                        if before.get(key, default) != after.get(key, default):
                            self.add(operation, pointer(location, key), "breaking", "PARAMETER_ENCODING_CHANGED", f"Parameter {key} changed.")
                    if before.get("explode", before.get("style", default_style) == "form") != after.get("explode", after.get("style", default_style) == "form"):
                        self.add(operation, location + "/explode", "breaking", "PARAMETER_ENCODING_CHANGED", "Parameter explode changed.")
                    if "content" in before or "content" in after:
                        if ("content" in before) != ("content" in after):
                            self.add(operation, location, "review", "PARAMETER_REPRESENTATION", "Parameter switched between schema and content.")
                        else:
                            self.media(before, after, location, operation, "request")
                    else:
                        self.schema(before.get("schema", {}), after.get("schema", {}), location + "/schema", operation, "request", set())
            body_a = self.object_ref(self.old, op_a.get("requestBody", {}), where + "/requestBody", operation)
            body_b = self.object_ref(self.new, op_b.get("requestBody", {}), where + "/requestBody", operation)
            if body_a is not None and body_b is not None:
                if flag(body_b, "required", "new" + where) and not flag(body_a, "required", "old" + where):
                    self.add(operation, where + "/requestBody/required", "breaking", "BODY_REQUIRED", "Request body became required.")
                self.media(body_a, body_b, where + "/requestBody", operation, "request")
            responses_a = obj(op_a.get("responses"), "old" + where + "/responses")
            responses_b = obj(op_b.get("responses"), "new" + where + "/responses")
            codes_a = {key for key in responses_a if not key.startswith("x-")}
            codes_b = {key for key in responses_b if not key.startswith("x-")}
            for code in sorted(codes_a - codes_b):
                self.add(operation, pointer(where + "/responses", code), "breaking", "RESPONSE_REMOVED", "Documented response status was removed.")
            for code in sorted(codes_b - codes_a):
                self.add(operation, pointer(where + "/responses", code), "review", "RESPONSE_ADDED", "A new response status may require client handling.")
            for code in sorted(codes_a & codes_b):
                location = pointer(where + "/responses", code)
                before = self.object_ref(self.old, responses_a[code], location, operation)
                after = self.object_ref(self.new, responses_b[code], location, operation)
                if before is not None and after is not None:
                    if before.get("headers") or after.get("headers"):
                        self.add(operation, location + "/headers", "review", "RESPONSE_HEADERS", "Response headers are outside the comparison scope.")
                    self.media(before, after, location, operation, "response")
        return sorted(self.findings)


def compare(old: Any, new: Any) -> list[Finding]:
    """Return deterministic breaking/review findings for old-client compatibility."""
    return Engine(old, new).run()
