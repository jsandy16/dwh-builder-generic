#!/usr/bin/env python3
"""The dwh agent: Claude in your terminal, building one pipeline with the dwh framework.

    python tools/dwh_agent.py <pipeline>                # work on pipelines/<pipeline>/
    python tools/dwh_agent.py <pipeline> --check        # where it stands and what the agent would do next (no AI)

It drafts every answer, writes the intake workbook, runs the builds, explains the results and
commits locally. It stops whenever a decision belongs to a person: owners answer only in the
workbook; approving, releasing and pushing stay with people. docs/agent.md explains its role and
rules; tools/dwhagent/policy.py enforces them.

Needs: `pip install -r tools/dwhagent/requirements.txt` and an Anthropic API key in ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from dwhagent import state as S  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pipeline", help="name of the folder under pipelines/")
    ap.add_argument("--check", action="store_true", help="show the stage and the next step, without the AI")
    ap.add_argument("--model", help="Claude model id or alias (default: the SDK's default)")
    ap.add_argument("--max-turns", type=int, default=80, help="maximum agent turns per step (default 80)")
    ap.add_argument("--max-budget-usd", type=float, default=5.0, help="spending cap per session (default 5)")
    ap.add_argument("--ask", help="start with this request before the stage task")
    args = ap.parse_args()
    pipeline = REPO / "pipelines" / args.pipeline
    if not (pipeline / "dwh-project.yaml").exists():
        print(f"no pipeline pipelines/{args.pipeline}/ — create it with `python tools/new_pipeline.py {args.pipeline}`")
        return 2
    if not (pipeline / ("dwh.cmd" if os.name == "nt" else "dwh")).exists():
        print(f"pipelines/{args.pipeline}/ has no ./dwh command on this computer yet: run "
              f"`python tools/doctor.py {args.pipeline}` first")
        return 2
    st = S.detect(REPO, pipeline)
    if args.check:
        from dwhagent.session import STAGE_TEXT
        print(f"pipelines/{args.pipeline}: stage {st.stage} — {STAGE_TEXT[st.stage]} ({st.why})")
        for k, v in st.facts.items():
            print(f"  {k}: {v}")
        return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY (an Anthropic API key: https://console.anthropic.com) — the agent uses the API.")
        return 2
    try:
        from dwhagent import session
    except ImportError as e:
        print(f"missing package ({e.name}): pip install -r tools/dwhagent/requirements.txt")
        return 2
    try:
        return asyncio.run(session.run(REPO, args.pipeline, args.model, args.max_turns, args.max_budget_usd,
                                       args.ask))
    except KeyboardInterrupt:
        print("\nstopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
