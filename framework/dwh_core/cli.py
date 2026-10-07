"""`python -m dwh_core <command>` — the only interface the dwh-* skills use."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import VERSION
from . import config as C
from .project import Project, ProjectNotFound, audit

EXIT_BLOCKED = 2      # intake/verification refused the step
EXIT_LOCKED = 75      # another run holds the lease
EXIT_ERROR = 3        # an unexpected error (not a verification failure); trace in .dwh/last_error.txt


def _parse_value(args) -> object:
    if getattr(args, "yaml", None) is not None:
        return yaml.load(args.yaml, Loader=yaml.BaseLoader)
    if getattr(args, "file", None):
        text = open(args.file, encoding="utf-8").read()
        if args.file.lower().endswith((".yaml", ".yml", ".json")):
            return yaml.load(text, Loader=yaml.BaseLoader)
        return text
    if args.value is None:
        raise SystemExit("give a value, --yaml or --file")
    return args.value


def cmd_intake(args, project: Project) -> int:
    from . import intake as I
    if args.action == "show":
        if args.skill == "all":
            from .runner import ALL
            print("\n\n".join(I.show(project, s, g) for s, g in ALL))
        else:
            print(I.show(project, args.skill, args.gate))
        return 0
    if args.action == "check":
        if args.skill == "all":
            from .runner import check_all
            ok, text = check_all(project, unattended=args.unattended)
            print(text)
            return 0 if ok else EXIT_BLOCKED
        rep = I.check(project, args.skill, args.gate, unattended=args.unattended)
        if args.json:
            print(json.dumps({"ok": rep.ok, "errors": [vars(e) for e in rep.errors],
                              "warnings": [vars(w) for w in rep.warnings],
                              "not_applicable": [vars(n) for n in rep.not_applicable]}, indent=2))
        else:
            print(rep.render())
        return 0 if rep.ok else EXIT_BLOCKED
    if args.action == "set":
        state = I.set_answer(project, args.path, _parse_value(args), by=args.by or "",
                             source=args.source, quote=args.quote or "", reason=args.reason or "",
                             drafted=args.drafted)
        print(f"recorded {args.path} ({state})")
        return 0
    if args.action == "pending":
        I.mark_pending(project, args.path, args.owner, args.due or "")
        print(f"{args.path} pending for {args.owner}")
        return 0
    if args.action == "confirm":
        I.confirm(project, args.path, args.by)
        print(f"{args.path} confirmed by {args.by}")
        return 0
    if args.action == "export":
        print(I.export_form(project, args.skill, args.role))
        return 0
    if args.action == "infer":
        cols = I.infer_schema(project, args.source, args.sample, by=args.by or project.builder)
        print(f"proposed {len(cols)} columns for sources.{args.source}.schema.columns (INFERRED — not usable yet):")
        for c, spec in cols.items():
            print(f"  {c}: {spec['type']}")
        print(f"Show this to the data engineer; after review record `dwh intake confirm "
              f"sources.{args.source}.schema.columns --by <DE id>`. Classification is still asked separately (★ GOV).")
        return 0
    if args.action == "analyze":
        from . import analyze as AN
        from . import proposal as PR
        draft, notes = PR.load_draft(project)
        if args.folder:
            found = AN.discover(project, args.folder)
            if not isinstance(draft.get("sources"), dict) or not draft.get("sources"):
                draft["sources"] = {k: {"location": v["location"], "format": v["format"]} for k, v in found.items()}
                out = dict(draft)
                if notes:
                    out["notes"] = notes
                C.dump_yaml(out, PR.draft_path(project))
                print(f"proposed {len(found)} source(s) into {PR.draft_path(project).relative_to(project.root)} "
                      "(rename, remove or regroup them there — this is a draft, not an answer):")
            else:
                print(f"found {len(found)} source shape(s); the draft already lists sources, so it was left as is:")
            for k, v in found.items():
                print(f"  {k}: {v['location']} ({v['format']}, batches seen: {', '.join(v['batches_seen']) or 'none'})")
        srcs = draft.get("sources") if isinstance(draft.get("sources"), dict) else C.get_path(project.document(), "sources") or {}
        print(AN.report(AN.run(project, srcs)))
        return 0
    if args.action == "workbook":
        from . import workbook as W
        from . import proposal as PR
        out, info = W.build(project, Path(args.out) if args.out else None, run_analysis=not args.no_analysis)
        if project.layout.version == "v2" and not args.out:   # keep what was sent, next to what comes back
            import shutil
            from .project import now_iso
            keep = project.loc("workbook_archive")
            keep.mkdir(parents=True, exist_ok=True)
            stamp = now_iso().replace(":", "").replace("-", "")[:15]
            shutil.copyfile(out, keep / f"{stamp}-{out.stem}_sent{out.suffix}")
        total = sum(v[0] for v in info["counts"].values())
        blanks = sum(v[1] for v in info["counts"].values())
        print(f"intake workbook written: {out}")
        print(f"{total} answers across {len(info['counts'])} tabs, pre-filled with defaults; "
              f"{blanks} required answers have no default (orange cells).")
        for tab, (n, req) in info["counts"].items():
            print(f"  {tab}: {n} answers" + (f", {req} to fill" if req else ""))
        # the defaults themselves must be consistent: check them exactly as an import would (records nothing)
        issues, _ = W.validate(project, W.parse(out), out)
        owner_only = [i for i in issues if i.path.endswith(("readback_confirmed", "golden_values"))
                      or i.path.startswith(("answered_by.", "people", "project.builder"))]
        issues = [i for i in issues if i not in owner_only]
        if owner_only:
            print(f"\n{len(owner_only)} answer(s) only the owner can give (no default on purpose): "
                  + ", ".join(sorted({i.path for i in owner_only}))[:400])
        if issues:
            print(f"\nDEFAULTS CHECK: {len(issues)} problem(s) if the owner kept every default — fix the draft "
                  f"({project.rel(PR.draft_path(project))}) and regenerate before sending; leave only what the owner must supply:")
            for i in issues[:50]:
                print(f"  - {i.sheet} {i.cell} `{i.path}`: {i.problem}" + (f" → {i.fix}" if i.fix else ""))
        else:
            print("\nDEFAULTS CHECK: clean — " + ("apart from the owner-only answers above, " if owner_only else "")
                  + "the workbook imports as it is if the owner keeps every default.")
        return 0
    if args.action == "import":
        from . import workbook as W
        code, text = W.import_workbook(project, args.file, dry_run=args.dry_run, out=args.out)
        print(text)
        return code
    if args.action == "readback":
        from . import silver
        res = silver.rule_readback(project, args.entity, write=True)
        print(res["text"])
        return 0
    raise SystemExit(f"unknown intake action {args.action}")


def cmd_approve(args, project: Project) -> int:
    from . import approvals as A
    if args.status:
        print(json.dumps(A.status(project), indent=2))
        return 0
    entry = A.approve(project, args.by, meaning=args.meaning, note=args.note or "")
    print(f"approved spec {entry['spec_hash'][:12]} by {entry['by']}"
          + (" (self-approved by the builder)" if entry["self_approved"] else ""))
    return 0


def cmd_build(args, project: Project) -> int:
    from . import runner
    return runner.build(project, args.layer, batch=args.batch, source=args.source,
                        unattended=args.unattended, rebuild=args.rebuild)


def cmd_publish(args, project: Project) -> int:
    from . import publish
    return publish.publish_cli(project, target=args.target)


def cmd_serve(args, project: Project) -> int:
    from . import serve
    if args.check:
        return serve.check(project)
    return serve.run(project, released=args.released)


def cmd_status(args, project: Project) -> int:
    from . import runner
    print(runner.status_text(project))
    return 0


def cmd_doctor(args, project: Project | None) -> int:
    from . import doctor
    return doctor.run(project, write=not args.no_write)


def cmd_generate(args, project: Project) -> int:
    from . import generate
    if args.verify:
        bad = generate.verify_all(project)
        for b in bad:
            print("TAMPERED:", b)
        print("all generated files intact" if not bad else f"{len(bad)} generated file(s) modified by hand")
        return 0 if not bad else EXIT_BLOCKED
    paths = generate.render_layer(project, args.layer)
    for p in paths:
        print("rendered", p.relative_to(project.root))
    return 0


def cmd_profile(args, project: Project) -> int:
    from . import profile
    profile.run(project)
    print(f"profile written: {project.rel(project.profile_file)} and {project.rel(project.loc('bronze_profile'))}")
    return 0


def cmd_synth(args, project: Project) -> int:
    from . import synthetic
    return synthetic.score(project) if args.score else synthetic.run(project)


def cmd_reset(args, project: Project) -> int:
    """Clear built data (warehouse, ledgers, snapshots, dead letters, results); keep every spec,
    answer, approval and the salt. Used to switch from synthetic to real data or reset a demo."""
    import shutil
    from .runtime import Lease
    if not (args.data and args.yes):
        print("refused: `dwh reset --data --yes` deletes the warehouse, ledgers, snapshots and dead letters "
              "(specs, answers and approvals are kept). Ask the user first.")
        return EXIT_BLOCKED
    with Lease(project, "dwh-reset"):
        for rel in (".dwh/warehouse.duckdb", ".dwh/warehouse.duckdb.wal", ".dwh/profile.json", ".dwh/synthetic.json"):
            project.p(rel).unlink(missing_ok=True)
        shutil.rmtree(project.p(".dwh/ledger"), ignore_errors=True)
        for name in ("serving", "dead_letter"):
            shutil.rmtree(project.loc(name), ignore_errors=True)
        rb = project.loc("readback_state")   # read-back counts belong to the old data; the .md evidence stays
        for f in rb.glob("*.json") if rb.exists() else []:
            f.unlink()
        for name in ("bronze-verify", "silver-verify", "gold-verify", "serve-check", "synthetic-score"):
            project.layout.report(name, "json").unlink(missing_ok=True)   # verification results
        project.loc("serving").mkdir(parents=True, exist_ok=True)
        project.loc("dead_letter").mkdir(parents=True, exist_ok=True)
    audit(project, "reset.data")
    print("warehouse data cleared; specs, answers and approvals kept. Rebuild from bronze.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="dwh", description=f"dwh_core {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    it = sub.add_parser("intake", help="ask, record and check inputs")
    isub = it.add_subparsers(dest="action", required=True)
    s = isub.add_parser("show"); s.add_argument("skill", help="project|bronze|silver|gold|serve|synthetic|all")
    s.add_argument("--gate", default="A", choices=["A", "B"])
    s = isub.add_parser("check"); s.add_argument("skill", help="project|bronze|silver|gold|serve|synthetic|all")
    s.add_argument("--gate", default="A", choices=["A", "B"])
    s.add_argument("--unattended", action="store_true"); s.add_argument("--json", action="store_true")
    s = isub.add_parser("set"); s.add_argument("path"); s.add_argument("value", nargs="?")
    s.add_argument("--yaml"); s.add_argument("--file"); s.add_argument("--by")
    s.add_argument("--source", default="chat", choices=["chat", "file", "form"])
    s.add_argument("--quote"); s.add_argument("--reason")
    s.add_argument("--drafted", action="store_true",
                   help="a value the assistant chose that the person did not state: blocks the gate until confirmed")
    s = isub.add_parser("pending"); s.add_argument("path"); s.add_argument("--owner", required=True); s.add_argument("--due")
    s = isub.add_parser("confirm"); s.add_argument("path"); s.add_argument("--by", required=True)
    s = isub.add_parser("export"); s.add_argument("skill"); s.add_argument("--role", required=True)
    s = isub.add_parser("readback"); s.add_argument("entity")
    s = isub.add_parser("analyze", help="find sources in a folder and measure them (counts only, no values)")
    s.add_argument("folder", nargs="?")
    s = isub.add_parser("workbook", help="write the Excel intake workbook: every question, defaults pre-filled")
    s.add_argument("--out"); s.add_argument("--no-analysis", action="store_true")
    s = isub.add_parser("import", help="read a filled intake workbook back: validate everything, then record")
    s.add_argument("file"); s.add_argument("--dry-run", action="store_true"); s.add_argument("--out")
    s = isub.add_parser("infer", help="propose a source schema from a sample file (must be confirmed)")
    s.add_argument("source"); s.add_argument("--sample", required=True); s.add_argument("--by")

    s = sub.add_parser("approve", help="human approval (interactive terminal only)")
    s.add_argument("--by"); s.add_argument("--meaning", default="approve", choices=["approve", "review"])
    s.add_argument("--note"); s.add_argument("--status", action="store_true")

    s = sub.add_parser("build", help="run a layer (refuses until its intake gate passes)")
    s.add_argument("layer", choices=["bronze", "silver", "gold"]); s.add_argument("--batch")
    s.add_argument("--source"); s.add_argument("--unattended", action="store_true")
    s.add_argument("--rebuild", action="store_true", help="silver: replay every entity from all bronze history")

    s = sub.add_parser("profile", help="(re)profile bronze")
    s = sub.add_parser("publish"); s.add_argument("--target", default="local", choices=["local", "consumers"])
    s = sub.add_parser("serve"); s.add_argument("--check", action="store_true")
    s.add_argument("--released", action="store_true", help="serve the snapshot released to consumers")
    s = sub.add_parser("status")
    s = sub.add_parser("doctor"); s.add_argument("--no-write", action="store_true")
    s = sub.add_parser("generate"); s.add_argument("layer", nargs="?", default="all")
    s.add_argument("--verify", action="store_true")
    s = sub.add_parser("reset", help="clear built data, keep specs and answers")
    s.add_argument("--data", action="store_true"); s.add_argument("--yes", action="store_true")
    s = sub.add_parser("layout", help="show where files live, or migrate a project to layout v2")
    s.add_argument("action", choices=["show", "migrate"]); s.add_argument("--to", default="v2", choices=["v2"])
    s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("synth", help="generate synthetic source files (dwh-synthetic-source)")
    s.add_argument("--score", action="store_true", help="score silver against the planted-truth ledger (V21)")
    return ap


def cmd_layout(args, project: Project) -> int:
    from . import layout
    return layout.cli(project, args.action, args.to, args.dry_run)


def pin_problem(project: Project) -> str:
    """The kernel running must be the one the pipeline pins (a shared kernel can move on without it)."""
    from . import KEY_ALGO
    m = project.manifest
    algo = str(m.get("key_algo") or "").strip()
    if algo and algo != KEY_ALGO:
        return (f"this pipeline's keys use algorithm {algo}; this kernel mints {KEY_ALGO}. "
                "Re-minting every key is not supported in place.")
    pinned = str(m.get("dwh_core_version") or "").strip()
    if pinned and pinned != VERSION:
        return (f"this pipeline pins dwh_core {pinned}; the kernel on the path is {VERSION}. Upgrading is a "
                f"reviewed change: set project.dwh_core_version to \"{VERSION}\" in dwh-project.yaml in its own "
                "change, then `dwh generate` and rebuild (`dwh layout migrate` does it when moving to layout v2).")
    return ""



HANDLERS = {"intake": cmd_intake, "approve": cmd_approve, "build": cmd_build, "publish": cmd_publish,
            "serve": cmd_serve, "status": cmd_status, "doctor": cmd_doctor, "generate": cmd_generate,
            "profile": cmd_profile, "synth": cmd_synth, "reset": cmd_reset, "layout": cmd_layout}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    from .project import LayoutError
    try:
        project = Project()
    except ProjectNotFound as e:
        if args.cmd == "doctor":
            return cmd_doctor(args, None)
        print(f"error: {e}", file=sys.stderr)
        return 1
    except LayoutError as e:   # e.g. an unknown project.layout: explained, never a traceback
        if args.cmd == "doctor":
            cmd_doctor(args, None)
        print(f"refused: {e}", file=sys.stderr)
        return EXIT_BLOCKED
    if args.cmd not in ("doctor", "status", "layout"):
        try:
            problem = pin_problem(project)
        except Exception:  # an unreadable manifest is reported by the command itself
            problem = ""
        if problem:
            print(f"refused: {problem}", file=sys.stderr)
            return EXIT_BLOCKED
    try:
        return HANDLERS[args.cmd](args, project)
    except BrokenPipeError:  # output piped into head/less that closed early: not an error
        return 0
    except Exception as e:  # every refusal is explained, never a bare traceback
        from .approvals import ApprovalError
        from .generate import TamperedFile
        from .intake import IntakeError
        from .runtime import LockHeld, VerificationError
        from .silver import NoBronzeData, SpecError
        from .workbook import WorkbookError
        from .analyze import AnalyzeError
        if isinstance(e, LockHeld):
            print(f"locked: {e}", file=sys.stderr)
            return EXIT_LOCKED
        if isinstance(e, (IntakeError, ApprovalError, VerificationError, TamperedFile, NoBronzeData, SpecError,
                          WorkbookError, AnalyzeError, LayoutError)):
            audit(project, f"{args.cmd}.refused", reason=str(e)[:400])
            print(f"refused: {e}", file=sys.stderr)
            return EXIT_BLOCKED
        import traceback
        (project.state / "last_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        audit(project, f"{args.cmd}.error", error=f"{type(e).__name__}: {str(e)[:300]}")
        print(f"error: {type(e).__name__}: {str(e)[:500]}\n(full trace in .dwh/last_error.txt)", file=sys.stderr)
        return EXIT_ERROR
