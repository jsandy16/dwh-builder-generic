# Validation suite

End-to-end proofs against the skills exactly as they ship: kernel + intake-gate suite, the Module
700 pack sample with a content oracle, a taxi-style 3-source warehouse on synthetic data with an
independent pandas oracle, all five merge strategies, a 19-mutant kill matrix, regressions for every
independent-review finding, the Excel intake workbook flow (analyse → draft → workbook → import,
all-or-nothing), layout v2 and the pipelines repository (migration, shared kernel, one file per
spec), determinism (1 vs 4 threads) and a `python -O` run.

The whole suite runs once per project layout: `REPORT.md` (layout v1) and `REPORT-layout-v2.md`.

## Run it

From the repository root:

```bash
pip install -r framework/requirements.txt
python tools/run_validation.py               # both layouts, ~20 minutes
python tools/run_validation.py --layout v2   # one layout
```

`run_validation.py` packages the skills (the kernel goes into dwh-init, as in a release), runs the
scratch projects in a temporary folder outside the repository, and writes the reports here. To run
`validate.py` directly, set `DWH_SKILLS` to a packaged skills folder (`python tools/package_skills.py`
writes `dist/skills/`), `DWH_RUNS` to a scratch folder outside the repository, and optionally
`DWH_TEST_LAYOUT=v2`.

The headless dashboard screenshot needs Playwright; without it that one step is skipped, not failed.
CI (`.github/workflows/framework.yml`) runs both layouts on every framework change.
