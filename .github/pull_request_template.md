## What changes

<!-- one or two sentences; for a pipeline: which answers changed and who gave them -->

## Kind of change

- [ ] framework (kernel / skills / tools) — `pytest framework/tests` and `python tools/run_validation.py` pass
- [ ] pipeline answers (workbook import) — the returned workbook is in `intake/workbooks/`
- [ ] pipeline build — `./dwh generate` run; reports committed; golden values pass
- [ ] kernel upgrade of a pipeline — pin changed in `dwh-project.yaml`, rebuilt, reports committed
- [ ] docs only

## Checklist

- [ ] No raw data, `.dwh/`, salt or wrappers in the diff (the pre-commit hook checks this)
- [ ] No hand edits to `*/generated/` (CI re-renders and compares)
- [ ] Decisions someone may ask about later have a note in `governance/adr/`
- [ ] Approval and consumer release are left to a person (`./dwh approve`, `./dwh publish --target consumers`)
