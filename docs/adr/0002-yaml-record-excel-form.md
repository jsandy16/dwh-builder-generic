# 0002 — YAML is the record, Excel is the form

- **Date:** 2026-10-07 · **Status:** accepted

## Context

People answer in Excel. The question was whether the workbook itself should be the stored spec.

## Decision

The workbook is the form; YAML spec files (plus provenance) are the record the kernel builds from.
`dwh intake workbook` renders YAML → Excel; `dwh intake import` turns Excel → YAML. Every workbook
sent, returned or refused is kept in `intake/workbooks/` as evidence, and each provenance entry
names its workbook file, sha256 and cell.

## Why

- Git can diff, review and merge text; an `.xlsx` is a zipped binary ("binary file changed").
- Two branches changing different KPIs merge automatically as YAML; two workbooks cannot be merged.
- Import strips Excel's ambiguity once (`01` → `1`, dates as serial numbers, stray spaces); builds
  read text with one meaning.
- `git blame` on a spec line shows when and in which pull request it changed.
- The draft, `dwh intake set` and migrations all write the same format.

## Consequences

People never need to open YAML. Reviewers read the YAML diff in the pull request. Hand edits to
YAML are detected through value hashes and block the build.
