# False-Sharing Detector + Fix-Up (Trace-Driven Simulator)

Python simulator that models a MESI-like coherence protocol, flags false sharing with a lightweight heuristic, and optionally suppresses invalidations for suspect lines to approximate padding/sub-blocking benefits.

## Files
- `sim.py`: main simulator with detector and fix-up toggle.
- `traces/`: sample traces (false sharing and padded controls).
- `plot_results.py`: utility to plot IPKI and IPC proxy from simulator JSON outputs.

## Usage
Run the simulator on a trace (addresses can be hex/dec):
```bash
python3 sim.py traces/producer_consumer.trace
python3 sim.py traces/producer_consumer.trace --false-sharing-fix --log out.csv --json out.json
```

Plot baseline vs. fix-up stats (use `--json` outputs from above):
```bash
MPLCONFIGDIR=./.matplotlib MPLBACKEND=Agg \
python3 plot_results.py --baseline out_base.json --fix out_fix.json --labels workload --out ipki_ipc.png
```

Live demo (static frontend consuming the JSON outputs):
- https://suvalavala.github.io/cse220-project/ (select workloads, toggle fix-up, view IPKI/IPC bars and raw stats)

## Input format
- Trace file: one access per line as `core_id R/W address` (address may be hex or decimal).
- Examples: see `traces/producer_consumer.trace`, `traces/histogram_false_sharing.trace`, and padded controls.

## Output
- Stdout JSON summary from `sim.py`: fields include `instructions`, `hits`, `misses`, `invalidations`, `avoided_invalidations` (if fix-up), `ipki` (invalidations per K instructions), and `ipc_proxy` (instr per simulated cycle).
- Optional: `--json <file>` writes the same summary to disk; `--log <csv>` emits suspect events (addr/core/word/confidence).
- Plots: `plot_results.py` produces a PNG comparing baseline vs. fix-up IPKI and IPC proxy.

## Notes
- Detector threshold and word size are tunable (`--fs-threshold`, `--word-bytes`).
- Generated artifacts (JSON/CSV/PNG) and auxiliary directories (`report/`, `web/`) are ignored via `.gitignore` per project request.
