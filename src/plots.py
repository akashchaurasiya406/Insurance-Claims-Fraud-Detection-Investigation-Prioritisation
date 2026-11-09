"""Consistent chart styling + the charts used in notebooks and reports."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve, roc_curve

# Categorical slots in fixed order (validated colour-blind-safe palette)
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
GREY, INK, INK2 = "#9b9a96", "#0b0b0b", "#52514e"
MODEL_COLORS = {"Gradient Boosting": BLUE, "Rules engine (baseline)": ORANGE,
                "Random Forest": AQUA, "Logistic Regression": YELLOW, "Random": GREY}


def setup_style():
    plt.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 150, "savefig.bbox": "tight",
        "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
        "axes.edgecolor": "#d6d5d0", "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": "#ebeae6", "grid.linewidth": 0.8, "axes.axisbelow": True,
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.labelcolor": INK2, "axes.labelsize": 10, "text.color": INK,
        "xtick.color": INK2, "ytick.color": INK2, "xtick.labelsize": 9, "ytick.labelsize": 9,
        "legend.frameon": False, "legend.fontsize": 9, "lines.linewidth": 2,
        "font.family": "DejaVu Sans",
    })


def bar_rate(ax, labels, rates, title, base_rate=None, color=BLUE, fmt="{:.1f}%", horizontal=False):
    """Bar chart of a rate (in %) with optional portfolio-average reference line."""
    pos = np.arange(len(labels))
    if horizontal:
        ax.barh(pos, rates, color=color, height=0.6)
        ax.set_yticks(pos, labels)
        ax.invert_yaxis()
        ax.grid(axis="y", visible=False)
        for p, r in zip(pos, rates):
            ax.text(r, p, " " + fmt.format(r), va="center", fontsize=9, color=INK2)
        if base_rate is not None:
            ax.axvline(base_rate, color=INK2, lw=1, ls="--", label=f"Portfolio average ({base_rate:.1f}%)")
            ax.legend(loc="lower right")
    else:
        ax.bar(pos, rates, color=color, width=0.6)
        ax.set_xticks(pos, labels)
        ax.grid(axis="x", visible=False)
        for p, r in zip(pos, rates):
            ax.text(p, r, fmt.format(r), ha="center", va="bottom", fontsize=9, color=INK2)
        if base_rate is not None:
            ax.axhline(base_rate, color=INK2, lw=1, ls="--", label=f"Portfolio average ({base_rate:.1f}%)")
            ax.legend(loc="best")
    ax.set_title(title)
    return ax


def pr_roc_curves(y, scores: dict):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    for name, s in scores.items():
        p, r, _ = precision_recall_curve(y, s)
        fpr, tpr, _ = roc_curve(y, s)
        c = MODEL_COLORS.get(name, GREY)
        axes[0].plot(r, p, color=c, label=name)
        axes[1].plot(fpr, tpr, color=c, label=name)
    axes[0].axhline(np.mean(y), color=GREY, ls="--", lw=1, label=f"Random ({np.mean(y):.0%})")
    axes[1].plot([0, 1], [0, 1], color=GREY, ls="--", lw=1, label="Random")
    axes[0].set(xlabel="Recall (share of fraud caught)", ylabel="Precision (hit rate)",
                title="Precision-Recall curve (2025 hold-out)")
    axes[1].set(xlabel="False positive rate", ylabel="True positive rate", title="ROC curve (2025 hold-out)")
    for ax in axes:
        ax.legend(loc="best")
    fig.tight_layout()
    return fig


def capacity_chart(curves: dict, capacity: float, metric="recall_at_capacity", ylabel="Share of fraud caught",
                   title="How much fraud does the SIU catch for a given review effort?"):
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for name, cdf in curves.items():
        ax.plot(cdf.pct_reviewed * 100, cdf[metric] * (100 if cdf[metric].max() <= 1 else 1),
                color=MODEL_COLORS.get(name, GREY), label=name,
                ls="--" if name == "Random" else "-", lw=1.2 if name == "Random" else 2)
    ax.axvline(capacity * 100, color=INK2, lw=1, ls=":")
    ax.text(capacity * 100, ax.get_ylim()[1] * 0.97, f"  SIU capacity {capacity:.0%}", fontsize=8,
            color=INK2, va="top")
    ax.set(xlabel="% of claims investigated (highest-risk first)", ylabel=ylabel, title=title)
    ax.legend(loc="lower right")
    fig.tight_layout()
    return fig


def net_benefit_chart(curves: dict, capacity: float):
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for name, cdf in curves.items():
        ax.plot(cdf.pct_reviewed * 100, cdf.net_benefit / 1e7, color=MODEL_COLORS.get(name, GREY),
                label=name, ls="--" if name == "Random" else "-", lw=1.2 if name == "Random" else 2)
        if name != "Random":
            best = cdf.loc[cdf.net_benefit.idxmax()]
            ax.scatter(best.pct_reviewed * 100, best.net_benefit / 1e7, s=40, zorder=3,
                       color=MODEL_COLORS.get(name, GREY), edgecolor="#fcfcfb", linewidth=2)
    ax.axvline(capacity * 100, color=INK2, lw=1, ls=":")
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set(xlabel="% of claims investigated (highest-risk first)",
           ylabel="Net benefit (₹ crore)",
           title="Net benefit = fraud savings − investigation & customer-friction cost (2025)")
    ax.legend(loc="best")
    fig.tight_layout()
    return fig


def importance_chart(imp: pd.DataFrame, top=15):
    d = imp.head(top).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8.5, 5.6))
    ax.barh(d.feature, d.importance, xerr=d["std"], color=BLUE, height=0.6,
            error_kw={"ecolor": INK2, "lw": 0.8, "capsize": 2})
    ax.grid(axis="y", visible=False)
    ax.set(xlabel="Drop in PR-AUC when feature is shuffled", title=f"Top {top} fraud drivers (permutation importance)")
    fig.tight_layout()
    return fig
