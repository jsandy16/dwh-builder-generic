# Repository layout

```
dwh-builder-generic/
├── README.md · CHANGELOG.md · CONTRIBUTING.md
├── .gitignore · .gitattributes · .editorconfig · .pre-commit-config.yaml · pyproject.toml
├── .github/
│   ├── CODEOWNERS                 path → reviewer, per role (DE / PO / SME / GOV)
│   ├── pull_request_template.md
│   └── workflows/
│       ├── framework.yml          lint, unit tests, validation suite on layouts v1 and v2
│       ├── pipelines.yml          every pipeline: contract, gates, generated code = specs
│       └── release.yml            tag vX.Y.Z → .skill packages on a GitHub release
├── framework/
│   ├── dwh_core/                  the kernel — one copy, versioned (VERSION in __init__.py)
│   │   └── catalogues/            every question each layer asks
│   ├── tests/                     unit tests
│   ├── pyproject.toml · requirements.txt · README.md
├── skills/                        the six skills (instructions; the kernel is added when packaged)
│   ├── dwh-init/ · dwh-bronze/ · dwh-silver/ · dwh-gold/ · dwh-serve/ · dwh-synthetic-source/
├── validation/                    end-to-end suite + its latest reports (REPORT.md, REPORT-layout-v2.md)
├── templates/pipeline/            the skeleton every new pipeline starts from
├── tools/                         new_pipeline · doctor · package_skills · run_validation · check_layout ·
│                                  check_pipelines · data_manifest · guard_commit
├── docs/                          guide · architecture · this page · pipeline contract ·
│   ├── diagrams/ · runbooks/ · adr/
└── pipelines/
    ├── README.md                  every pipeline, its owners and status
    └── olist/                     one folder per pipeline ↓
```

## One pipeline

```
pipelines/<name>/
├── README.md                      purpose, owners, status, how to rebuild
├── dwh-project.yaml               name, profile, builder, layout: v2, kernel pin, key algorithm
├── requirements/                  what was asked — input, never written by a build
│   ├── request.md
│   ├── source-README.md           the supplier's documentation
│   └── reference/
├── data/
│   ├── manifest.yaml              committed: every raw file, sha256, rows
│   ├── raw/                       NOT in git: batch_01/, batch_02/ …
│   └── synthetic/                 synthetic spec + planted truth (optional)
├── project/
│   ├── people.yaml                who holds DE / PO / SME / GOV
│   ├── policies.yaml              compliance, egress, time zone, calendar, money
│   └── decisions/provenance.yaml  who answered those, from which workbook cell
├── intake/
│   ├── draft.yaml                 Claude's proposals, with a reason per answer
│   ├── analysis.json              counts-only measurements
│   ├── current/                   NOT in git: the workbook being filled right now
│   └── workbooks/                 every workbook sent (_sent), returned, refused (-issues), date-stamped
├── bronze/
│   ├── specs/sources/<source>.yaml        one file per source (location, format, schema, classification)
│   ├── decisions/provenance.yaml
│   ├── generated/
│   └── reports/                   file gates, profile, schema drift
├── silver/
│   ├── specs/entities/<entity>.yaml       one file per entity (mapping, keys, merge, rules, lookups)
│   ├── decisions/
│   │   ├── provenance.yaml
│   │   └── readbacks/             the rule read-back each owner confirmed
│   ├── generated/
│   └── reports/                   row law, synthetic score
├── gold/
│   ├── specs/metrics/<metric>.yaml        one file per metric card (golden values included)
│   ├── decisions/provenance.yaml
│   ├── generated/
│   ├── reports/                   golden values, reconciliation, metric cards
│   └── checks/                    independent re-derivations of the golden values
├── serve/
│   ├── specs/serve.yaml           the dashboard
│   ├── decisions/provenance.yaml
│   ├── generated/                 the Streamlit app
│   └── reports/                   dashboard check + screenshot
├── governance/
│   ├── approvals.log              hash-chained, written only by `./dwh approve` (a person)
│   ├── releases/<snapshot>.json   every publish: tables, rows, hashes, approval state
│   ├── debt.md · lineage.md · lineage.yaml
│   └── adr/                       decision records
├── custom/                        logic the templates cannot express (not executed yet)
└── .dwh/                          NOT in git: warehouse, ledgers, landed files, dead letters, snapshots, salt
```

## Rules of thumb

- **YAML is the record, Excel is the form.** People answer in the workbook; the import writes the
  YAML and its provenance. Reviews read the YAML diff. See [ADR 0002](adr/0002-yaml-record-excel-form.md).
- **Nothing with data rows is committed.** Specs, decisions, code and counts are; rows are not.
- **Generated code is committed but never edited.** It makes pull requests show what will run; CI
  proves it matches the specs.
- **One kind of change per pull request** (framework vs. a pipeline's answers vs. a kernel upgrade).
