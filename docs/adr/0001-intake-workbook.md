# 0001 — Every question in one Excel intake workbook

- **Date:** 2026-10-06 · **Status:** accepted (kernel 1.1.0)

## Context

Answers were collected one by one in chat. Owners could not see the whole set, defaults were
invisible, and a half-answered intake built half a pipeline.

## Decision

After analysing the data (counts only) and the requirements, dwh-init writes one workbook with a
tab per kind of question, every answer pre-filled with a default and its reason. Import is
all-or-nothing: the answers are applied to a scratch copy and every layer's gate runs there; any
problem returns an `-issues.xlsx` and records nothing. Golden values and the rule read-back have no
default on purpose, because a default would make the check prove itself.

## Consequences

Owners answer in a familiar tool; the agent cannot slip in an unreviewed answer; keeping a ★
default is still an owner's answer and is listed by `dwh status`.
