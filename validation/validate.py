"""Run the whole validation suite against the skills in /home/claude/dwh-skills and write REPORT.md."""
from __future__ import annotations

import json
import os
import platform
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "scenarios"))
import common, domain1, domain2, kernel, layouts, merges, mutants, regressions, workbook  # noqa: E402

RUNS = common.RUNS


def suite(name, fn):
    log, t0 = [], time.time()
    extra = None
    try:
        extra = fn(log)
    except common.Fail as e:
        log.append(("FAIL", str(e)[:400]))
    except Exception as e:  # a crash is a failure, reported with its type
        log.append(("FAIL", f"crashed: {type(e).__name__}: {str(e)[:300]}"))
    return {"name": name, "seconds": round(time.time() - t0, 1), "log": log, "extra": extra,
            "passed": all(s == "PASS" for s, _ in log) and bool(log)}


def main():
    results = []
    results.append(suite("Kernel + intake gate suite", lambda log: kernel.run((RUNS / "kernel").resolve(), log)))
    results.append(suite("Domain 1 — Module 700 pack sample (content oracle)",
                         lambda log: domain1.run(RUNS / "d1", log) and None))
    results.append(suite("Generated code: deterministic rendering + tamper detection",
                         lambda log: kernel.generated_checks(RUNS / "d1", log)))
    results.append(suite("Domain 2 — taxi-style, synthetic data, 3 sources",
                         lambda log: domain2.run(RUNS / "d2", log, threads="4")))
    results.append(suite("Merge strategies (append / upsert / CDC / snapshot, late + out-of-order)",
                         lambda log: merges.run(RUNS / "merges", log)))
    results.append(suite("Mutation-kill matrix (V33)", lambda log: mutants.run(log)))
    results.append(suite("Independent-review regressions (C1–C3, H1–H8, M2–M8, L8, drafts, formats)",
                         lambda log: (regressions.run((RUNS / "regress").resolve(), log),
                                      regressions.gold_and_serve((RUNS / "d1").resolve(), log)) and None))

    results.append(suite("Intake workbook (analyse → draft → Excel → import, all-or-nothing)",
                         lambda log: workbook.run((RUNS / "shop").resolve(), log) and None))
    results.append(suite("Layout v2 + pipelines repository (migrate, shared kernel, one file per spec)",
                         lambda log: layouts.run((RUNS / "d1").resolve(), RUNS.resolve(), log)))

    def det(log):
        a = results[3]["extra"] or {}
        b = domain2.run(RUNS / "d2_threads1", [], threads="1")
        common.check(a.get("hashes") == b.get("hashes") and a.get("hashes_after") == b.get("hashes_after"),
                     "1 thread vs 4 threads → identical content hashes for every silver and gold table (V43)", log)
        return {"threads4": a.get("hashes_after"), "threads1": b.get("hashes_after")}
    results.append(suite("Determinism (V43)", det))

    def optimized(log):
        os.environ["PYTHONOPTIMIZE"] = "1"
        try:
            inner = []
            domain1.run(RUNS / "d1_O", inner)
            common.check(all(s == "PASS" for s, _ in inner) and len(inner) > 10,
                         f"domain 1 passes under python -O ({len(inner)} checks): no assert-based checks (V40)", log)
        finally:
            os.environ.pop("PYTHONOPTIMIZE", None)
    results.append(suite("python -O (V40)", optimized))
    suffix = "" if common.LAYOUT == "v1" else f"-layout-{common.LAYOUT}"
    (HERE / f"results{suffix}.json").write_text(json.dumps(results, indent=1, default=str))
    write_report(results)
    print("\n".join(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}  ({sum(1 for s, _ in r['log'] if s == 'PASS')}/"
                    f"{len(r['log'])}, {r['seconds']}s)" for r in results))
    return 0 if all(r["passed"] for r in results) else 1


def write_report(results):
    import duckdb
    total = sum(len(r["log"]) for r in results)
    passed = sum(1 for r in results for s, _ in r["log"] if s == "PASS")
    lines = ["# dwh skill suite — validation report", "",
             f"Run on {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} · Python {platform.python_version()} · "
             f"DuckDB {duckdb.__version__} · {platform.system()} {platform.machine()} · "
             f"project layout **{common.LAYOUT}**", "",
             f"**{passed} of {total} checks passed** across {len(results)} suites.", "",
             "| Suite | Result | Checks | Time |", "|---|---|---|---|"]
    for r in results:
        n = len(r["log"])
        p = sum(1 for s, _ in r["log"] if s == "PASS")
        lines.append(f"| {r['name']} | {'PASS' if r['passed'] else 'FAIL'} | {p}/{n} | {r['seconds']} s |")
    for r in results:
        lines += ["", f"## {r['name']}", ""]
        lines += [f"- {'✅' if s == 'PASS' else '❌'} {m}" for s, m in r["log"]]
    lines += ["", "## Not covered by this run (stated, not hidden)", "",
              "- **Windows** (cmd / PowerShell / Git Bash): the wrappers and doctor target it, but this suite ran on "
              "Linux only. Run `validate.py` on a Windows machine before relying on it there.",
              "- **Real NYC TLC files**: domain 2 uses synthetic data shaped like TLC; the real-file run is the next step.",
              "- **Scale**: largest batch ~1.9k rows; DuckDB handles the 500 MB / 50 MB targets, but timings were not measured.",
              "- **Out of v1 scope** (see dwh-init/references/limits.md): row-level security, regulated-mode controls, "
              "fiscal calendars, custom steps, cloud connectors."]
    suffix = "" if common.LAYOUT == "v1" else f"-layout-{common.LAYOUT}"
    (HERE / f"REPORT{suffix}.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
