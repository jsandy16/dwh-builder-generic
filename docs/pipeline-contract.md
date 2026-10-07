# Pipeline contract

A pipeline is any folder `pipelines/<name>/` containing `dwh-project.yaml`. Nothing else in the
repository lists pipelines: CI finds them by that file. `tools/check_layout.py` enforces this
contract locally (pre-commit) and in CI:

| ID | Rule | Fix |
|---|---|---|
| P1 | `dwh-project.yaml` says `layout: v2` and pins the framework's kernel version and key algorithm | `./dwh layout migrate`; upgrade the pin in its own pull request |
| P2 | `README.md`, `requirements/` (with at least one file) and `data/manifest.yaml` exist | write `requirements/request.md`; `python tools/data_manifest.py <name>` |
| P3 | each file in `bronze/specs/sources/`, `silver/specs/entities/`, `gold/specs/metrics/` has exactly one top-level key, equal to its file name | rename the file or the key |
| P4 | no layout-v1 folders (`config/`, `artefacts/`, `pipeline/`, `serving/`, `dead_letter/`) | `./dwh layout migrate` |
| P5 | nothing under `data/raw/`, `.dwh/`, `intake/current/`, no `dwh`/`dwh.cmd`, no kernel copy is tracked; no file over 5 MB | `git rm --cached …` |
| P6 | workbooks only in `intake/workbooks/`; `.csv/.parquet/.duckdb` only in `data/synthetic/` or `gold/checks/` | move the file, or keep it out of git |

`tools/check_pipelines.py` adds two checks that need the kernel:

- **Gates** — `dwh intake check all`. A pipeline still waiting for answers is reported, not failed.
- **Generated code = specs** — the code is re-rendered in a scratch copy and compared byte for byte
  with what is committed. A hand edit, or specs changed without `./dwh generate`, fails the build.

## Adding a pipeline

```bash
python tools/new_pipeline.py <name>          # copies templates/pipeline, pins the kernel
```

Then the request in `requirements/request.md`, the files in `data/raw/`, and ask Claude to set up
the warehouse for `pipelines/<name>`. Commit the folder (the ignores keep data out). No framework
file changes.

## Removing a pipeline

Delete the folder in a pull request. Its published snapshots and warehouse live only in the
machines that built them (`.dwh/`), so archive those first if they are needed.
