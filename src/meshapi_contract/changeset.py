from __future__ import annotations

from dataclasses import dataclass

from meshapi_contract.diff import Change, classify_changes, operations

_ENDPOINT_CHANGED_PREFIXES = ("response_status_", "response_content_type_", "request_body_")

_PARAMS_ADDED_KINDS = frozenset({"parameter_added", "parameter_added_required"})

_PARAMS_CHANGED_KINDS = frozenset(
    {
        "parameter_now_required",
        "parameter_no_longer_required",
        "parameter_location_changed",
        "parameter_type_changed",
    }
)

_SCHEMA_KINDS = frozenset(
    {
        "field_added",
        "field_removed",
        "type_changed",
        "union_member_added",
        "enum_value_added",
        "enum_value_removed",
        "field_now_required",
        "field_no_longer_required",
        "default_changed",
        "constraint_changed",
        "schema_removed",
    }
)


@dataclass(frozen=True)
class ChangeSet:
    from_version: str | None
    to_version: str | None
    changes: tuple[Change, ...]
    endpoints_added: tuple[str, ...]
    endpoints_removed: tuple[str, ...]
    endpoints_changed: tuple[str, ...]
    schemas_changed: tuple[str, ...]
    params_added: tuple[str, ...]
    params_removed: tuple[str, ...]
    params_changed: tuple[str, ...]
    deprecations: tuple[str, ...]
    has_breaking: bool


def build_changeset(
    before: dict,
    after: dict,
    *,
    from_version: str | None = None,
    to_version: str | None = None,
) -> ChangeSet:
    changes = classify_changes(before, after)
    buckets: dict[str, list[str]] = {
        "endpoints_added": [],
        "endpoints_removed": [],
        "endpoints_changed": [],
        "schemas_changed": [],
        "params_added": [],
        "params_removed": [],
        "params_changed": [],
    }
    for change in changes:
        bucket = _bucket_for(change.kind)
        if bucket is not None:
            buckets[bucket].append(change.detail)

    return ChangeSet(
        from_version=from_version,
        to_version=to_version,
        changes=tuple(changes),
        has_breaking=any(c.breaking for c in changes),
        deprecations=_deprecations(after),
        **{name: tuple(sorted(values)) for name, values in buckets.items()},
    )


# Kinds outside the taxonomy stay in `changes` but land in no bucket.
def _bucket_for(kind: str) -> str | None:
    if kind == "operation_added":
        return "endpoints_added"
    if kind == "operation_removed":
        return "endpoints_removed"
    if kind in _SCHEMA_KINDS:
        return "schemas_changed"
    if kind in _PARAMS_ADDED_KINDS:
        return "params_added"
    if kind == "parameter_removed":
        return "params_removed"
    if kind in _PARAMS_CHANGED_KINDS:
        return "params_changed"
    if kind.startswith(_ENDPOINT_CHANGED_PREFIXES) or kind == "request_content_type_removed":
        return "endpoints_changed"
    return None


def _deprecations(spec: dict) -> tuple[str, ...]:
    marked: list[str] = []
    for (method, path), body in operations(spec).items():
        if _is_deprecated(body):
            marked.append(f"{method} {path}")
    schemas = (spec.get("components") or {}).get("schemas") or {}
    for name, body in schemas.items():
        if isinstance(body, dict) and _is_deprecated(body):
            marked.append(name)
    return tuple(sorted(marked))


def _is_deprecated(node: dict) -> bool:
    sunset = node.get("x-sunset")
    return node.get("deprecated") is True or (isinstance(sunset, str) and bool(sunset))
