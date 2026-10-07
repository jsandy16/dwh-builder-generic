# Add a batch

1. Put the new files next to the others with the same naming (`data/raw/batch_03/…`).
2. `python tools/data_manifest.py <name>` — records the new files (commit `data/manifest.yaml`).
3. `./dwh build bronze` — lands only what is new; a batch with the same content is skipped; a file
   that breaks the agreed layout is rejected whole (`./dwh status` shows why).
4. `./dwh build silver` then `./dwh build gold`.
5. If a check fails, nothing from that batch is committed in that layer. Claude explains it and
   proposes a fix in a short workbook round; the owner decides (example: Olist ADR 0001).
6. `./dwh publish` and commit the reports, the release record and any new decision record.

A **corrected** batch is re-delivered under the same batch name. What happens is the source's
`redelivery_policy` answer: `replace` (the old version is superseded and what depends on it is
rebuilt) or `reject` (refused with an alert).
