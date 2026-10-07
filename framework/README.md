# framework — the dwh_core kernel

`dwh_core` is the one program every pipeline runs. The skills tell Claude *what to ask and when*;
the kernel decides *whether anything may build* and does the building, deterministically, from the
specs.

| Module | Job |
|---|---|
| `project.py` | where files live (layout v1 / v2), loading and saving specs and provenance |
| `layout.py` | `dwh layout show` / `dwh layout migrate` |
| `catalogue.py` + `catalogues/*.yaml` | every question each layer asks: owner, level (M / M★ / C / O), type, allowed answers |
| `intake.py`, `validators.py` | recording answers with provenance; the gates (`dwh intake check`) |
| `analyze.py`, `proposal.py`, `workbook.py` | counts-only analysis, default answers, the Excel intake workbook and its all-or-nothing import |
| `bronze.py`, `profile.py` | landing files as received behind file gates; counts-only profile |
| `silver.py` | typing, conforming, rules, dead letters, merges, row law |
| `gold.py` | KPIs from metric cards, golden values, reconciliation |
| `publish.py`, `serve.py` | snapshots, release gate, the Streamlit dashboard and its headless check |
| `approvals.py` | hash-chained, human-only approvals |
| `generate.py` | rendering code from specs with tamper-evident headers |
| `runtime.py`, `runner.py` | ledgers, leases, verification results, `dwh build` / `dwh status` |
| `doctor.py` | environment check; writes the `dwh` / `dwh.cmd` wrappers |

Run it through a pipeline's wrapper (`./dwh …`) or directly:

```bash
PYTHONPATH=framework DWH_PROJECT=pipelines/olist python -m dwh_core status
```

Tests: `pytest framework/tests` (unit) and `python tools/run_validation.py` (end to end, both
layouts). Version: `VERSION` in `dwh_core/__init__.py`; see `CHANGELOG.md` and CONTRIBUTING.md for
how a version change reaches the pipelines.
