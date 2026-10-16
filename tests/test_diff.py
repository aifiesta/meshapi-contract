from __future__ import annotations

from meshapi_contract import classify_changes


def spec(paths=None, schemas=None, versions=("2026-08",)) -> dict:
    return {
        "openapi": "3.1.0",
        "x-mesh-api-versions": [{"label": v} for v in versions],
        "paths": paths if paths is not None else {},
        "components": {"schemas": schemas if schemas is not None else {}},
    }


def op(response_ref="Model", parameters=None, request_ref=None) -> dict:
    body = {
        "responses": {
            "200": {
                "content": {
                    "application/json": {"schema": {"$ref": f"#/components/schemas/{response_ref}"}}
                }
            }
        }
    }
    if parameters is not None:
        body["parameters"] = parameters
    if request_ref is not None:
        body["requestBody"] = {
            "content": {
                "application/json": {"schema": {"$ref": f"#/components/schemas/{request_ref}"}}
            }
        }
    return body


def obj(properties: dict, required=()) -> dict:
    return {
        "type": "object",
        "properties": properties,
        **({"required": list(required)} if required else {}),
    }


def ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def kinds(changes) -> set[str]:
    return {c.kind for c in changes}


def breaking(changes) -> list:
    return [c for c in changes if c.breaking]


class TestNoChange:
    def test_an_identical_spec_yields_nothing(self):
        one = spec({"/v1/models": {"get": op()}}, {"Model": obj({"id": {"type": "string"}})})

        assert classify_changes(one, one) == []

    def test_key_order_is_not_a_change(self):
        before = spec(
            {"/v1/models": {"get": op()}, "/v1/keys": {"get": op()}},
            {"Model": obj({"id": {"type": "string"}, "name": {"type": "string"}})},
        )
        after = spec(
            {"/v1/keys": {"get": op()}, "/v1/models": {"get": op()}},
            {"Model": obj({"name": {"type": "string"}, "id": {"type": "string"}})},
        )

        assert classify_changes(before, after) == []


class TestRemovedOperation:
    def test_a_removed_operation_is_breaking(self):
        before = spec({"/v1/models": {"get": op()}, "/v1/models/free": {"get": op()}})
        after = spec({"/v1/models": {"get": op()}})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"operation_removed"}
        assert breaking(changes)
        assert "GET /v1/models/free" in changes[0].detail

    def test_a_removed_method_on_a_kept_path_is_breaking(self):
        before = spec({"/v1/keys/{key_id}": {"get": op(), "delete": op()}})
        after = spec({"/v1/keys/{key_id}": {"get": op()}})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"operation_removed"}
        assert "DELETE /v1/keys/{key_id}" in changes[0].detail

    def test_a_new_operation_is_additive(self):
        before = spec({"/v1/models": {"get": op()}})
        after = spec({"/v1/models": {"get": op()}, "/v1/api-versions": {"get": op()}})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"operation_added"}
        assert not breaking(changes)


class TestRemovedResponseField:
    def test_a_removed_property_is_breaking(self):
        before = spec(
            {"/v1/models": {"get": op()}},
            {"Model": obj({"id": {"type": "string"}, "prompt_usd_per_1k": {"type": "string"}})},
        )
        after = spec({"/v1/models": {"get": op()}}, {"Model": obj({"id": {"type": "string"}})})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"field_removed"}
        assert breaking(changes)
        assert "Model.prompt_usd_per_1k" in changes[0].detail

    def test_a_new_optional_property_is_additive(self):
        before = spec({"/v1/models": {"get": op()}}, {"Model": obj({"id": {"type": "string"}})})
        after = spec(
            {"/v1/models": {"get": op()}},
            {"Model": obj({"id": {"type": "string"}, "input_usd_per_unit": {"type": "string"}})},
        )

        changes = classify_changes(before, after)

        assert kinds(changes) == {"field_added"}
        assert not breaking(changes)

    def test_a_removed_schema_is_breaking(self):
        before = spec({"/v1/models": {"get": op()}}, {"Model": obj({"id": {"type": "string"}})})
        after = spec({"/v1/models": {"get": op()}}, {})

        changes = classify_changes(before, after)

        assert "schema_removed" in kinds(changes)
        assert breaking(changes)


class TestTypeChange:
    def test_a_changed_property_type_is_breaking(self):
        before = spec(schemas={"Model": obj({"context_length": {"type": "string"}})})
        after = spec(schemas={"Model": obj({"context_length": {"type": "integer"}})})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"type_changed"}
        assert breaking(changes)
        assert "string" in changes[0].detail and "integer" in changes[0].detail

    def test_widening_a_type_to_include_null_is_still_reported(self):
        before = spec(schemas={"Model": obj({"name": {"type": "string"}})})
        after = spec(
            schemas={"Model": obj({"name": {"anyOf": [{"type": "string"}, {"type": "null"}]}})}
        )

        assert breaking(classify_changes(before, after))


class TestUnionMembers:
    def test_a_union_that_gained_a_member_is_additive(self):
        before = spec(schemas={"Msg": obj({"content": {"anyOf": [ref("Text"), ref("Image")]}})})
        after = spec(
            schemas={"Msg": obj({"content": {"anyOf": [ref("Text"), ref("Image"), ref("Think")]}})}
        )

        changes = classify_changes(before, after)

        assert kinds(changes) == {"union_member_added"}
        assert not breaking(changes)

    def test_a_union_that_lost_a_member_is_breaking(self):
        before = spec(
            schemas={"Msg": obj({"content": {"anyOf": [ref("Text"), ref("Image"), ref("Think")]}})}
        )
        after = spec(schemas={"Msg": obj({"content": {"anyOf": [ref("Text"), ref("Image")]}})})

        assert breaking(classify_changes(before, after))
        assert kinds(classify_changes(before, after)) == {"type_changed"}

    def test_a_swapped_member_is_breaking_not_widening(self):
        before = spec(schemas={"Msg": obj({"content": {"anyOf": [ref("Text"), ref("Image")]}})})
        after = spec(schemas={"Msg": obj({"content": {"anyOf": [ref("Text"), ref("Video")]}})})

        assert breaking(classify_changes(before, after))

    def test_a_union_nested_in_an_array_still_counts_as_widening(self):
        before = spec(
            schemas={
                "Msg": obj(
                    {
                        "content": {
                            "anyOf": [
                                {"type": "array", "items": {"anyOf": [ref("Text"), ref("Tool")]}},
                                {"type": "string"},
                            ]
                        }
                    }
                )
            }
        )
        after = spec(
            schemas={
                "Msg": obj(
                    {
                        "content": {
                            "anyOf": [
                                {
                                    "type": "array",
                                    "items": {"anyOf": [ref("Text"), ref("Think"), ref("Tool")]},
                                },
                                {"type": "string"},
                            ]
                        }
                    }
                )
            }
        )

        assert not breaking(classify_changes(before, after))

    def test_a_member_narrowed_alongside_an_addition_is_still_breaking(self):
        before = spec(
            schemas={
                "Msg": obj(
                    {"v": {"anyOf": [{"type": "string", "maxLength": 512}, {"type": "null"}]}}
                )
            }
        )
        after = spec(
            schemas={
                "Msg": obj(
                    {
                        "v": {
                            "anyOf": [
                                {"type": "string", "maxLength": 8},
                                {"type": "null"},
                                {"type": "integer"},
                            ]
                        }
                    }
                )
            }
        )

        assert breaking(classify_changes(before, after))

    def test_a_oneOf_that_gained_a_member_is_still_breaking(self):
        before = spec(schemas={"Msg": obj({"v": {"oneOf": [{"type": "string"}]}})})
        after = spec(
            schemas={
                "Msg": obj(
                    {"v": {"oneOf": [{"type": "string"}, {"type": "string", "maxLength": 3}]}}
                )
            }
        )

        assert breaking(classify_changes(before, after))

    def test_a_tightened_sibling_of_a_widened_array_is_still_breaking(self):
        before = spec(
            schemas={
                "Msg": obj(
                    {
                        "v": {
                            "type": "array",
                            "items": {"anyOf": [ref("Text")]},
                            "maxItems": 10,
                        }
                    }
                )
            }
        )
        after = spec(
            schemas={
                "Msg": obj(
                    {
                        "v": {
                            "type": "array",
                            "items": {"anyOf": [ref("Text"), ref("Think")]},
                            "maxItems": 2,
                        }
                    }
                )
            }
        )

        assert breaking(classify_changes(before, after))

    def test_a_tightened_sibling_of_a_widened_union_is_still_breaking(self):
        before = spec(schemas={"Msg": obj({"v": {"anyOf": [ref("Text")], "maxLength": 100}})})
        after = spec(
            schemas={"Msg": obj({"v": {"anyOf": [ref("Text"), ref("Think")], "maxLength": 4}})}
        )

        assert breaking(classify_changes(before, after))

    def test_a_non_dict_schema_node_is_never_called_widening(self):
        from meshapi_contract.diff import _only_widens

        assert _only_widens(True, {"anyOf": [{"type": "string"}]}) is False
        assert _only_widens({"anyOf": [{"type": "string"}]}, True) is False
        assert _only_widens(True, True) is True

    def test_a_scalar_becoming_a_union_is_still_breaking(self):
        before = spec(schemas={"Model": obj({"name": {"type": "string"}})})
        after = spec(
            schemas={"Model": obj({"name": {"anyOf": [{"type": "string"}, {"type": "null"}]}})}
        )

        assert breaking(classify_changes(before, after))

    def test_a_widened_array_item_type_that_is_not_a_union_is_breaking(self):
        before = spec(schemas={"Msg": obj({"ids": {"type": "array", "items": {"type": "string"}}})})
        after = spec(schemas={"Msg": obj({"ids": {"type": "array", "items": {"type": "integer"}}})})

        assert breaking(classify_changes(before, after))


class TestEnumValues:
    def test_a_removed_enum_value_is_breaking(self):
        before = spec(schemas={"Status": {"enum": ["active", "suspended", "pending"]}})
        after = spec(schemas={"Status": {"enum": ["active", "suspended"]}})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"enum_value_removed"}
        assert breaking(changes)
        assert "pending" in changes[0].detail

    def test_a_new_enum_value_is_additive_on_a_response(self):
        before = spec(schemas={"Status": {"enum": ["active"]}})
        after = spec(schemas={"Status": {"enum": ["active", "suspended"]}})

        assert not breaking(classify_changes(before, after))


class TestRequestRequirements:
    def test_a_newly_required_field_is_breaking(self):
        before = spec(schemas={"CreateKey": obj({"label": {"type": "string"}})})
        after = spec(schemas={"CreateKey": obj({"label": {"type": "string"}}, required=["label"])})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"field_now_required"}
        assert breaking(changes)
        assert "CreateKey.label" in changes[0].detail

    def test_relaxing_a_requirement_is_additive(self):
        before = spec(schemas={"CreateKey": obj({"label": {"type": "string"}}, required=["label"])})
        after = spec(schemas={"CreateKey": obj({"label": {"type": "string"}})})

        assert not breaking(classify_changes(before, after))

    def test_a_newly_required_query_parameter_is_breaking(self):
        before = spec(
            {
                "/v1/models": {
                    "get": op(parameters=[{"name": "free", "in": "query", "required": False}])
                }
            }
        )
        after = spec(
            {
                "/v1/models": {
                    "get": op(parameters=[{"name": "free", "in": "query", "required": True}])
                }
            }
        )

        changes = classify_changes(before, after)

        assert kinds(changes) == {"parameter_now_required"}
        assert breaking(changes)

    def test_a_removed_parameter_is_breaking(self):
        before = spec(
            {
                "/v1/models": {
                    "get": op(parameters=[{"name": "free", "in": "query", "required": False}])
                }
            }
        )
        after = spec({"/v1/models": {"get": op(parameters=[])}})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"parameter_removed"}
        assert breaking(changes)

    def test_a_new_optional_parameter_is_additive(self):
        before = spec({"/v1/models": {"get": op(parameters=[])}})
        after = spec(
            {
                "/v1/models": {
                    "get": op(
                        parameters=[{"name": "X-Mesh-Version", "in": "header", "required": False}]
                    )
                }
            }
        )

        assert not breaking(classify_changes(before, after))


class TestSeveralAtOnce:
    def test_every_change_is_reported_not_just_the_first(self):
        before = spec(
            {"/v1/models": {"get": op()}, "/v1/models/free": {"get": op()}},
            {"Model": obj({"id": {"type": "string"}, "prompt_usd_per_1k": {"type": "string"}})},
        )
        after = spec(
            {"/v1/models": {"get": op()}},
            {"Model": obj({"id": {"type": "integer"}})},
        )

        changes = classify_changes(before, after)

        assert kinds(changes) == {"operation_removed", "field_removed", "type_changed"}
        assert len(breaking(changes)) == 3


class TestDimensionsTheFirstVersionMissed:
    def test_a_removed_response_status_is_breaking(self):
        before = spec({"/v1/models": {"get": {"responses": {"200": {}, "404": {}}}}})
        after = spec({"/v1/models": {"get": {"responses": {"200": {}}}}})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"response_status_removed"}
        assert breaking(changes)
        assert "404" in changes[0].detail

    def test_a_new_response_status_is_additive(self):
        before = spec({"/v1/models": {"get": {"responses": {"200": {}}}}})
        after = spec({"/v1/models": {"get": {"responses": {"200": {}, "429": {}}}}})

        assert not breaking(classify_changes(before, after))

    def test_a_changed_response_content_type_is_breaking(self):
        before = spec(
            {"/v1/models": {"get": {"responses": {"200": {"content": {"application/json": {}}}}}}}
        )
        after = spec({"/v1/models": {"get": {"responses": {"200": {"content": {"text/csv": {}}}}}}})

        changes = classify_changes(before, after)

        assert "response_content_type_removed" in kinds(changes)
        assert breaking(changes)

    def test_a_request_body_becoming_required_is_breaking(self):
        before = spec({"/v1/keys": {"post": {"requestBody": {"required": False}, "responses": {}}}})
        after = spec({"/v1/keys": {"post": {"requestBody": {"required": True}, "responses": {}}}})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"request_body_now_required"}
        assert breaking(changes)

    def test_a_changed_parameter_type_is_breaking(self):
        before = spec(
            {
                "/v1/models": {
                    "get": op(
                        parameters=[{"name": "free", "in": "query", "schema": {"type": "string"}}]
                    )
                }
            }
        )
        after = spec(
            {
                "/v1/models": {
                    "get": op(
                        parameters=[{"name": "free", "in": "query", "schema": {"type": "boolean"}}]
                    )
                }
            }
        )

        changes = classify_changes(before, after)

        assert kinds(changes) == {"parameter_type_changed"}
        assert breaking(changes)

    def test_a_parameter_moving_between_query_and_header_is_breaking(self):
        before = spec({"/v1/models": {"get": op(parameters=[{"name": "v", "in": "query"}])}})
        after = spec({"/v1/models": {"get": op(parameters=[{"name": "v", "in": "header"}])}})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"parameter_location_changed"}
        assert breaking(changes)

    def test_a_changed_default_is_breaking(self):
        before = spec(schemas={"Q": obj({"limit": {"type": "integer", "default": 20}})})
        after = spec(schemas={"Q": obj({"limit": {"type": "integer", "default": 50}})})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"default_changed"}
        assert breaking(changes)
        assert "20" in changes[0].detail and "50" in changes[0].detail

    def test_a_changed_parameter_default_is_breaking(self):
        before = spec(
            {
                "/v1/models": {
                    "get": op(
                        parameters=[{"name": "limit", "in": "query", "schema": {"default": 20}}]
                    )
                }
            }
        )
        after = spec(
            {
                "/v1/models": {
                    "get": op(
                        parameters=[{"name": "limit", "in": "query", "schema": {"default": 50}}]
                    )
                }
            }
        )

        assert breaking(classify_changes(before, after))

    def test_a_tightened_constraint_is_breaking(self):
        before = spec(schemas={"Q": obj({"name": {"type": "string", "maxLength": 100}})})
        after = spec(schemas={"Q": obj({"name": {"type": "string", "maxLength": 50}})})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"constraint_changed"}
        assert breaking(changes)

    def test_a_newly_added_constraint_is_breaking(self):
        before = spec(schemas={"Q": obj({"name": {"type": "string"}})})
        after = spec(schemas={"Q": obj({"name": {"type": "string", "pattern": "^[a-z]+$"}})})

        assert breaking(classify_changes(before, after))

    def test_a_relaxed_constraint_is_reported_but_not_breaking(self):
        before = spec(schemas={"Q": obj({"name": {"type": "string", "maxLength": 50}})})
        after = spec(schemas={"Q": obj({"name": {"type": "string", "maxLength": 100}})})

        changes = classify_changes(before, after)

        assert changes and not breaking(changes)


class TestRequestBodyAndBounds:
    def test_adding_a_required_request_body_is_breaking(self):
        before = spec({"/v1/keys": {"post": {"responses": {}}}})
        after = spec({"/v1/keys": {"post": {"requestBody": {"required": True}, "responses": {}}}})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"request_body_added"}
        assert breaking(changes)

    def test_adding_an_optional_request_body_is_additive(self):
        before = spec({"/v1/keys": {"post": {"responses": {}}}})
        after = spec({"/v1/keys": {"post": {"requestBody": {"required": False}, "responses": {}}}})

        assert not breaking(classify_changes(before, after))

    def test_removing_the_request_body_is_breaking(self):
        before = spec({"/v1/keys": {"post": {"requestBody": {"required": True}, "responses": {}}}})
        after = spec({"/v1/keys": {"post": {"responses": {}}}})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"request_body_removed"}
        assert breaking(changes)

    def test_dropping_an_accepted_request_content_type_is_breaking(self):
        before = spec(
            {
                "/v1/files": {
                    "post": {
                        "requestBody": {
                            "content": {"multipart/form-data": {}, "application/json": {}}
                        },
                        "responses": {},
                    }
                }
            }
        )
        after = spec(
            {
                "/v1/files": {
                    "post": {
                        "requestBody": {"content": {"application/json": {}}},
                        "responses": {},
                    }
                }
            }
        )

        changes = classify_changes(before, after)

        assert kinds(changes) == {"request_content_type_removed"}
        assert breaking(changes)
        assert "multipart/form-data" in changes[0].detail

    def test_relaxing_a_lower_bound_is_not_breaking(self):
        before = spec(schemas={"Q": obj({"n": {"type": "integer", "minimum": 10}})})
        after = spec(schemas={"Q": obj({"n": {"type": "integer", "minimum": 1}})})

        changes = classify_changes(before, after)

        assert changes and not breaking(changes)

    def test_tightening_a_lower_bound_is_breaking(self):
        before = spec(schemas={"Q": obj({"n": {"type": "integer", "minimum": 1}})})
        after = spec(schemas={"Q": obj({"n": {"type": "integer", "minimum": 10}})})

        assert breaking(classify_changes(before, after))

    def test_a_non_numeric_constraint_change_is_breaking(self):
        before = spec(schemas={"Q": obj({"at": {"type": "string", "format": "date-time"}})})
        after = spec(schemas={"Q": obj({"at": {"type": "string", "format": "date"}})})

        assert breaking(classify_changes(before, after))

    def test_dropping_a_constraint_entirely_is_additive(self):
        before = spec(schemas={"Q": obj({"name": {"type": "string", "maxLength": 50}})})
        after = spec(schemas={"Q": obj({"name": {"type": "string"}})})

        changes = classify_changes(before, after)

        assert kinds(changes) == {"constraint_changed"}
        assert not breaking(changes)
        assert "removed" in changes[0].detail

    def test_a_parameter_becoming_optional_is_additive(self):
        before = spec(
            {"/v1/models": {"get": op(parameters=[{"name": "q", "in": "query", "required": True}])}}
        )
        after = spec(
            {
                "/v1/models": {
                    "get": op(parameters=[{"name": "q", "in": "query", "required": False}])
                }
            }
        )

        changes = classify_changes(before, after)

        assert kinds(changes) == {"parameter_no_longer_required"}
        assert not breaking(changes)


class TestPublicSubset:
    def test_non_v1_paths_are_excluded(self):
        from meshapi_contract import public_subset

        subset = public_subset(
            {"paths": {"/v1/models": {"get": {}}, "/admin/keys": {"get": {}}}, "components": {}}
        )

        assert list(subset["paths"]) == ["/v1/models"]

    def test_x_internal_operations_are_excluded(self):
        from meshapi_contract import public_subset

        subset = public_subset(
            {
                "paths": {
                    "/v1/keys": {"get": {}, "delete": {"x-internal": True}},
                    "/v1/secret": {"get": {"x-internal": True}},
                    "/v1/whole-path": {"x-internal": True, "get": {}},
                },
                "components": {},
            }
        )

        assert list(subset["paths"]) == ["/v1/keys"]
        assert list(subset["paths"]["/v1/keys"]) == ["get"]

    def test_only_schemas_reachable_from_public_paths_are_kept(self):
        from meshapi_contract import public_subset

        subset = public_subset(
            {
                "paths": {"/v1/models": {"get": op(response_ref="Model")}},
                "components": {
                    "schemas": {
                        "Model": obj({"price": {"$ref": "#/components/schemas/Price"}}),
                        "Price": obj({"amount": {"type": "string"}}),
                        "AdminOnly": obj({"secret": {"type": "string"}}),
                    }
                },
            }
        )

        assert sorted(subset["components"]["schemas"]) == ["Model", "Price"]

    def test_a_self_referencing_schema_does_not_hang(self):
        from meshapi_contract import public_subset

        subset = public_subset(
            {
                "paths": {"/v1/tree": {"get": op(response_ref="Node")}},
                "components": {
                    "schemas": {
                        "Node": obj({"children": {"items": {"$ref": "#/components/schemas/Node"}}})
                    }
                },
            }
        )

        assert list(subset["components"]["schemas"]) == ["Node"]

    def test_prose_is_stripped_but_default_is_kept(self):
        from meshapi_contract import public_subset

        subset = public_subset(
            {
                "paths": {
                    "/v1/models": {
                        "get": {
                            "summary": "List models",
                            "operationId": "list_models",
                            "responses": {"200": {"description": "ok"}},
                        }
                    }
                },
                "components": {"schemas": {}},
            }
        )
        operation = subset["paths"]["/v1/models"]["get"]

        assert "summary" not in operation and "operationId" not in operation
        assert "description" not in operation["responses"]["200"]

    def test_a_changed_default_survives_stripping(self):
        from meshapi_contract import public_subset

        subset = public_subset(
            {
                "paths": {"/v1/models": {"get": op(response_ref="Q")}},
                "components": {
                    "schemas": {"Q": obj({"limit": {"type": "integer", "default": 20}})}
                },
            }
        )

        assert subset["components"]["schemas"]["Q"]["properties"]["limit"]["default"] == 20
