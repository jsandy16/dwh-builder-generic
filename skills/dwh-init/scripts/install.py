#!/usr/bin/env python3
"""Scaffold a warehouse project and pin the dwh_core kernel into it.

    python <skill>/scripts/install.py --project <dir> [--layout v1|v2] [--shared-kernel <dir>]

* standalone (default): copies the kernel into <dir>/dwh_core (self-contained and pinned), layout v1;
* inside a pipelines repository (a parent folder has framework/dwh_core, or --shared-kernel is
  given): nothing is copied — the pipeline pins the shared kernel's version in dwh-project.yaml
  and uses layout v2 (one folder per layer, one spec file per source / entity / metric);
* creates the folder layout, .gitignore, requirements.txt and an empty manifest;
* runs the environment doctor, which writes ./dwh and dwh.cmd wrappers that call this exact
  interpreter (no python3 / make / PATH guessing on Windows).
It never overwrites specs or answers that already exist, and it never answers intake
questions — those are recorded with `dwh intake set` from what the people involved said.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KERNEL = HERE.parent / "kernel" / "dwh_core"
FOLDERS = ["config/intake", "governance", "data/raw", "artefacts/results", "dead_letter", "serving",
           "pipeline/generated", "custom", "synthetic"]
FOLDERS_V2 = ["requirements", "data/raw", "data/synthetic", "project/decisions", "intake/current", "intake/workbooks",
              "bronze/specs/sources", "bronze/decisions", "bronze/generated", "bronze/reports",
              "silver/specs/entities", "silver/decisions/readbacks", "silver/generated", "silver/reports",
              "gold/specs/metrics", "gold/decisions", "gold/generated", "gold/reports", "gold/checks",
              "serve/specs", "serve/decisions", "serve/generated", "serve/reports",
              "governance/releases", "governance/adr", "custom"]
GITIGNORE_V2 = """# dwh (layout v2): data rows, local state and machine-specific files stay out of git
.dwh/
data/raw/
intake/current/
dwh
dwh.cmd
__pycache__/
*.pyc
"""
README_V2 = """# {name}

Pipeline built with the dwh-* skills (shared kernel `dwh_core` {version}, layout v2).

| Folder | Holds |
|---|---|
| `requirements/` | what was asked: the request, the supplier's data documentation |
| `data/` | `raw/` source files (not in git), `synthetic/` small fake sample, `manifest.yaml` |
| `project/` | people and policies (+ their `decisions/`) |
| `intake/` | the agent's draft, the counts-only analysis, every workbook sent and returned |
| `bronze/ silver/ gold/ serve/` | per layer: `specs/` (one file per source / entity / metric), `decisions/` (who answered what), `generated/` (never edit), `reports/` (proofs) |
| `governance/` | approvals, releases, debt, decision records (`adr/`), lineage |

Run everything through the wrapper the doctor writes (`./dwh …` or `dwh.cmd …`):
`doctor`, `intake check all`, `build bronze|silver|gold`, `publish`, `serve`, `status`.
"""
GITIGNORE = """# dwh: local state, published snapshots and raw data stay out of git
.dwh/
serving/
dead_letter/
data/raw/
__pycache__/
*.pyc
"""
REQUIREMENTS = """duckdb>=1.1,<2
pandas>=2.0
pyarrow>=14
pyyaml>=6.0
# dashboard (dwh-serve)
streamlit>=1.30
# Excel sources only
openpyxl>=3.1
"""
README = """# {name}

Warehouse built with the dwh-* skills (kernel `dwh_core` {version}, pinned in `dwh_core/`).

Run everything through the wrapper — it calls the exact Python the doctor checked:

| Step | Git Bash / macOS / Linux | cmd / PowerShell |
|---|---|---|
| check the environment | `./dwh doctor` | `dwh.cmd doctor` |
| see what is still needed | `./dwh intake check all` | `dwh.cmd intake check all` |
| land files | `./dwh build bronze` | `dwh.cmd build bronze` |
| clean + conform | `./dwh build silver` | `dwh.cmd build silver` |
| metrics | `./dwh build gold` | `dwh.cmd build gold` |
| publish a snapshot | `./dwh publish` | `dwh.cmd publish` |
| dashboard | `./dwh serve` | `dwh.cmd serve` |
| where things stand | `./dwh status` | `dwh.cmd status` |

Specs live in `config/` and `governance/`; generated code in `pipeline/generated/` (never edit it);
proofs in `artefacts/`; rejected rows in `dead_letter/`.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="project folder (created if missing)")
    ap.add_argument("--name", help="project name for the README (the intake still asks for it)")
    ap.add_argument("--layout", choices=["v1", "v2"],
                    help="v1 = self-contained folder (default standalone); v2 = per-layer folders (default in a repo)")
    ap.add_argument("--shared-kernel", help="folder holding a shared dwh_core (e.g. <repo>/framework); "
                    "found automatically when a parent folder has framework/dwh_core")
    ap.add_argument("--upgrade", action="store_true",
                    help="replace an older pinned kernel with this one (only when the user asked; same key algorithm only)")
    args = ap.parse_args()
    root = Path(args.project).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True  # never leave caches inside the skill folder
    shared = _shared_kernel(root, args.shared_kernel)
    if shared is None and not KERNEL.exists():
        print("refused: this copy of dwh-init has no kernel/ folder and no shared framework/dwh_core was found "
              "above the project; pass --shared-kernel <folder holding dwh_core>.")
        return 2
    kernel_home = shared if shared is not None else KERNEL.parent
    sys.path.insert(0, str(kernel_home))
    from dwh_core import KEY_ALGO, VERSION  # noqa: E402
    pinned_layout = _manifest_value(root / "dwh-project.yaml", "layout") or (
        "v1" if (root / "dwh-project.yaml").exists() else "")
    layout = args.layout or pinned_layout or ("v2" if shared is not None else os.environ.get("DWH_DEFAULT_LAYOUT", "v1"))
    if pinned_layout and layout != pinned_layout:
        print(f"refused: this project uses layout {pinned_layout}; the installer does not change an existing "
              f"project's layout. Run `dwh layout migrate` to move it to v2.")
        return 2
    if shared is not None:
        return _install_shared(root, kernel_home, VERSION, KEY_ALGO, layout, args)

    dest = root / "dwh_core"
    if dest.exists():
        have = _version(dest)
        if have != VERSION:
            if not args.upgrade:
                print(f"refused: this project pins dwh_core {have}; this skill ships {VERSION}. Upgrading the kernel "
                      "is a reviewed change — rerun with --upgrade only when the user has asked for it.")
                return 2
            pinned_algo = _manifest_value(root / "dwh-project.yaml", "key_algo")
            if pinned_algo and pinned_algo != KEY_ALGO:
                print(f"refused: the project's keys use algorithm {pinned_algo}; this kernel mints {KEY_ALGO}. "
                      "An upgrade would re-mint every key — not supported in place.")
                return 2
            print(f"upgrading dwh_core {have} → {VERSION} (key algorithm {KEY_ALGO} unchanged)")
            _set_manifest_version(root / "dwh-project.yaml", VERSION)
        shutil.rmtree(dest)
    shutil.copytree(KERNEL, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    _scaffold(root, VERSION, KEY_ALGO, layout, args)
    print(f"kernel dwh_core {VERSION} pinned in {dest}")
    return _doctor_and_next(root, root, layout)


def _shared_kernel(root: Path, given: str | None) -> Path | None:
    if given:
        p = Path(given).expanduser().resolve()
        if not (p / "dwh_core" / "__init__.py").exists():
            raise SystemExit(f"--shared-kernel {p}: no dwh_core package there")
        return p
    if (root / "dwh_core").exists():   # an existing standalone project stays standalone
        return None
    for cand in [root, *root.parents]:
        if (cand / "framework" / "dwh_core" / "__init__.py").exists():
            return cand / "framework"
    return None


def _install_shared(root: Path, kernel_home: Path, version: str, key_algo: str, layout: str, args) -> int:
    manifest = root / "dwh-project.yaml"
    pinned = _manifest_value(manifest, "dwh_core_version")
    if pinned and pinned != version and not args.upgrade:
        print(f"refused: this pipeline pins dwh_core {pinned}; the shared kernel is {version}. Upgrading is a "
              "reviewed change — rerun with --upgrade only when the user has asked for it.")
        return 2
    algo = _manifest_value(manifest, "key_algo")
    if algo and algo != key_algo:
        print(f"refused: the pipeline's keys use algorithm {algo}; the shared kernel mints {key_algo}.")
        return 2
    if pinned and pinned != version:
        _set_manifest_version(manifest, version)
    _scaffold(root, version, key_algo, layout, args, shared=True)
    print(f"pipeline uses the shared kernel dwh_core {version} in {kernel_home} (layout {layout})")
    return _doctor_and_next(root, kernel_home, layout)


def _scaffold(root: Path, version: str, key_algo: str, layout: str, args, shared: bool = False) -> None:
    for f in (FOLDERS_V2 if layout == "v2" else FOLDERS):
        (root / f).mkdir(parents=True, exist_ok=True)
    _write_once(root / ".gitignore", GITIGNORE_V2 if layout == "v2" else GITIGNORE)
    if not shared:   # in a repository the packages are pinned once, next to the shared kernel
        _write_once(root / "requirements.txt", REQUIREMENTS)
    readme = README_V2 if layout == "v2" else README
    _write_once(root / "README.md", readme.format(name=args.name or root.name, version=version))
    gen = "the generated/ folders" if layout == "v2" else "pipeline/generated/"
    _write_once(root / "custom" / "README.md",
                "Logic the templates cannot express belongs here, owned by a person, never in "
                f"{gen}. (Custom steps are not executed by dwh_core yet.)\n")
    manifest = root / "dwh-project.yaml"
    if not manifest.exists():
        extra = "  layout: v2\n" if layout == "v2" else ""
        manifest.write_text(f"project:\n  dwh_core_version: \"{version}\"\n  key_algo: {key_algo}\n{extra}",
                            encoding="utf-8")
    (root / ".dwh").mkdir(exist_ok=True)
    salt = root / ".dwh" / "salt"
    if not salt.exists():
        import secrets
        salt.write_text(secrets.token_hex(16), encoding="utf-8")


def _doctor_and_next(root: Path, kernel_home: Path, layout: str) -> int:
    rc = subprocess.call([sys.executable, "-m", "dwh_core", "doctor"], cwd=root,
                         env={**_env(), "PYTHONPATH": str(kernel_home), "DWH_PROJECT": str(root)})
    draft = "intake/draft.yaml" if layout == "v2" else "config/intake/draft.yaml"
    print("\nNext: put the source files in data/raw/, then `./dwh intake analyze data/raw` (Git Bash/macOS/Linux; "
          f"`dwh.cmd …` on Windows), write {draft}, and `./dwh intake workbook` — the Excel file "
          "with every question for the user.")
    print("Back up .dwh/salt: hashed (masked) values and protected keys depend on it.")
    return 0 if rc == 0 else rc


def _manifest_value(manifest: Path, key: str) -> str:
    if not manifest.exists():
        return ""
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip('"')
    return ""


def _set_manifest_version(manifest: Path, version: str) -> None:
    if not manifest.exists():
        return
    lines = manifest.read_text(encoding="utf-8").splitlines()
    out = [(line.split("dwh_core_version:")[0] + f'dwh_core_version: "{version}"')
           if line.strip().startswith("dwh_core_version:") else line for line in lines]
    manifest.write_text("\n".join(out) + "\n", encoding="utf-8")


def _version(dest: Path) -> str:
    for line in (dest / "__init__.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("VERSION"):
            return line.split("=")[1].strip().strip('"')
    return "?"


def _write_once(path: Path, text: str) -> None:
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def _env() -> dict:
    import os
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    return env


if __name__ == "__main__":
    sys.exit(main())
