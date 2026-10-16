import json
import subprocess
import sys

from meshapi_contract.gate import main

SPEC = {
    "paths": {
        "/v1/chat": {
            "post": {
                "operationId": "chat",
                "parameters": [{"name": "limit", "in": "query"}],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Req"}
                        }
                    }
                },
                "responses": {},
            }
        }
    },
    "components": {"schemas": {"Req": {"properties": {"model": {}, "prompt": {}}}}},
}


def _write(tmp_path, spec_obj, actual_obj):
    spec = tmp_path / "openapi.json"
    actual = tmp_path / "actual.json"
    spec.write_text(json.dumps(spec_obj))
    actual.write_text(json.dumps(actual_obj))
    return ["--spec", str(spec), "--actual", str(actual)]


def _actual(fields, version="2026-01-01"):
    return {
        "schema_version": "1",
        "spec_version": version,
        "model_fields": fields,
        "params": ["POST /v1/chat:limit"],
    }


def test_ok_on_superset(tmp_path, capsys):
    args = _write(
        tmp_path, SPEC, _actual([["Req", "model"], ["Req", "prompt"], ["Req", "extra"]])
    )
    assert main([*args, "--spec-version", "2026-01-01"]) == 0
    assert "contract-check: OK (3 surface members)" in capsys.readouterr().out


def test_drift_lists_missing_rows(tmp_path, capsys):
    args = _write(tmp_path, SPEC, _actual([["Req", "model"]]))
    assert main([*args, "--spec-version", "2026-01-01"]) == 1
    out = capsys.readouterr().out
    assert "contract-check: DRIFT" in out
    assert "missing 1 spec surface member(s):" in out
    assert "missing field: Req.prompt" in out


def test_version_mismatch_exits_3(tmp_path, capsys):
    args = _write(tmp_path, SPEC, _actual([["Req", "model"]], version="old"))
    assert main([*args, "--spec-version", "2026-01-01"]) == 3
    assert "spec_version" in capsys.readouterr().out


def test_missing_file_exits_4(tmp_path, capsys):
    args = _write(tmp_path, SPEC, _actual([]))
    args[3] = str(tmp_path / "nope.json")
    assert main([*args, "--spec-version", "v"]) == 4
    assert "contract-check: error:" in capsys.readouterr().out


def test_malformed_json_exits_4(tmp_path, capsys):
    args = _write(tmp_path, SPEC, _actual([]))
    (tmp_path / "actual.json").write_text("{not json")
    assert main([*args, "--spec-version", "v"]) == 4
    assert "contract-check: error:" in capsys.readouterr().out


def test_non_object_actual_exits_4(tmp_path):
    args = _write(tmp_path, SPEC, [1, 2])
    assert main([*args, "--spec-version", "v"]) == 4


def test_empty_spec_exits_4(tmp_path, capsys):
    args = _write(tmp_path, {"paths": {}}, _actual([]))
    assert main([*args, "--spec-version", "2026-01-01"]) == 4
    assert "empty surface" in capsys.readouterr().out


def test_missing_schema_version_exits_4(tmp_path, capsys):
    actual = _actual([["Req", "model"]])
    del actual["schema_version"]
    args = _write(tmp_path, SPEC, actual)
    assert main([*args, "--spec-version", "2026-01-01"]) == 4
    assert "schema_version" in capsys.readouterr().out


def test_module_entrypoint(tmp_path):
    args = _write(tmp_path, SPEC, _actual([["Req", "model"], ["Req", "prompt"]]))
    r = subprocess.run(
        [sys.executable, "-m", "meshapi_contract.gate", *args, "--spec-version", "2026-01-01"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
