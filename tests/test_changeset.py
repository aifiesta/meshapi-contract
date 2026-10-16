from __future__ import annotations

import ast
from pathlib import Path

from meshapi_contract import Change, ChangeSet, build_changeset
from meshapi_contract.changeset import _bucket_for

DIFF_SOURCE = Path(__file__).resolve().parent.parent / "src" / "meshapi_contract" / "diff.py"


def spec(paths=None, schemas=None) -> dict:
    return {
        "openapi": "3.1.0",
        "paths": paths if paths is not None else {},
        "components": {"schemas": schemas if schemas is not None else {}},
    }


def op_with_response_ref(ref: str) -> dict:
    return {
        "responses": {
            "200": {
                "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{ref}"}}}
            }
        }
    }


def test_operation_added_and_removed_group_into_endpoints():
    before = spec(paths={"/v1/a": {"get": op_with_response_ref("M")}})
    after = spec(paths={"/v1/b": {"post": op_with_response_ref("M")}})

    cs = build_changeset(before, after)

    assert cs.endpoints_added == ("POST /v1/b",)
    assert cs.endpoints_removed == ("GET /v1/a",)
    assert cs.has_breaking is True


def test_schema_field_change_groups_into_schemas_changed_with_name():
    before = spec(schemas={"Model": {"type": "object", "properties": {"id": {"type": "string"}}}})
    after = spec(
        schemas={
            "Model": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "extra": {"type": "string"}},
            }
        }
    )

    cs = build_changeset(before, after)

    assert cs.schemas_changed == ("Model.extra",)
    assert cs.endpoints_added == ()


def test_parameter_kinds_split_into_params_added_and_removed():
    before = spec(
        paths={
            "/v1/a": {
                "get": {
                    "parameters": [{"name": "old", "in": "query", "schema": {"type": "string"}}],
                    "responses": {},
                }
            }
        }
    )
    after = spec(
        paths={
            "/v1/a": {
                "get": {
                    "parameters": [{"name": "new", "in": "query", "schema": {"type": "string"}}],
                    "responses": {},
                }
            }
        }
    )

    cs = build_changeset(before, after)

    assert len(cs.params_removed) == 1
    assert len(cs.params_added) == 1
    assert "new" in cs.params_added[0]
    assert "old" in cs.params_removed[0]


def test_changed_parameter_kinds_land_in_params_changed_not_added():
    before = spec(
        paths={
            "/v1/a": {
                "get": {
                    "parameters": [{"name": "q", "in": "query", "schema": {"type": "string"}}],
                    "responses": {},
                }
            }
        }
    )
    after = spec(
        paths={
            "/v1/a": {
                "get": {
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {},
                }
            }
        }
    )

    cs = build_changeset(before, after)

    assert cs.params_changed == ("GET /v1/a ?q", "GET /v1/a ?q: string -> integer")
    assert cs.params_added == ()
    assert cs.params_removed == ()


def test_response_and_request_body_kinds_group_into_endpoints_changed():
    before = spec(
        paths={
            "/v1/a": {
                "get": {
                    "responses": {"200": {"description": "ok"}, "404": {"description": "nf"}},
                },
                "post": {
                    "requestBody": {
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    },
                    "responses": {},
                },
            }
        }
    )
    after = spec(
        paths={
            "/v1/a": {
                "get": {"responses": {"200": {"description": "ok"}}},
                "post": {"responses": {}},
            }
        }
    )

    cs = build_changeset(before, after)

    kinds = {c.kind for c in cs.changes}
    assert "response_status_removed" in kinds
    assert "request_body_removed" in kinds
    assert cs.endpoints_changed == ("GET /v1/a -> 404", "POST /v1/a")
    assert cs.params_added == ()
    assert cs.schemas_changed == ()


def test_has_breaking_is_any_of_change_breaking_flags():
    before = spec(paths={"/v1/a": {"get": op_with_response_ref("M")}})
    after = spec(paths={"/v1/a": {"get": op_with_response_ref("M")}, "/v1/b": {"get": {}}})

    cs = build_changeset(before, after)

    assert all(not c.breaking for c in cs.changes)
    assert cs.has_breaking is False


def test_has_breaking_true_when_any_change_is_breaking():
    before = spec(schemas={"Model": {"type": "object", "properties": {"a": {"type": "string"}}}})
    after = spec(
        schemas={"Model": {"type": "object", "properties": {"b": {"type": "string"}}}},
        paths={"/v1/new": {"get": {"responses": {}}}},
    )

    cs = build_changeset(before, after)

    kinds = {c.kind for c in cs.changes}
    assert {"field_removed", "field_added", "operation_added"} <= kinds
    assert cs.has_breaking is True


def test_request_content_type_removed_groups_into_endpoints_changed():
    body = {"content": {"application/json": {"schema": {"type": "object"}}}}
    body_two_types = {
        "content": {
            "application/json": {"schema": {"type": "object"}},
            "text/plain": {"schema": {"type": "string"}},
        }
    }
    before = spec(paths={"/v1/a": {"post": {"requestBody": body_two_types, "responses": {}}}})
    after = spec(paths={"/v1/a": {"post": {"requestBody": body, "responses": {}}}})

    cs = build_changeset(before, after)

    assert cs.endpoints_changed == ("POST /v1/a: text/plain",)
    assert cs.has_breaking is True
    assert cs.params_added == ()


def test_from_and_to_version_pass_through_verbatim():
    cs = build_changeset(spec(), spec(), from_version="2026-08", to_version="2026-10")

    assert cs.from_version == "2026-08"
    assert cs.to_version == "2026-10"


def test_version_defaults_to_none():
    cs = build_changeset(spec(), spec())

    assert cs.from_version is None
    assert cs.to_version is None


def test_empty_diff_yields_empty_buckets_and_no_breaking():
    cs = build_changeset(spec(), spec())

    assert cs == ChangeSet(
        from_version=None,
        to_version=None,
        changes=(),
        endpoints_added=(),
        endpoints_removed=(),
        endpoints_changed=(),
        schemas_changed=(),
        params_added=(),
        params_removed=(),
        params_changed=(),
        deprecations=(),
        has_breaking=False,
    )


def test_grouping_keys_off_kind_not_detail_text():
    # Field names are chosen so their detail strings contain bucket keywords and " -> ";
    # a detail-parsing implementation would misroute both changes.
    before = spec(
        schemas={"Model": {"type": "object", "properties": {"x -> y": {"type": "string"}}}}
    )
    after = spec(
        schemas={
            "Model": {
                "type": "object",
                "properties": {
                    "parameter_removed": {"type": "string"},
                    "x -> y": {"type": "integer"},
                },
            }
        }
    )

    cs = build_changeset(before, after)

    assert cs.schemas_changed == (
        "Model.parameter_removed",
        "Model.x -> y: string -> integer",
    )
    assert cs.params_added == ()
    assert cs.params_removed == ()
    assert cs.params_changed == ()


def test_deprecations_list_deprecated_operations_and_schemas_sorted():
    after = spec(
        paths={
            "/v1/b": {"get": {"deprecated": True, "responses": {}}},
            "/v1/a": {"get": {"x-sunset": "2027-01-01", "responses": {}}},
            "/v1/c": {"get": {"responses": {}}},
        },
        schemas={
            "Old": {"type": "object", "deprecated": True},
            "Unmarked": {"type": "object", "x-sunset": None},
            "New": {"type": "object"},
        },
    )

    cs = build_changeset(spec(), after)

    assert cs.deprecations == ("GET /v1/a", "GET /v1/b", "Old")


def test_deprecations_empty_when_none_marked():
    cs = build_changeset(spec(), spec(paths={"/v1/a": {"get": {"responses": {}}}}))

    assert cs.deprecations == ()


def test_change_records_are_preserved_in_changes():
    before = spec(paths={"/v1/a": {"get": {"responses": {}}}})
    after = spec()

    cs = build_changeset(before, after)

    assert cs.changes == (
        Change(kind="operation_removed", detail="GET /v1/a", breaking=True),
    )


def _kinds_emitted_by_diff() -> set[str]:
    # Collects every string literal inside a `kind=` argument, so ternaries like
    # `kind="a" if x else "b"` contribute both branches.
    tree = ast.parse(DIFF_SOURCE.read_text())
    kinds: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "kind":
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    kinds.add(sub.value)
    return kinds


def test_every_kind_emitted_by_diff_is_routed_to_a_bucket():
    kinds = _kinds_emitted_by_diff()

    assert "type_changed" in kinds  # guards the ast walk against an empty result
    unrouted = sorted(k for k in kinds if _bucket_for(k) is None)
    assert unrouted == []


def test_x_sunset_false_or_empty_is_not_deprecated():
    after = spec(
        paths={
            "/v1/a": {"get": {"x-sunset": False, "responses": {}}},
            "/v1/b": {"get": {"x-sunset": "", "responses": {}}},
        },
        schemas={"Model": {"type": "object", "x-sunset": False}},
    )

    cs = build_changeset(spec(), after)

    assert cs.deprecations == ()
