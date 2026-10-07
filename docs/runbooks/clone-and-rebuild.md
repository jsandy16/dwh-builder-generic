# Clone the repository and rebuild a pipeline

Git holds everything except data. On a new machine:

```bash
git clone https://github.com/jsandy16/dwh-builder-generic && cd dwh-builder-generic
pip install -r framework/requirements.txt
python tools/doctor.py <name>
cd pipelines/<name>
```

`tools/doctor.py` checks this Python and writes `./dwh` (and `dwh.cmd`) for this machine. Then:

1. Copy the raw files into `data/raw/` and check them:
   `python ../../tools/data_manifest.py <name> --check` must say they match the manifest.
2. Restore `.dwh/salt` from the backup (see salt-and-secrets) if you need the same hashed ids as
   the original build. Without it a new salt is created: hashed ids differ, KPI values do not.
3. `./dwh build bronze`, `./dwh build silver`, `./dwh build gold`, `./dwh publish`, `./dwh serve`.

The gold reports you get should match the committed ones (row counts, golden values).
