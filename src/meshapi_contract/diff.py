from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

_NON_OPERATION_KEYS = ("parameters", "summary", "description", "servers", "$ref")


@dataclass(frozen=True)
class Change:
    kind: str
    detail: str
    breaking: bool

    def __str__(self) -> str:  # pragma: no cover - convenience for failure output
        return f"[{'BREAKING' if self.breaking else 'additive'}] {self.kind}: {self.detail}"


def operations(spec: dict) -> dict[tuple[str, str], dict]:
    found: dict[tuple[str, str], dict] = {}
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, body in item.items():
            if method.lower() in _HTTP_METHODS and isinstance(body, dict):
                found[(method.upper(), path)] = body
    return found


def _schemas(spec: dict) -> dict[str, dict]:
    schemas = ((spec.get("components") or {}).get("schemas")) or {}
    return {name: body for name, body in schemas.items() if isinstance(body, dict)}


def _properties(schema: dict) -> dict[str, Any]:
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


def _required(schema: dict) -> set[str]:
    required = schema.get("required")
    return set(required) if isinstance(required, list) else set()


def _enum(schema: dict) -> list | None:
    values = schema.get("enum")
    return values if isinstance(values, list) else None


def _type_signature(schema: Any) -> str:
    if not isinstance(schema, dict):
        return repr(schema)
    if "$ref" in schema:
        return str(schema["$ref"])
    for combinator in ("anyOf", "oneOf", "allOf"):
        if combinator in schema and isinstance(schema[combinator], list):
            members = sorted(_type_signature(m) for m in schema[combinator])
            return f"{combinator}[{', '.join(members)}]"
    declared = schema.get("type")
    if declared == "array":
        return f"array[{_type_signature(schema.get('items'))}]"
    if declared is None:
        return "any"
    return str(declared)


def _only_widens(old: Any, new: Any) -> bool:
    # Deep equality, not _type_signature: that rendering drops validation keywords,
    # so a shrunk maxLength beside an added member would read as a pure addition.
    if old == new:
        return True
    if not isinstance(old, dict) or not isinstance(new, dict):
        return False

    if old.get("type") == "array" and new.get("type") == "array":
        return _only_widens(old.get("items"), new.get("items")) and _without(
            old, "items"
        ) == _without(new, "items")

    # An added alternative that nobody could send before rejects nothing.
    old_members, new_members = old.get("anyOf"), new.get("anyOf")
    if isinstance(old_members, list) and isinstance(new_members, list):
        if _without(old, "anyOf") != _without(new, "anyOf"):
            return False
        return all(any(_only_widens(o, n) for n in new_members) for o in old_members)
    return False


def _without(schema: dict, key: str) -> dict:
    return {k: v for k, v in schema.items() if k != key}


# Keyed by name alone: a name moving between query and header is one type change,
# not a removal plus an addition.
def _parameters(operation: dict) -> dict[str, dict]:
    params = operation.get("parameters")
    if not isinstance(params, list):
        return {}
    return {p["name"]: p for p in params if isinstance(p, dict) and "name" in p}


def _version_labels(spec: dict) -> set[str]:
    published = spec.get("x-mesh-api-versions")
    if not isinstance(published, list):
        return set()
    return {entry["label"] for entry in published if isinstance(entry, dict) and "label" in entry}


# Read from the spec root so the baseline records which versions existed when it was generated.
def published_a_new_version(before: dict, after: dict) -> bool:
    return bool(_version_labels(after) - _version_labels(before))


def classify_changes(before: dict, after: dict) -> list[Change]:
    changes: list[Change] = []
    changes.extend(_operation_changes(before, after))
    changes.extend(_schema_changes(before, after))
    changes.extend(_parameter_changes(before, after))
    return changes


def _operation_changes(before: dict, after: dict) -> Iterable[Change]:
    old, new = operations(before), operations(after)

    for method, path in sorted(set(old) - set(new)):
        yield Change(
            kind="operation_removed",
            detail=f"{method} {path}",
            breaking=True,
        )
    for method, path in sorted(set(new) - set(old)):
        yield Change(kind="operation_added", detail=f"{method} {path}", breaking=False)


def _schema_changes(before: dict, after: dict) -> Iterable[Change]:
    old, new = _schemas(before), _schemas(after)

    for name in sorted(set(old) - set(new)):
        yield Change(
            kind="schema_removed",
            detail=f"{name} — every operation returning or accepting it changes shape",
            breaking=True,
        )

    for name in sorted(set(old) & set(new)):
        yield from _one_schema_changes(name, old[name], new[name])


def _one_schema_changes(name: str, old: dict, new: dict) -> Iterable[Change]:
    old_props, new_props = _properties(old), _properties(new)

    for field in sorted(set(old_props) - set(new_props)):
        yield Change(kind="field_removed", detail=f"{name}.{field}", breaking=True)
    for field in sorted(set(new_props) - set(old_props)):
        yield Change(kind="field_added", detail=f"{name}.{field}", breaking=False)

    for field in sorted(set(old_props) & set(new_props)):
        old_type = _type_signature(old_props[field])
        new_type = _type_signature(new_props[field])
        # A union that only gained a member accepts strictly more, so no working request is refused.
        if old_type != new_type:
            widened = _only_widens(old_props[field], new_props[field])
            yield Change(
                kind="union_member_added" if widened else "type_changed",
                detail=f"{name}.{field}: {old_type} -> {new_type}",
                breaking=not widened,
            )
        yield from _value_changes(f"{name}.{field}", old_props[field], new_props[field])

    # Only a field callers were already sending can break when it becomes required.
    for field in sorted(_required(new) - _required(old)):
        if field in old_props:
            yield Change(kind="field_now_required", detail=f"{name}.{field}", breaking=True)
    for field in sorted(_required(old) - _required(new)):
        yield Change(kind="field_no_longer_required", detail=f"{name}.{field}", breaking=False)

    old_enum, new_enum = _enum(old), _enum(new)
    if old_enum is not None and new_enum is not None:
        for value in sorted(set(map(repr, old_enum)) - set(map(repr, new_enum))):
            yield Change(
                kind="enum_value_removed",
                detail=f"{name}: {value} is no longer accepted or returned",
                breaking=True,
            )
        for value in sorted(set(map(repr, new_enum)) - set(map(repr, old_enum))):
            # Additive by convention, else no new model type or status could ever ship.
            yield Change(kind="enum_value_added", detail=f"{name}: {value}", breaking=False)


# Tightening a validation keyword rejects requests that worked before; relaxing accepts more.
_CONSTRAINT_KEYS = (
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minItems",
    "maxItems",
    "pattern",
    "multipleOf",
    "format",
)

_UPPER_BOUNDS = ("maxLength", "maximum", "maxItems", "exclusiveMaximum")
_LOWER_BOUNDS = ("minLength", "minimum", "minItems", "exclusiveMinimum")


def _relaxes(key: str, was: Any, now: Any) -> bool:
    if not isinstance(was, (int, float)) or not isinstance(now, (int, float)):
        return False
    if key in _UPPER_BOUNDS:
        return now > was
    if key in _LOWER_BOUNDS:
        return now < was
    return False


def _value_changes(where: str, old: Any, new: Any) -> Iterable[Change]:
    if not isinstance(old, dict) or not isinstance(new, dict):
        return

    # A changed default silently changes behaviour for every caller who omits the field.
    if old.get("default") != new.get("default"):
        yield Change(
            kind="default_changed",
            detail=f"{where}: default {old.get('default')!r} -> {new.get('default')!r}",
            breaking=True,
        )

    for key in _CONSTRAINT_KEYS:
        was, now = old.get(key), new.get(key)
        if was == now:
            continue
        # Dropping a constraint accepts more, so it is not breaking.
        if now is None:
            yield Change(
                kind="constraint_changed",
                detail=f"{where}: {key} {was!r} removed",
                breaking=False,
            )
            continue
        yield Change(
            kind="constraint_changed",
            detail=f"{where}: {key} {was!r} -> {now!r}",
            breaking=not _relaxes(key, was, now),
        )


def _parameter_changes(before: dict, after: dict) -> Iterable[Change]:
    old_ops, new_ops = operations(before), operations(after)

    for key in sorted(set(old_ops) & set(new_ops)):
        method, path = key
        where = f"{method} {path}"
        old_params, new_params = _parameters(old_ops[key]), _parameters(new_ops[key])

        for name in sorted(set(old_params) - set(new_params)):
            yield Change(
                kind="parameter_removed",
                detail=f"{where} ?{name} — silently ignored from now on",
                breaking=True,
            )
        for name in sorted(set(new_params) - set(old_params)):
            required = bool(new_params[name].get("required"))
            yield Change(
                kind="parameter_added_required" if required else "parameter_added",
                detail=f"{where} ?{name}",
                breaking=required,
            )
        for name in sorted(set(old_params) & set(new_params)):
            old_param, new_param = old_params[name], new_params[name]
            was = bool(old_param.get("required"))
            now = bool(new_param.get("required"))
            if now and not was:
                yield Change(
                    kind="parameter_now_required", detail=f"{where} ?{name}", breaking=True
                )
            elif was and not now:
                yield Change(
                    kind="parameter_no_longer_required",
                    detail=f"{where} ?{name}",
                    breaking=False,
                )

            if old_param.get("in") != new_param.get("in"):
                yield Change(
                    kind="parameter_location_changed",
                    detail=f"{where} ?{name}: in {old_param.get('in')} -> {new_param.get('in')}",
                    breaking=True,
                )

            old_sig = _type_signature(old_param.get("schema"))
            new_sig = _type_signature(new_param.get("schema"))
            if old_sig != new_sig:
                yield Change(
                    kind="parameter_type_changed",
                    detail=f"{where} ?{name}: {old_sig} -> {new_sig}",
                    breaking=True,
                )
            yield from _value_changes(
                f"{where} ?{name}", old_param.get("schema"), new_param.get("schema")
            )

        yield from _response_changes(where, old_ops[key], new_ops[key])
        yield from _request_body_changes(where, old_ops[key], new_ops[key])


def _responses(operation: dict) -> dict[str, dict]:
    responses = operation.get("responses")
    return responses if isinstance(responses, dict) else {}


def _content_types(node: Any) -> set[str]:
    content = node.get("content") if isinstance(node, dict) else None
    return set(content) if isinstance(content, dict) else set()


def _response_changes(where: str, old: dict, new: dict) -> Iterable[Change]:
    old_responses, new_responses = _responses(old), _responses(new)

    for status in sorted(set(old_responses) - set(new_responses)):
        yield Change(kind="response_status_removed", detail=f"{where} -> {status}", breaking=True)
    for status in sorted(set(new_responses) - set(old_responses)):
        yield Change(kind="response_status_added", detail=f"{where} -> {status}", breaking=False)

    for status in sorted(set(old_responses) & set(new_responses)):
        old_types = _content_types(old_responses[status])
        new_types = _content_types(new_responses[status])
        for media in sorted(old_types - new_types):
            yield Change(
                kind="response_content_type_removed",
                detail=f"{where} -> {status}: {media}",
                breaking=True,
            )
        for media in sorted(new_types - old_types):
            yield Change(
                kind="response_content_type_added",
                detail=f"{where} -> {status}: {media}",
                breaking=False,
            )


def _request_body_changes(where: str, old: dict, new: dict) -> Iterable[Change]:
    old_body = old.get("requestBody") if isinstance(old.get("requestBody"), dict) else None
    new_body = new.get("requestBody") if isinstance(new.get("requestBody"), dict) else None

    if old_body is None and new_body is not None:
        yield Change(
            kind="request_body_added",
            detail=f"{where}",
            breaking=bool(new_body.get("required")),
        )
        return
    if old_body is not None and new_body is None:
        yield Change(kind="request_body_removed", detail=f"{where}", breaking=True)
        return
    if old_body is None or new_body is None:
        return

    if bool(new_body.get("required")) and not bool(old_body.get("required")):
        yield Change(kind="request_body_now_required", detail=f"{where}", breaking=True)

    for media in sorted(_content_types(old_body) - _content_types(new_body)):
        yield Change(kind="request_content_type_removed", detail=f"{where}: {media}", breaking=True)


# Mirrors the publishing pipeline's filter, so the gate guards the set customers read.
def public_subset(spec: dict) -> dict:
    paths: dict[str, dict] = {}
    for path, item in (spec.get("paths") or {}).items():
        if not path.startswith("/v1/") or not isinstance(item, dict):
            continue
        if item.get("x-internal") is True:
            continue
        kept = {
            key: value
            for key, value in item.items()
            if key.lower() not in _HTTP_METHODS
            or not (isinstance(value, dict) and value.get("x-internal") is True)
        }
        if any(key.lower() in _HTTP_METHODS for key in kept):
            paths[path] = kept

    all_schemas = (spec.get("components") or {}).get("schemas") or {}
    paths = _strip_prose(paths)
    return {
        "x-mesh-api-versions": spec.get("x-mesh-api-versions", []),
        "paths": paths,
        "components": {"schemas": _reachable_schemas(paths, all_schemas)},
    }


# components.schemas is global; snapshotting all of it would fail the gate on admin-only edits.
def _refs(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            yield ref.rsplit("/", 1)[-1]
        for value in node.values():
            yield from _refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _refs(item)


def _reachable_schemas(paths: dict, schemas: dict) -> dict:
    seen: set[str] = set()
    queue = list(_refs(paths))
    while queue:
        name = queue.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        queue.extend(_refs(schemas[name]))
    return {name: _strip_prose(schemas[name]) for name in sorted(seen)}


# Documentation-only keys, dropped so a baseline diff shows contract changes and nothing else.
_PROSE_KEYS = frozenset(
    {
        "description",
        "title",
        "summary",
        "example",
        "examples",
        "operationId",
        "tags",
        "externalDocs",
        "x-codeSamples",
        "x-page-icon",
        "x-enumDescriptions",
    }
)


# Keys directly under `properties` are field names, which may collide with prose keys (`tags`).
def _strip_prose(node: Any, *, naming_fields: bool = False) -> Any:
    if isinstance(node, dict):
        return {
            key: _strip_prose(value, naming_fields=(key == "properties"))
            for key, value in node.items()
            if naming_fields or key not in _PROSE_KEYS
        }
    if isinstance(node, list):
        return [_strip_prose(item) for item in node]
    return node


def render(spec: dict) -> str:
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"
