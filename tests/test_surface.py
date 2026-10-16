import json

import pytest

from meshapi_contract.surface import (
    ACTUAL_SCHEMA_VERSION,
    Surface,
    SurfaceVersionError,
    actual_surface_from_json,
    diff_surface,
    expected_surface,
    load_actual,
)


def _ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def _body(name):
    return {"content": {"application/json": {"schema": _ref(name)}}}


def _spec(op, schemas):
    return {
        "paths": {"/v1/chat": {"post": op}},
        "components": {"schemas": schemas},
    }


def test_expected_surface_one_op():
    spec = _spec(
        {
            "operationId": "chat",
            "parameters": [{"name": "limit", "in": "query"}],
            "requestBody": _body("Req"),
            "responses": {"200": _body("Resp")},
        },
        {
            "Req": {"properties": {"model": {}, "prompt": {}}},
            "Resp": {"properties": {"id": {}}},
        },
    )
    s = expected_surface(spec)
    assert s.model_fields == {("Req", "model"), ("Req", "prompt"), ("Resp", "id")}
    assert s.params == {"POST /v1/chat:limit"}


def test_op_without_operation_id_keyed_by_path():
    spec = _spec({"parameters": [{"name": "q"}], "responses": {}}, {})
    assert expected_surface(spec).params == {"POST /v1/chat:q"}


def test_ref_to_missing_schema_contributes_nothing():
    spec = _spec({"requestBody": _body("Ghost"), "responses": {}}, {})
    s = expected_surface(spec)
    assert s.model_fields == frozenset()


def test_allof_request_model_merges_fields():
    spec = _spec(
        {"requestBody": _body("Req"), "responses": {}},
        {
            "Req": {
                "allOf": [_ref("Base"), {"properties": {"extra": {}}}],
                "properties": {"own": {}},
            },
            "Base": {"properties": {"a": {}, "b": {}}},
        },
    )
    fields = {f for m, f in expected_surface(spec).model_fields if m == "Req"}
    assert fields == {"a", "b", "extra", "own"}


def test_diff_empty_when_actual_superset():
    exp = Surface(frozenset({("M", "a")}), frozenset({"p"}))
    act = Surface(frozenset({("M", "a"), ("M", "z")}), frozenset({"p", "q"}))
    assert diff_surface(exp, act) == []


def test_diff_lists_missing_field():
    exp = Surface(frozenset({("M", "a"), ("M", "b")}), frozenset({"p"}))
    act = Surface(frozenset({("M", "a")}), frozenset({"p"}))
    rows = diff_surface(exp, act)
    assert rows == ["missing field: M.b"]


def test_load_actual_version_mismatch(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"spec_version": "1.0.0", "model_fields": [["M", "a"]], "params": []}))
    assert load_actual(str(f), "1.0.0").model_fields == {("M", "a")}
    with pytest.raises(SurfaceVersionError):
        load_actual(str(f), "2.0.0")
    assert isinstance(ACTUAL_SCHEMA_VERSION, str)
    assert actual_surface_from_json({"model_fields": [], "params": []}) == Surface(frozenset(), frozenset())


def test_nested_ref_field_included():
    spec = _spec(
        {"requestBody": _body("Req"), "responses": {}},
        {
            "Req": {"properties": {"fmt": _ref("Fmt")}},
            "Fmt": {"properties": {"type": {}}},
        },
    )
    assert expected_surface(spec).model_fields == {("Req", "fmt"), ("Fmt", "type")}


def test_array_items_ref_included():
    spec = _spec(
        {"requestBody": _body("Req"), "responses": {}},
        {
            "Req": {"properties": {"messages": {"type": "array", "items": _ref("Msg")}}},
            "Msg": {"properties": {"role": {}, "tool": {"anyOf": [_ref("Tool")]}}},
            "Tool": {"properties": {"name": {}}},
        },
    )
    assert expected_surface(spec).model_fields == {
        ("Req", "messages"), ("Msg", "role"), ("Msg", "tool"), ("Tool", "name"),
    }


def test_self_referential_schema_terminates():
    spec = _spec(
        {"requestBody": _body("Node"), "responses": {}},
        {"Node": {"properties": {"child": _ref("Node"), "v": {}}}},
    )
    assert expected_surface(spec).model_fields == {("Node", "child"), ("Node", "v")}


def test_diff_rows_sorted():
    exp = Surface(frozenset({("Z", "a"), ("A", "b"), ("M", "c")}), frozenset({"p2", "p1"}))
    rows = diff_surface(exp, Surface(frozenset(), frozenset()))
    assert len(rows) == 5
    assert rows == sorted(rows)


def test_diff_reports_missing_param():
    exp = Surface(frozenset(), frozenset({"GET /x:q"}))
    assert diff_surface(exp, Surface(frozenset(), frozenset())) == ["missing param: GET /x:q"]


def test_load_actual_envelope_version(tmp_path):
    f = tmp_path / "s.json"
    base = {"spec_version": "1", "model_fields": [], "params": []}
    f.write_text(json.dumps({**base, "schema_version": ACTUAL_SCHEMA_VERSION}))
    load_actual(str(f), "1")
    f.write_text(json.dumps({**base, "schema_version": "999"}))
    with pytest.raises(SurfaceVersionError):
        load_actual(str(f), "1")
