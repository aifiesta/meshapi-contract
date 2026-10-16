# meshapi-contract

Classifies breaking changes between two snapshots of a public OpenAPI contract.
Pure Python, standard library only, no runtime dependencies.

## What it does

- `public_subset(spec)` projects a full OpenAPI document down to the public surface:
  `/v1/` paths, without operations flagged internal, with only the schemas those
  operations can reach. Prose keys (descriptions, examples, summaries) are dropped so
  snapshots diff on contract changes alone.
- `classify_changes(before, after)` returns every difference as a `Change(kind, detail,
  breaking)`. Removals, type changes, newly required inputs, tightened constraints and
  changed defaults are breaking. Additions and relaxations are not.
- `published_a_new_version(before, after)` reports whether `after` introduces a dated
  API version that `before` did not, which is the usual reason to accept a breaking change.
- `render(spec)` produces the canonical JSON text for a committed baseline file.
- `operations(spec)` indexes a document's operations by `(METHOD, path)`.

## Usage

```python
import json
from meshapi_contract import classify_changes, public_subset, render

with open("baseline.json") as f:
    before = json.load(f)
with open("generated.json") as f:
    after = public_subset(json.load(f))

for change in classify_changes(before, after):
    print(change)
```

## Contract gate

SDK CI runs one shared check against a published `openapi.json` and the SDK's
actual-surface JSON:

```sh
python -m meshapi_contract.gate --spec openapi.json --actual surface.json \
    --spec-version "$(cat .meshapi-spec-version)"
```

| Exit | Meaning |
| --- | --- |
| 0 | SDK covers every spec field and parameter |
| 1 | Drift: missing members are listed |
| 2 | Usage error (argparse) |
| 3 | Surface file built against a different spec or surface schema version |
| 4 | Operational error: unreadable or malformed input, empty spec surface, or no `schema_version` in the surface file |

## Development

```sh
uv sync --extra dev
uv run pytest -q
```

## Design notes

- Schema `$ref`s are compared by name and not resolved. A field removed from a shared
  schema is reported once, not once per operation that uses it.
- Ambiguous changes are reported as breaking so a reviewer decides. The classifier does
  not try to be clever about widened types.
