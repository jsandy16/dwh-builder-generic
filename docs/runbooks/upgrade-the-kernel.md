# Upgrade a pipeline to a new kernel version

The framework can move ahead of a pipeline; the kernel refuses to run a pipeline pinned to another
version ("this pipeline pins dwh_core X"). Upgrade one pipeline per pull request:

1. Read `CHANGELOG.md` for what changed between the versions.
2. In `pipelines/<name>/dwh-project.yaml` set `dwh_core_version` to the framework's `VERSION`
   (never change `key_algo`).
3. `./dwh generate`, then rebuild: `./dwh build silver --rebuild` and `./dwh build gold`.
4. Compare: gold row counts and golden values must be unchanged unless the changelog says why.
5. Commit the pin, regenerated code and reports. Approval is stale after a pin change — the
   owner approves again (runbook: approve-and-release).

A pipeline still on layout v1 is moved with `./dwh layout migrate`, which also sets the pin.
