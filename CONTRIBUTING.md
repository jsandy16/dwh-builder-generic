# Contributing

## Branches and pull requests

- `main` is protected: every change arrives through a pull request with a green CI run.
- One pull request = one kind of change. Do not mix a framework change with a pipeline's answers.
- CODEOWNERS asks the right owner to review: specs and decisions of a pipeline go to its owners,
  `framework/` to the framework maintainers.
- Pull request titles: `framework: …`, `skills: …`, `pipeline(<name>): …`, `docs: …`.

## Changing a pipeline

Specs and answers change through the intake workbook (or `./dwh intake set … --by <person>`), never
by editing YAML by hand: hand edits to an owner's answer are detected (value hashes) and block the
build. Generated code under `<layer>/generated/` is never edited; CI fails if it differs from what
the specs render.

Commit, for every change:

- the spec files and `decisions/provenance.yaml` the import wrote;
- the returned workbook in `intake/workbooks/` (the import puts it there);
- regenerated code (`./dwh generate`) and the reports of the build you ran;
- a note in `governance/adr/` when the change is a decision someone may ask about later.

Approval is never part of a pull request made by Claude: a person runs `./dwh approve` in their own
terminal and commits `governance/approvals.log`.

## Changing the framework

1. Change `framework/dwh_core` (and the skills, if behaviour they describe changes).
2. Run `pytest framework/tests` and `python tools/run_validation.py` (both layouts).
3. Bump `VERSION` in `framework/dwh_core/__init__.py` and add a `CHANGELOG.md` entry.
4. Pipelines keep their pinned version until someone upgrades each one in its own pull request:
   set `project.dwh_core_version`, run `./dwh generate`, rebuild, commit the new reports.

Never change the key algorithm (`KEY_ALGO`) in place: it would re-mint every key.

## Releasing the skills

Tag `vX.Y.Z` on `main`. The release workflow packages `dist/*.skill` (the kernel is put into
dwh-init at packaging time) and attaches them to the GitHub release; install those in Claude.

## Never commit

Raw data, anything under `.dwh/` (warehouse, salt, dead letters, snapshots), the `dwh` / `dwh.cmd`
wrappers, credentials. The pre-commit hook (`pre-commit install`) refuses them.
