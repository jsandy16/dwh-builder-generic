# Add a pipeline

1. `python tools/new_pipeline.py <name> --title "Readable title"` (lower-case name, hyphens allowed).
2. Write `pipelines/<name>/requirements/request.md`; put the supplier's documentation in
   `requirements/` too.
3. Put the files in `pipelines/<name>/data/raw/` (never committed) and run
   `python tools/data_manifest.py <name>`.
4. Ask Claude: *"Set up the warehouse for pipelines/<name>."* dwh-init measures the data (counts
   only), drafts every answer and sends the intake workbook; it lands in `intake/current/` and a
   `_sent` copy in `intake/workbooks/`.
5. Answer it and give it back. The import records the answers (or returns an `-issues.xlsx`).
6. Open a pull request `pipeline(<name>): intake`. CI checks the folder contract and the gates.
7. Continue with bronze → after-first-load round → silver → gold → serve, one pull request per
   round; approval and release stay with a person.
