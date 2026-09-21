# Dataset directory

The simulation dataset is **not** distributed with this repository — it is
several hundred megabytes of RMS time-series exports. Place it here, or point
the `BENCHMARK_DATA_DIR` environment variable at wherever you keep it.

## Expected layout

One folder per fault location, one CSV per fault duration. The CSV filename is
the fault duration expressed in the unit the codebase calls "cycles", where
**1 cycle = 10 ms**. The fault is assumed to start at t = 1.0 s, so
`compute_kpis` infers the fault window from the filename as
`1.0 s → 1.0 + cycles/100 s` (e.g. `16.csv` → 1.00–1.16 s, a 160 ms fault):

```
data/
├── Bus 01/
│   ├── 2.csv
│   ├── 4.csv
│   └── ...            # up to 20.csv
├── Bus 02/
├── ...
├── Bus 39/
├── Line 01 - 02/
│   ├── 2.csv
│   └── ...
├── Line 01 - 39/
└── ...
```

Folder names must start with `Bus ` or `Line ` — that prefix is how the loader
classifies the fault type.

## Expected CSV format

A DIgSILENT PowerFactory RMS export with a **two-row header**. The delimiter may
be either `,` or `;` (it is auto-detected), and the decimal separator must be `.`.

- One column whose second header row contains `Time` — the time axis in seconds.
- Bus voltage columns: second header row contains `u1` (voltage magnitude in pu),
  first header row is the bus name (e.g. `Bus 25`).
- Generator speed columns: second header row contains `Speed` (in pu).

Columns that match none of the above are ignored, so extra exported variables
are harmless.

## Generating the dataset

With PowerFactory installed and the IEEE 39-bus project loaded, the simulations
can be produced through the `run_simulation` / `run_custom_case` MCP tools
described in the main README.
