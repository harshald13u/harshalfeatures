# FII / FPI Historical Flows — monthly auto-updater

`update_fii_flows.py` keeps the tool current:

1. Reads the embedded `const D = {...}` from `../index.html`.
2. Fetches the latest monthly FPI net figures (Equity + Total, Rs cr) from NSDL.
3. Appends new months, re-derives the current calendar-year & financial-year
   rows from the monthly sums, and extends the FY cumulative chain (tail only —
   historical rows are never rewritten).
4. Writes back `index.html`, `fii-flows-data.json` and regenerates
   `FII_FPI_Historical_Data_India.xlsx`.

**Fail-safe:** strict validation gates; on any parse failure or implausible
number it exits non-zero and writes nothing — an unattended run can never
commit bad data.

```
python3 update_fii_flows.py                 # normal run
python3 update_fii_flows.py --dry-run        # parse+validate, write nothing
python3 update_fii_flows.py --from-csv f.csv # update from a CSV (cols: month, equity, total)
```

The monthly schedule lives in `update-fii-flows.workflow.yml` — copy it to
`.github/workflows/update-fii-flows.yml` to activate (see top of that file).
