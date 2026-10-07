# Documentation

| Read this | When |
|---|---|
| [guide.md](guide.md) | first — the whole life cycle in plain words: who does what, every workbook tab, the checks |
| [repository-layout.md](repository-layout.md) | where everything lives, and what git holds |
| [pipeline-contract.md](pipeline-contract.md) | what a pipeline folder must contain (checked by CI) |
| [architecture.md](architecture.md) | how the skills, the kernel and the pipelines fit together |

## Runbooks

[Add a pipeline](runbooks/add-a-pipeline.md) ·
[Add a batch](runbooks/add-a-batch.md) ·
[Approve and release](runbooks/approve-and-release.md) ·
[Upgrade a pipeline's kernel](runbooks/upgrade-the-kernel.md) ·
[Clone and rebuild](runbooks/clone-and-rebuild.md) ·
[The salt and other secrets](runbooks/salt-and-secrets.md)

## Decision records (framework)

[0001 Intake workbook](adr/0001-intake-workbook.md) ·
[0002 YAML is the record, Excel is the form](adr/0002-yaml-record-excel-form.md) ·
[0003 Layout v2 and a shared kernel](adr/0003-layout-v2-and-shared-kernel.md) ·
[0004 Raw data out of git](adr/0004-raw-data-out-of-git.md)

Pipeline-specific decisions live in each pipeline's `governance/adr/`.

## Diagram

`diagrams/dwh-lifecycle.png` — the life cycle in three lanes (you / Claude / automatic checks).
Editable in Lucid: [DWH skill life cycle — who does what](https://lucid.app/lucidchart/13824867-f915-4a29-adc1-4d8088390d23/edit).
