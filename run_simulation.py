"""Run the three policies and export a summary table and figure."""
import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from simulator import (
    NO_RETRY, SAFE_RETRY, NO_IDEMPOTENCY, make_sample_payments,
    run_policy, summarize,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    payments = make_sample_payments()
    summaries = []
    for policy in (NO_RETRY, SAFE_RETRY, NO_IDEMPOTENCY):
        frame, _ = run_policy(payments, policy)
        summaries.append(summarize(frame, policy.name))
    results = pd.DataFrame(summaries)
    results.to_csv(args.output / "summary.csv", index=False)

    labels = ["One attempt", "Retries with\nidempotency", "Retries without\nidempotency"]
    colors = ["#64748b", "#0f766e", "#c2410c"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.8))
    for ax, metric, title in zip(
        axes, ["Success rate (%)", "Duplicate charges"],
        ["Confirmed payment success (%)", "Extra committed charges"],
    ):
        bars = ax.bar(labels, results[metric], color=colors, width=0.6)
        ax.bar_label(bars, padding=4, fmt="%.1f" if "%" in metric else "%d")
        ax.set_title(title, loc="left", fontsize=12, pad=14)
        ax.set_ylim(0, 105 if "%" in metric else max(results[metric]) * 1.25 + 1)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(axis="x", length=0, labelsize=9)
        ax.yaxis.grid(True, alpha=0.15)
        ax.set_axisbelow(True)
    fig.suptitle("RetryWise: payment retry policies", x=0.06, ha="left", fontsize=16)
    fig.text(0.06, 0.03, "600 synthetic payments · seed 2027 · four-attempt retry limit · simulated outcomes", fontsize=9, color="#475569")
    fig.tight_layout(rect=(0, 0.08, 1, 0.94))
    fig.savefig(args.output / "policy_comparison.png", dpi=180)
    plt.close(fig)
    print(results.to_string(index=False))
    print(f"\nSaved results to {args.output.resolve()}")


if __name__ == "__main__":
    main()
