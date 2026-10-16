from __future__ import annotations

import json
from dataclasses import dataclass

from meshapi_contract.diff import _schemas, operations

ACTUAL_SCHEMA_VERSION = "1"

_REF_PREFIX = "#/components/schemas/"
_COMPOSITION = ("allOf", "anyOf", "oneOf")


class SurfaceVersionError(ValueError):
    pass


@dataclass(frozen=True)
class Surface:
    model_fields: frozenset[tuple[str, str]]
    params: frozenset[str]


def _ref_name(node: dict) -> str | None:
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
        return ref[len(_REF_PREFIX):]
    return None


class _Walker:
    def __init__(self, schemas: dict[str, dict]) -> None:
        self.schemas = schemas
        self.out: set[tuple[str, str]] = set()
        self.entered: set[str] = set()

    def enter(self, name: str) -> None:
        # entered doubles as the cycle guard for self/mutually recursive models
        if name in self.entered or name not in self.schemas:
            return
        self.entered.add(name)
        self.members(self.schemas[name], name, frozenset({name}))

    def members(self, node: dict, owner: str, stack: frozenset[str]) -> None:
        for field, value in (node.get("properties") or {}).items():
            self.out.add((owner, field))
            self.refs_in(value)
        for key in _COMPOSITION:
            for member in node.get(key) or []:
                if not isinstance(member, dict):
                    continue
                name = _ref_name(member)
                if name is None:
                    self.members(member, owner, stack)
                elif name in self.schemas and name not in stack:
                    # composed members merge into the owner's own fields
                    self.members(self.schemas[name], owner, stack | {name})

    def refs_in(self, node: object) -> None:
        if not isinstance(node, dict):
            return
        name = _ref_name(node)
        if name is not None:
            self.enter(name)
            return
        self.refs_in(node.get("items"))
        self.refs_in(node.get("additionalProperties"))
        for value in (node.get("properties") or {}).values():
            self.refs_in(value)
        for key in _COMPOSITION:
            for member in node.get(key) or []:
                self.refs_in(member)


def _body_schemas(op: dict) -> list[dict]:
    containers = [op.get("requestBody")]
    containers += list((op.get("responses") or {}).values())
    found = []
    for container in containers:
        if not isinstance(container, dict):
            continue
        for media in (container.get("content") or {}).values():
            schema = media.get("schema") if isinstance(media, dict) else None
            if isinstance(schema, dict):
                found.append(schema)
    return found


def expected_surface(spec: dict) -> Surface:
    schemas = _schemas(spec)
    walker = _Walker(schemas)
    params: set[str] = set()
    for (method, path), op in operations(spec).items():
        path_level = ((spec.get("paths") or {}).get(path) or {}).get("parameters") or []
        for param in [*path_level, *(op.get("parameters") or [])]:
            if isinstance(param, dict) and "name" in param:
                params.add(f"{method} {path}:{param['name']}")
        for schema in _body_schemas(op):
            walker.refs_in(schema)
    return Surface(frozenset(walker.out), frozenset(params))


def actual_surface_from_json(data: dict) -> Surface:
    return Surface(
        frozenset((m, f) for m, f in data.get("model_fields", [])),
        frozenset(data.get("params", [])),
    )


def diff_surface(expected: Surface, actual: Surface) -> list[str]:
    rows = [
        f"missing field: {m}.{f}" for m, f in expected.model_fields - actual.model_fields
    ]
    rows += [f"missing param: {p}" for p in expected.params - actual.params]
    return sorted(rows)


def load_actual(path: str, spec_version: str) -> Surface:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    envelope = data.get("schema_version")
    if envelope is not None and envelope != ACTUAL_SCHEMA_VERSION:
        raise SurfaceVersionError(
            f"surface schema_version {envelope!r} != supported {ACTUAL_SCHEMA_VERSION!r}"
        )
    found = data.get("spec_version")
    if found != spec_version:
        raise SurfaceVersionError(
            f"surface file spec_version {found!r} != expected {spec_version!r}"
        )
    return actual_surface_from_json(data)
