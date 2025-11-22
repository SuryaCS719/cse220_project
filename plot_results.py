#!/usr/bin/env python3
"""
Plot IPKI and IPC proxy for baseline vs. fix-up runs.

Usage:
  python3 plot_results.py --baseline results/fs_base.json results/prod_base.json --fix results/fs_fix.json results/prod_fix.json --labels fs prod --out ipki_ipc.png

Each JSON file should be produced by sim.py (use --json flag).
"""
import argparse
import json
import matplotlib.pyplot as plt


def load_stats(paths):
    return [json.load(open(p)) for p in paths]


def main():
    ap = argparse.ArgumentParser(description="Plot IPKI and IPC proxy for baseline vs fix-up")
    ap.add_argument("--baseline", nargs="+", required=True, help="Baseline stats JSON files")
    ap.add_argument("--fix", nargs="+", required=True, help="Fix-up stats JSON files (same order/length as baseline)")
    ap.add_argument("--labels", nargs="+", required=False, help="Labels for each workload (same length)")
    ap.add_argument("--out", default="ipki_ipc.png", help="Output image path")
    args = ap.parse_args()

    if len(args.baseline) != len(args.fix):
        raise SystemExit("baseline and fix lists must have same length")
    if args.labels and len(args.labels) != len(args.baseline):
        raise SystemExit("labels length must match baseline/fix")

    base = load_stats(args.baseline)
    fix = load_stats(args.fix)
    labels = args.labels if args.labels else [f"w{i}" for i in range(len(base))]

    ipki_base = [b.get("ipki", 0) for b in base]
    ipki_fix = [f.get("ipki", 0) for f in fix]
    ipc_base = [b.get("ipc_proxy", 0) for b in base]
    ipc_fix = [f.get("ipc_proxy", 0) for f in fix]

    x = range(len(labels))
    width = 0.35

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))

    ax1.bar([i - width / 2 for i in x], ipki_base, width, label="baseline")
    ax1.bar([i + width / 2 for i in x], ipki_fix, width, label="fix-up")
    ax1.set_ylabel("IPKI")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(labels)
    ax1.set_title("Invalidations per K Instructions")
    ax1.legend()

    ax2.bar([i - width / 2 for i in x], ipc_base, width, label="baseline")
    ax2.bar([i + width / 2 for i in x], ipc_fix, width, label="fix-up")
    ax2.set_ylabel("IPC proxy")
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(labels)
    ax2.set_title("IPC proxy")
    ax2.legend()

    fig.tight_layout()
    plt.savefig(args.out, bbox_inches="tight")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
