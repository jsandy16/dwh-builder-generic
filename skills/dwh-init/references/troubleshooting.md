# Troubleshooting

## `python` / `python3` "was not found; run without arguments to install from the Microsoft Store"
That is the Windows App Execution Alias stub, not Python. Install Python from python.org (tick
"Add python.exe to PATH"), then turn off Settings → Apps → Advanced app settings → App execution
aliases for python.exe and python3.exe. Re-run `install.py` with the real interpreter (e.g.
`py -3 install.py …`). From then on use `dwh.cmd`, which calls that interpreter by absolute path.

## `make: command not found`, `streamlit: command not found`
Not needed. Every step is a `dwh` command; the dashboard runs with `dwh serve`, which starts
Streamlit through the checked interpreter.

## Doctor FAIL on a package
Install into the interpreter the doctor printed: `"<that path>" -m pip install -r requirements.txt`.
Streamlit is only needed for the dashboard; openpyxl only for Excel sources.

## `locked: … holds the warehouse`
Another build is running (exit code 75). Wait for it. Never delete `.dwh/lock.json` or the
DuckDB `.wal` file: a lease left by a crashed process is detected and recovered automatically.

## `refused: … was edited by hand`
Someone changed a generated file (`pipeline/generated/`, or `<layer>/generated/` in layout v2). Restore it with `dwh generate` after moving
any needed logic into `custom/` and describing it to the owner — generated files are never edited.

## Encoding problems (accents, Hindi, CJK in data)
The wrappers set `PYTHONUTF8=1`. Declare the source encoding in the bronze intake
(`csv.encoding`); a UTF-8 byte-order mark is handled.
