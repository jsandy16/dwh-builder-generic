"""dwh_core — the execution kernel behind the dwh-* skills.

Every skill in the suite drives this package through `python -m dwh_core <command>`.
The model edits specs (YAML; where they live depends on the project layout, see project.py);
it never writes runtime SQL or Python.
All runtime code is rendered deterministically from the templates in this package.
"""

VERSION = "1.2.0"
KEY_ALGO = "v1"

# Identities that may never be recorded as the author of a human-owned (M*) answer
# or an approval. The agent drives the CLI; it is not a stakeholder.
AGENT_IDS = {"agent", "claude", "assistant", "ai", "bot", "system", "auto", "default"}
