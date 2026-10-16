from __future__ import annotations

from meshapi_contract import public_subset

VERSIONS = [{"label": "2026-08"}]


def _ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def _get(response_schema: str) -> dict:
    return {
        "responses": {"200": {"content": {"application/json": {"schema": _ref(response_schema)}}}}
    }


def _spec(paths: dict, schemas: dict | None = None) -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "x", "version": "9.9.9"},
        "servers": [{"url": "https://example.invalid"}],
        "x-mesh-api-versions": VERSIONS,
        "paths": paths,
        "components": {"schemas": schemas or {}},
    }


def test_paths_outside_the_v1_namespace_are_dropped():
    spec = _spec({"/v1/models": {"get": _get("Model")}, "/health": {"get": _get("Model")}})

    assert set(public_subset(spec)["paths"]) == {"/v1/models"}


def test_operations_flagged_internal_are_dropped():
    spec = _spec(
        {
            "/v1/models": {
                "get": _get("Model"),
                "post": {"x-internal": True, **_get("Model")},
            },
            "/v1/keys": {"get": {"x-internal": True, **_get("Model")}},
        }
    )

    paths = public_subset(spec)["paths"]

    assert set(paths) == {"/v1/models"}
    assert set(paths["/v1/models"]) == {"get"}


def test_the_api_version_list_is_kept_and_the_root_metadata_is_not():
    subset = public_subset(_spec({"/v1/models": {"get": _get("Model")}}))

    assert subset["x-mesh-api-versions"] == VERSIONS
    assert "info" not in subset
    assert "servers" not in subset
    assert "openapi" not in subset


def test_schemas_no_public_operation_reaches_are_pruned():
    schemas = {
        "Model": {"type": "object", "properties": {"price": _ref("Price")}},
        "Price": {"type": "object", "properties": {"amount": {"type": "number"}}},
        "AdminOnly": {"type": "object", "properties": {"secret": {"type": "string"}}},
    }
    spec = _spec({"/v1/models": {"get": _get("Model")}}, schemas)

    assert set(public_subset(spec)["components"]["schemas"]) == {"Model", "Price"}


def test_a_schema_reached_only_through_an_internal_operation_is_pruned():
    schemas = {
        "Model": {"type": "object"},
        "Admin": {"type": "object", "properties": {"id": {"type": "string"}}},
    }
    spec = _spec(
        {
            "/v1/models": {"get": _get("Model")},
            "/v1/admin": {"get": {"x-internal": True, **_get("Admin")}},
        },
        schemas,
    )

    assert set(public_subset(spec)["components"]["schemas"]) == {"Model"}
