# Pipelines

One folder per warehouse. CI finds every `*/dwh-project.yaml` here — adding a pipeline needs no other
change (`python tools/new_pipeline.py <name>`; contract: `docs/pipeline-contract.md`).

| Pipeline | What | Owners | Kernel | State |
|---|---|---|---|---|
| [olist](olist/) | Brazilian e-commerce orders, 6 daily KPIs | sandeep (DE, PO, SME, GOV) | 1.2.0 | built and verified on batches 01–02; awaiting approval |
