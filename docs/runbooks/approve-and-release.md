# Approve and release

Only a person can do this, in their own terminal. Claude and CI never approve.

1. Check: `./dwh status` — every gate PASS, gold verified, the ★ defaults you kept listed.
   In the `governed` profile no ★ may be pending and the approver must not be the builder.
2. Approve: `./dwh approve --by <your id>` and type your id when asked. The approval binds the hash
   of every spec and answer; any later change makes it stale.
3. Release: `./dwh publish --target consumers`. The "unreleased" banner disappears.
4. Commit `governance/approvals.log` and the new `governance/releases/<snapshot>.json` in a pull
   request titled `pipeline(<name>): release <snapshot>`.

Regulated data (`policies.compliance` other than `none`) cannot be released to consumers yet.
