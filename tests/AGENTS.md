# Test changes

- Keep behavior and error checks in feature tests. Use JSON snapshots for complete documents.
- Preserve OpenAPI 3.1 validation and JSON round-trip checks in snapshot tests.
- Update snapshots only for intended output changes. Format JSON with `msgspec.json.format(api.to_json(), indent=2)` and review the fixture diff.
- Snapshot comparison ignores object key order and schema `required`/`enum` order. Preserve the order of other arrays and literal values in defaults, constants, and examples.
