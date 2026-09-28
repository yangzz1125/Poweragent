"""Analyze frozen voltage episodes; refuse incomplete official runs by default."""

from __future__ import annotations

import argparse
import csv
import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

CONDITIONS = [f"I{i}-V{v}-R{r}" for i in range(2) for v in range(2) for r in range(2)]


def cluster_ci(group: pd.DataFrame, field: str, rng: np.random.Generator, samples: int = 1000) -> tuple[float, float]:
    # Resample scenarios, retaining all repeats; repeated calls are not independent cases.
    by_case = [part[field].to_numpy(dtype=float) for _, part in group.groupby("scenario_id")]
    if not by_case:
        return float("nan"), float("nan")
    means = np.array([np.concatenate([by_case[i] for i in rng.integers(len(by_case), size=len(by_case))]).mean() for _ in range(samples)])
    return tuple(np.quantile(means, [0.025, 0.975]))


def factorial(rows: pd.DataFrame) -> list[dict]:
    if set(rows["condition"]) != set(CONDITIONS):
        return [{"term": "model", "note": "all 8 conditions required"}]
    bits = rows["condition"].str.extract(r"I([01])-V([01])-R([01])").astype(int).to_numpy()
    i, v, r = bits.T
    design = np.column_stack((np.ones(len(rows)), i, v, r, i * v, i * r, v * r, i * v * r))
    y = rows["success"].to_numpy(dtype=float)
    rates = rows.groupby("condition")["success"].mean()
    if any((rates == 0) | (rates == 1)):
        return [{"term": "model", "note": "complete/quasi separation: coefficient not estimable"}]
    def objective(beta):
        z = design @ beta
        return np.logaddexp(0, z).sum() - y @ z
    fit = minimize(objective, np.zeros(8), method="BFGS")
    if not fit.success:
        return [{"term": "model", "note": f"optimization failed: {fit.message}"}]
    return [{"term": term, "log_odds": float(value), "odds_ratio": float(np.exp(value))}
            for term, value in zip(("intercept", "I", "V", "R", "IV", "IR", "VR", "IVR"), fit.x)]


def absolute_factorial_effects(rows: pd.DataFrame, samples: int = 1000) -> pd.DataFrame:
    """Scenario-paired rate contrasts; no finite logit coefficient is fabricated."""
    cells = rows.groupby(["scenario_id", "condition"])["success"].mean().unstack().reindex(columns=CONDITIONS).dropna()
    rng = np.random.default_rng(2026)
    records = []
    for size in (1, 2, 3):
        for factors in combinations(range(3), size):
            weights = np.array([np.prod([1 if condition[1 + 3 * f] == "1" else -1 for f in factors])
                                / (2 ** (3 - size)) for condition in CONDITIONS])
            values = cells.to_numpy() @ weights
            low = high = None
            if len(values) >= 2:
                draws = values[rng.integers(len(values), size=(samples, len(values)))].mean(axis=1)
                low, high = map(float, np.quantile(draws, [.025, .975]))
            records.append({"term": "".join("IVR"[f] for f in factors),
                            "absolute_rate_contrast": float(values.mean()) if len(values) else None,
                            "ci_low": low, "ci_high": high, "n_paired_scenarios": len(values),
                            "excluded_unpaired_scenarios": rows.scenario_id.nunique() - len(values),
                            "estimand": "main rate difference" if size == 1 else "difference-of-differences" if size == 2 else "triple difference"})
    return pd.DataFrame(records)


def analyze(csv_path: Path, output: Path, *, allow_incomplete: bool = False, bootstrap: int = 1000) -> dict:
    data = pd.read_csv(csv_path)
    required = {"run_id", "scenario_id", "condition", "repetition_index", "status", "success", "difficulty", "n_actual_power_flows", "total_tokens"}
    if not required <= set(data):
        raise ValueError(f"missing episode columns: {sorted(required - set(data))}")
    keys = ["run_id", "scenario_id", "condition", "repetition_index"]
    if data.duplicated(keys).any():
        raise ValueError("duplicate episode key")
    if data.run_id.nunique() != 1:
        raise ValueError("analyze each frozen run separately")
    errors = int((data.status != "complete").sum())
    complete = data[data.status == "complete"].copy()
    if not len(complete):
        raise ValueError("no completed episodes")
    run_path = csv_path.parent / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else {}
    planned = {tuple(task) for task in run.get("planned_tasks", [])}
    observed = set(data[["condition", "scenario_id", "repetition_index"]].itertuples(index=False, name=None))
    if planned and (run.get("run_id") != data.run_id.iloc[0] or observed - planned):
        raise ValueError("episode data differs from planned run")
    if not planned and not allow_incomplete:
        raise ValueError("official analysis requires run.json with planned_tasks; use --allow-incomplete for legacy debug")
    expected = len(planned) if planned else 8 * complete.scenario_id.nunique() * complete.repetition_index.nunique()
    if not allow_incomplete and (errors or observed != planned or len(data) != expected or set(complete.condition) != set(CONDITIONS)):
        raise ValueError(f"incomplete matrix: {len(complete)} complete, {errors} errors, expected {expected}")
    output.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(2026)
    main, difficulty = [], []
    for label, frame in ((main, complete.groupby("condition")), (difficulty, complete.groupby(["difficulty", "condition"]))):
        for name, group in frame:
            names = name if isinstance(name, tuple) else (name,)
            lower, upper = cluster_ci(group, "success", rng, bootstrap)
            failed = group[group.get("first_submit_failed", pd.Series(False, index=group.index)).fillna(0).astype(bool)]
            label.append({"difficulty": names[0] if len(names) == 2 else "all", "condition": names[-1],
                          "n": len(group), "n_scenarios": group.scenario_id.nunique(), "success_rate": group.success.mean(),
                          "ci_low": lower, "ci_high": upper, "first_pass_success": group.first_pass_success.mean() if "first_pass_success" in group else float("nan"),
                          "recovery_denominator": len(failed), "recovery_rate": failed.recovered.mean() if len(failed) else float("nan"),
                          "valid_action": group.valid_action.mean() if "valid_action" in group else float("nan"),
                          "power_flows": group.n_actual_power_flows.mean(), "tokens": group.total_tokens.mean(),
                          "token_coverage": group.total_tokens.notna().mean(), "latency_seconds": group.latency_seconds.mean() if "latency_seconds" in group else float("nan")})
    main_df, diff_df = pd.DataFrame(main), pd.DataFrame(difficulty)
    main_df.to_csv(output / "table3_main.csv", index=False)
    diff_df.to_csv(output / "difficulty.csv", index=False)
    effects = []
    for factor in ("domain_interface", "verification", "recovery"):
        if factor not in complete:
            continue
        other = [field for field in ("domain_interface", "verification", "recovery") if field != factor]
        paired = complete.pivot_table(index=["scenario_id", "repetition_index", *other], columns=factor, values="success").reindex(columns=[0, 1]).dropna(subset=[0, 1])
        differences = (paired[1] - paired[0]).rename("difference").reset_index()
        low, high = cluster_ci(differences, "difference", rng, bootstrap)
        effects.append({"term": factor, "absolute_success_difference": differences.difference.mean(), "ci_low": low, "ci_high": high, "n_pairs": len(differences)})
    absolute_factorial_effects(complete, bootstrap).to_csv(output / "factorial_rate_contrasts.csv", index=False)
    coefficients = factorial(complete)
    with (output / "table4_factorial.csv").open("w", newline="", encoding="utf-8") as stream:
        columns = ["term", "log_odds", "odds_ratio", "absolute_success_difference", "ci_low", "ci_high", "n_pairs", "note"]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(effects + coefficients)
    summary = {"run_ids": sorted(complete.run_id.unique().tolist()), "complete": len(complete), "errors": errors,
               "expected": expected, "coverage_verified": bool(planned), "missing_tasks": len(planned - observed) if planned else None, "missing_tokens": int(complete.total_tokens.isna().sum()), "dataset_sha256": sorted(complete.dataset_sha256.dropna().unique().tolist()) if "dataset_sha256" in complete else []}
    (output / "analysis_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    figures(main_df, diff_df, output)
    contract_figures(output, summary)
    return summary


def figures(main: pd.DataFrame, difficulty: pd.DataFrame, output: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    main = main.set_index("condition").reindex(CONDITIONS).reset_index()
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(main.condition, main.success_rate, color="#4177a8")
    ax.errorbar(range(8), main.success_rate, yerr=[main.success_rate - main.ci_low, main.ci_high - main.success_rate], fmt="none", color="black", capsize=3)
    ax.set(ylabel="Success rate (95% scenario-cluster bootstrap CI)", ylim=(0, 1.06))
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout(); fig.savefig(output / "figure3_success.png", dpi=180); plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(16, 4), sharey=True)
    for ax, level in zip(axes, ("easy", "medium", "hard")):
        part = difficulty[difficulty.difficulty == level].set_index("condition").reindex(CONDITIONS)
        ax.bar(range(8), part.success_rate, color="#4177a8")
        ax.set(title=level.title(), xticks=range(8), xticklabels=CONDITIONS, ylim=(0, 1.06))
        ax.tick_params(axis="x", rotation=65)
    axes[0].set_ylabel("Success rate")
    fig.tight_layout(); fig.savefig(output / "figure4_difficulty.png", dpi=180); plt.close(fig)
    for field, suffix in (("power_flows", "pf"), ("tokens", "tokens")):
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.scatter(main[field], main.success_rate)
        for _, row in main.iterrows():
            if pd.notna(row[field]):
                ax.annotate(row.condition, (row[field], row.success_rate))
        ax.set(xlabel=f"Mean {field} per episode", ylabel="Success rate", ylim=(0, 1.06))
        fig.tight_layout(); fig.savefig(output / f"figure5_cost_{suffix}.png", dpi=180); plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(main.condition, main.first_pass_success, label="First submit success")
    recovered = main.recovery_rate.fillna(0) * main.recovery_denominator / main.n
    ax.bar(main.condition, recovered, bottom=main.first_pass_success, label="Recovered after failure")
    ax.set(ylabel="Episode fraction", ylim=(0, 1.06)); ax.legend()
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout(); fig.savefig(output / "figure6_recovery.png", dpi=180); plt.close(fig)


def contract_figures(output: Path, summary: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from poweragentbench.voltage_case import DEFAULT_CONFIG_PATH, read_json

    config = read_json(DEFAULT_CONFIG_PATH)
    pd.DataFrame([{"property": "network", "value": "IEEE 33-bus"},
                  {"property": "voltage_limits_pu", "value": "0.95–1.05"},
                  {"property": "BESS", "value": str(len(config["bess"]))},
                  {"property": "dataset_sha256", "value": ", ".join(summary["dataset_sha256"])},
                  *({"property": key, "value": value} for key, value in config["agent"].items())]).to_csv(output / "table1_benchmark.csv", index=False)
    pd.DataFrame([{"condition": condition, "interface": int(condition[1]), "verification": int(condition[4]), "recovery": int(condition[7])} for condition in CONDITIONS]).to_csv(output / "table2_conditions.csv", index=False)
    fig, ax = plt.subplots(figsize=(11, 2))
    ax.axis("off")
    ax.text(.5, .65, "LLM → Domain interface → Tool server → Power flow", ha="center", fontsize=15)
    ax.text(.5, .3, "Preview verification → Independent evaluator → Recovery feedback", ha="center", fontsize=13)
    fig.tight_layout(); fig.savefig(output / "figure1_architecture.png", dpi=180); plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.axis("off")
    ax.table(cellText=[[name, name[1], name[4], name[7]] for name in CONDITIONS],
             colLabels=["Condition", "I", "V", "R"], loc="center")
    fig.tight_layout(); fig.savefig(output / "figure2_factorial.png", dpi=180); plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-incomplete", action="store_true", help="Only for Dev/debug; never label as a complete paper result")
    parser.add_argument("--bootstrap", type=int, default=1000)
    args = parser.parse_args()
    print(json.dumps(analyze(args.episodes, args.output_dir, allow_incomplete=args.allow_incomplete, bootstrap=args.bootstrap), indent=2))


if __name__ == "__main__":
    main()
