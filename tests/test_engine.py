from copy import deepcopy
import unittest

from contract_diff import InputError, compare


def contract(schema=None, direction="request"):
    operation = {"responses": {"200": {"description": "OK"}}}
    if schema is not None:
        media = {"content": {"application/json": {"schema": schema}}}
        if direction == "request":
            operation["requestBody"] = media
        else:
            operation["responses"]["200"].update(media)
    return {"openapi": "3.1.1", "info": {"title": "Example", "version": "1"}, "paths": {"/items": {"post": operation}}}


def operation(document):
    return document["paths"]["/items"]["post"]


class CompatibilityTests(unittest.TestCase):
    def codes(self, old, new, severity=None):
        return {f.code for f in compare(old, new) if severity is None or f.severity == severity}

    def test_identical_contract(self):
        document = contract({"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]})
        self.assertEqual(compare(document, deepcopy(document)), [])

    def test_operation_removed_and_path_pointer_escaped(self):
        old = contract()
        new = deepcopy(old)
        new["paths"] = {}
        finding, = compare(old, new)
        self.assertEqual((finding.code, finding.pointer), ("OPERATION_REMOVED", "/paths/~1items/post"))

    def test_new_operation_does_not_break_old_clients(self):
        old = contract()
        new = deepcopy(old)
        new["paths"]["/other"] = {"get": {"responses": {"200": {"description": "OK"}}}}
        self.assertEqual(compare(old, new), [])

    def test_request_type_narrowing_and_widening(self):
        wide = contract({"type": ["string", "null"]})
        narrow = contract({"type": "string"})
        self.assertIn("TYPE_CHANGED", self.codes(wide, narrow))
        self.assertEqual(compare(narrow, wide), [])

    def test_response_type_direction_is_reversed(self):
        wide = contract({"type": ["string", "null"]}, "response")
        narrow = contract({"type": "string"}, "response")
        self.assertIn("TYPE_CHANGED", self.codes(narrow, wide))
        self.assertEqual(compare(wide, narrow), [])

    def test_integer_is_subset_of_number(self):
        integer = contract({"type": "integer"})
        number = contract({"type": "number"})
        self.assertEqual(compare(integer, number), [])
        self.assertIn("TYPE_CHANGED", self.codes(number, integer))

    def test_request_enum_narrowing(self):
        wide = contract({"type": "string", "enum": ["a", "b"]})
        narrow = contract({"type": "string", "enum": ["a"]})
        self.assertIn("ENUM_CHANGED", self.codes(wide, narrow))
        self.assertEqual(compare(narrow, wide), [])

    def test_response_enum_widening_and_removal(self):
        narrow = contract({"type": "string", "enum": ["a"]}, "response")
        wide = contract({"type": "string", "enum": ["a", "b"]}, "response")
        unrestricted = contract({"type": "string"}, "response")
        self.assertIn("ENUM_CHANGED", self.codes(narrow, wide))
        self.assertIn("ENUM_CHANGED", self.codes(narrow, unrestricted))
        self.assertEqual(compare(wide, narrow), [])

    def test_boolean_and_numeric_enum_values_are_distinct(self):
        old = contract({"enum": [True]})
        new = contract({"enum": [1]})
        self.assertIn("ENUM_CHANGED", self.codes(old, new))

    def test_numeric_enum_equivalence(self):
        self.assertEqual(compare(contract({"enum": [1]}), contract({"enum": [1.0]})), [])

    def test_new_required_property(self):
        old = contract({"type": "object", "properties": {"email": {"type": "string"}}})
        new = deepcopy(old)
        operation(new)["requestBody"]["content"]["application/json"]["schema"]["required"] = ["email"]
        self.assertIn("REQUIRED_CHANGED", self.codes(old, new))

    def test_response_required_guarantee_removed(self):
        old = contract({"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}, "response")
        new = contract({"type": "object", "properties": {"id": {"type": "string"}}}, "response")
        self.assertIn("REQUIRED_CHANGED", self.codes(old, new))
        self.assertEqual(compare(new, old), [])

    def test_removed_response_properties_are_classified_by_guarantee(self):
        old = contract({"type": "object", "properties": {"id": {"type": "string"}, "note": {"type": "string"}}, "required": ["id"]}, "response")
        new = contract({"type": "object"}, "response")
        findings = [f for f in compare(old, new) if f.code == "PROPERTY_REMOVED"]
        self.assertEqual({f.pointer.rsplit("/", 1)[-1]: f.severity for f in findings}, {"id": "breaking", "note": "review"})

    def test_closed_request_property_removal(self):
        old = contract({"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": False})
        new = contract({"type": "object", "additionalProperties": False})
        self.assertIn("PROPERTY_REMOVED", self.codes(old, new))

    def test_open_request_property_removal_is_allowed(self):
        old = contract({"type": "object", "properties": {"name": {"type": "string"}}})
        self.assertEqual(compare(old, contract({"type": "object"})), [])

    def test_closing_request_object_is_breaking(self):
        old = contract({"type": "object"})
        new = contract({"type": "object", "additionalProperties": False})
        self.assertIn("BOOLEAN_SCHEMA_CHANGED", self.codes(old, new))
        self.assertEqual(compare(new, old), [])

    def test_closed_response_expansion(self):
        old = contract({"type": "object", "additionalProperties": False}, "response")
        new = contract({"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": False}, "response")
        self.assertIn("CLOSED_RESPONSE_EXPANDED", self.codes(old, new))

    def test_request_bounds(self):
        old = contract({"type": "string", "minLength": 1, "maxLength": 100})
        narrow = contract({"type": "string", "minLength": 2, "maxLength": 80})
        self.assertEqual(len(compare(old, narrow)), 2)
        self.assertEqual(compare(narrow, old), [])

    def test_response_bounds(self):
        old = contract({"type": "integer", "minimum": 0, "maximum": 10}, "response")
        wide = contract({"type": "integer", "minimum": -1, "maximum": 20}, "response")
        self.assertEqual(len(compare(old, wide)), 2)
        self.assertEqual(compare(wide, old), [])

    def test_array_items(self):
        old = contract({"type": "array", "items": {"type": ["string", "null"]}})
        new = contract({"type": "array", "items": {"type": "string"}})
        self.assertTrue(any(f.pointer.endswith("/items/type") for f in compare(old, new)))

    def test_local_ref_can_use_escaped_property_name(self):
        old = contract({"$ref": "#/components/schemas/a~1b~0c"})
        old["components"] = {"schemas": {"a/b~c": {"type": ["string", "null"]}}}
        new = deepcopy(old)
        new["components"]["schemas"]["a/b~c"]["type"] = "string"
        self.assertIn("TYPE_CHANGED", self.codes(old, new))

    def test_recursive_schema_terminates_and_checks_leaf(self):
        old = contract({"$ref": "#/components/schemas/Node"})
        old["components"] = {"schemas": {"Node": {"type": "object", "properties": {"next": {"$ref": "#/components/schemas/Node"}, "name": {"type": ["string", "null"]}}}}}
        new = deepcopy(old)
        new["components"]["schemas"]["Node"]["properties"]["name"]["type"] = "string"
        findings = compare(old, new)
        self.assertEqual([f.code for f in findings], ["TYPE_CHANGED"])

    def test_remote_ref_never_fetches_network(self):
        old = contract({"$ref": "https://example.invalid/schema.json"})
        self.assertEqual(self.codes(old, old), {"UNSUPPORTED_REF"})

    def test_pure_reference_cycle_needs_review(self):
        document = contract({"$ref": "#/components/schemas/Loop"})
        document["components"] = {"schemas": {"Loop": {"$ref": "#/components/schemas/Loop"}}}
        self.assertEqual(self.codes(document, document), {"REF_CYCLE"})

    def test_ref_siblings_need_review(self):
        document = contract({"$ref": "#/components/schemas/Id", "maxLength": 8})
        document["components"] = {"schemas": {"Id": {"type": "string"}}}
        self.assertIn("REF_SIBLINGS", self.codes(document, document))

    def test_unchanged_unsupported_combinator_is_reported(self):
        document = contract({"oneOf": [{"type": "string"}, {"type": "integer"}]})
        self.assertEqual(self.codes(document, document), {"UNSUPPORTED_SCHEMA"})

    def test_path_parameter_is_overridden_at_operation_level(self):
        old = contract()
        old["paths"]["/items"]["parameters"] = [{"name": "limit", "in": "query", "required": True, "schema": {"type": "integer"}}]
        operation(old)["parameters"] = [{"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}}]
        new = deepcopy(old)
        del operation(new)["parameters"]
        self.assertIn("PARAMETER_REQUIRED", self.codes(old, new))

    def test_new_optional_parameter_is_compatible(self):
        old = contract()
        new = deepcopy(old)
        operation(new)["parameters"] = [{"name": "limit", "in": "query", "schema": {"type": "integer"}}]
        self.assertEqual(compare(old, new), [])

    def test_parameter_serialization_defaults_are_normalized(self):
        old = contract()
        operation(old)["parameters"] = [{"name": "ids", "in": "query", "schema": {"type": "array", "items": {"type": "string"}}}]
        new = deepcopy(old)
        operation(new)["parameters"][0].update(style="form", explode=True)
        self.assertEqual(compare(old, new), [])
        operation(new)["parameters"][0]["explode"] = False
        self.assertIn("PARAMETER_ENCODING_CHANGED", self.codes(old, new))

    def test_body_becomes_required(self):
        old = contract({"type": "string"})
        new = deepcopy(old)
        operation(new)["requestBody"]["required"] = True
        self.assertIn("BODY_REQUIRED", self.codes(old, new))

    def test_response_removed_and_added(self):
        old = contract()
        new = deepcopy(old)
        operation(new)["responses"] = {"201": {"description": "Created"}}
        self.assertEqual(self.codes(old, new), {"RESPONSE_REMOVED", "RESPONSE_ADDED"})

    def test_media_type_removed(self):
        old = contract({"type": "string"})
        new = deepcopy(old)
        operation(new)["requestBody"]["content"] = {}
        self.assertIn("MEDIA_TYPE_REMOVED", self.codes(old, new))

    def test_new_response_media_type_needs_review(self):
        old = contract({"type": "string"}, "response")
        new = deepcopy(old)
        operation(new)["responses"]["200"]["content"]["text/plain"] = {"schema": {"type": "string"}}
        self.assertEqual(self.codes(old, new), {"RESPONSE_MEDIA_ADDED"})

    def test_security_policy_change_needs_review(self):
        old = contract()
        new = deepcopy(old)
        operation(new)["security"] = [{"bearer": []}]
        self.assertIn("OPERATION_POLICY_CHANGED", self.codes(old, new))

    def test_findings_are_deterministic_and_inputs_are_not_mutated(self):
        old = contract({"type": ["string", "null"], "enum": [None, "a", "b"]})
        new = contract({"type": "string", "enum": ["a"]})
        originals = deepcopy((old, new))
        findings = compare(old, new)
        self.assertEqual(findings, sorted(findings))
        self.assertEqual(findings, compare(old, new))
        self.assertEqual((old, new), originals)

    def test_rejects_malformed_used_structures(self):
        invalid_schemas = [{"type": 42}, {"type": "banana"}, {"enum": []}, {"required": "name"}, {"properties": []}, {"minimum": True}, {"$ref": "#/missing"}]
        for schema in invalid_schemas:
            with self.subTest(schema=schema), self.assertRaises(InputError):
                compare(contract(schema), contract(schema))

    def test_rejects_openapi_30(self):
        old = contract()
        old["openapi"] = "3.0.3"
        with self.assertRaises(InputError):
            compare(old, contract())

    def test_rejects_duplicate_parameters(self):
        old = contract()
        param = {"name": "q", "in": "query", "schema": {"type": "string"}}
        operation(old)["parameters"] = [param, param]
        with self.assertRaises(InputError):
            compare(old, contract())

    def test_rejects_malformed_parameter_location(self):
        old = contract()
        operation(old)["parameters"] = [{"name": "q", "in": {"query": True}}]
        with self.assertRaises(InputError):
            compare(old, contract())


if __name__ == "__main__":
    unittest.main()
