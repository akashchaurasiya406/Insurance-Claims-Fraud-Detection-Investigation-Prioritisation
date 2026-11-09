"""
Train, compare and select the fraud model; produce business metrics, charts and the scored claims.

Pipeline
  1. Out-of-time split: train 2022-23 | validate 2024 | test 2025
  2. Candidates: rules engine (baseline), Logistic Regression, Random Forest, Gradient Boosting
     (+ small tuning grid incl. class-weighting for imbalance), selected on validation PR-AUC
  3. Re-fit on 2022-24, evaluate once on 2025
  4. Business view: capacity curve, net benefit, ranking by probability vs expected loss (₹)
  5. Explainability: permutation importance + per-claim reason codes
  6. Outputs: models/, reports/, data/processed/scored_claims_2025.csv

Usage:
    python src/train_model.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

sys.path.insert(0, str(Path(__file__).resolve().parent))
import modeling as M  # noqa: E402
import plots as P  # noqa: E402

ROOT = M.ROOT
FIG = ROOT / "reports" / "figures"
MODELS = ROOT / "models"
PROCESSED = ROOT / "data" / "processed"


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(parents=True, exist_ok=True)
    P.setup_style()

    df = M.load_features()
    train, valid, test = M.time_split(df)
    print(f"train {len(train):,} ({train.is_fraud.mean():.1%} fraud) | "
          f"valid {len(valid):,} ({valid.is_fraud.mean():.1%}) | test {len(test):,} ({test.is_fraud.mean():.1%})")

    # ------------------------------------------------------------------ #
    # 1. Model selection on validation (2024)
    # ------------------------------------------------------------------ #
    candidates = {
        "Logistic Regression": M.make_logistic(),
        "Random Forest": M.make_random_forest(),
    }
    gb_grid = [dict(learning_rate=lr, max_leaf_nodes=leaves, class_weight=cw)
               for lr in (0.03, 0.06) for leaves in (15, 31) for cw in (None, "balanced")]
    for params in gb_grid:
        name = f"GB lr={params['learning_rate']} leaves={params['max_leaf_nodes']} cw={params['class_weight']}"
        candidates[name] = M.make_gradient_boosting(**params)

    rows = [{"model": "Rules engine (baseline)",
             **M.evaluate(valid.is_fraud, valid[M.BASELINE_COL], valid.total_claim_amount)}]
    fitted = {}
    for name, pipe in candidates.items():
        pipe.fit(train[M.FEATURES], train.is_fraud)
        s = pipe.predict_proba(valid[M.FEATURES])[:, 1]
        rows.append({"model": name, **M.evaluate(valid.is_fraud, s, valid.total_claim_amount)})
        fitted[name] = pipe
        print(f"  {name:<45} PR-AUC {rows[-1]['pr_auc']:.3f}  ROC-AUC {rows[-1]['roc_auc']:.3f}")
    val_df = pd.DataFrame(rows).sort_values("pr_auc", ascending=False)
    val_df.to_csv(ROOT / "reports" / "validation_model_selection.csv", index=False)

    gb_rows = val_df[val_df.model.str.startswith("GB ")]
    best_gb_name = gb_rows.iloc[0].model
    best_gb_params = gb_grid[[f"GB lr={p['learning_rate']} leaves={p['max_leaf_nodes']} cw={p['class_weight']}"
                              for p in gb_grid].index(best_gb_name)]
    print(f"\nBest gradient-boosting config on validation: {best_gb_name}")

    # ranking strategy chosen on validation: probability vs expected loss (p x claim amount)
    s_val = fitted[best_gb_name].predict_proba(valid[M.FEATURES])[:, 1]
    by_prob = M.top_k_metrics(valid.is_fraud, s_val, valid.total_claim_amount)
    by_value = M.top_k_metrics(valid.is_fraud, s_val * valid.total_claim_amount, valid.total_claim_amount)
    use_expected_loss = by_value["net_benefit"] > by_prob["net_benefit"]
    print(f"Validation net benefit @10%: rank by probability ₹{by_prob['net_benefit']/1e7:.2f} Cr | "
          f"rank by expected loss ₹{by_value['net_benefit']/1e7:.2f} Cr -> "
          f"{'expected loss' if use_expected_loss else 'probability'}")

    # ------------------------------------------------------------------ #
    # 2. Re-fit on 2022-2024 and evaluate ONCE on 2025
    # ------------------------------------------------------------------ #
    trval = pd.concat([train, valid])
    final_models = {
        "Logistic Regression": M.make_logistic(),
        "Random Forest": M.make_random_forest(),
        "Gradient Boosting": M.make_gradient_boosting(**best_gb_params),
    }
    test_scores = {"Rules engine (baseline)": test[M.BASELINE_COL].to_numpy(float)}
    for name, pipe in final_models.items():
        pipe.fit(trval[M.FEATURES], trval.is_fraud)
        test_scores[name] = pipe.predict_proba(test[M.FEATURES])[:, 1]

    y, amt = test.is_fraud.to_numpy(), test.total_claim_amount.to_numpy()
    test_rows = [{"model": n, **M.evaluate(y, s, amt)} for n, s in test_scores.items()]
    gb_p = test_scores["Gradient Boosting"]
    test_rows.append({"model": "Gradient Boosting (ranked by expected ₹ loss)",
                      **M.evaluate(y, gb_p * amt, amt)})
    test_df = pd.DataFrame(test_rows)
    test_df.to_csv(ROOT / "reports" / "test_model_comparison.csv", index=False)
    print("\n2025 hold-out results:")
    print(test_df[["model", "roc_auc", "pr_auc", "precision_at_capacity", "recall_at_capacity",
                   "fraud_amount_recall", "net_benefit"]].round(3).to_string(index=False))

    final = final_models["Gradient Boosting"]
    joblib.dump({"pipeline": final, "features": M.FEATURES, "params": best_gb_params,
                 "rank_by_expected_loss": bool(use_expected_loss)}, MODELS / "fraud_model.joblib")

    # ------------------------------------------------------------------ #
    # 3. Business curves
    # ------------------------------------------------------------------ #
    priority = gb_p * amt if use_expected_loss else gb_p
    rng = np.random.default_rng(0)
    curves = {
        "Gradient Boosting": M.capacity_curve(y, priority, amt),
        "Rules engine (baseline)": M.capacity_curve(y, test_scores["Rules engine (baseline)"], amt),
        "Random": M.capacity_curve(y, rng.random(len(y)), amt),
    }
    pd.concat([c.assign(strategy=n) for n, c in curves.items()]).to_csv(
        ROOT / "reports" / "capacity_curve_2025.csv", index=False)

    P.pr_roc_curves(y, {k: v for k, v in test_scores.items()}).savefig(FIG / "06_pr_roc_curves.png")
    P.capacity_chart(curves, M.SIU_CAPACITY, metric="fraud_amount_recall",
                     ylabel="% of fraud value (₹) caught",
                     title="Fraud value caught vs. investigation effort (2025 hold-out)").savefig(FIG / "07_capacity_recall.png")
    P.net_benefit_chart(curves, M.SIU_CAPACITY).savefig(FIG / "08_net_benefit.png")

    # ------------------------------------------------------------------ #
    # 4. Explainability
    # ------------------------------------------------------------------ #
    pi = permutation_importance(final, test[M.FEATURES], y, scoring="average_precision",
                                n_repeats=5, random_state=M.RANDOM_STATE, n_jobs=-1)
    imp = (pd.DataFrame({"feature": M.FEATURES, "importance": pi.importances_mean, "std": pi.importances_std})
           .sort_values("importance", ascending=False))
    imp.to_csv(ROOT / "reports" / "feature_importance.csv", index=False)
    P.importance_chart(imp).savefig(FIG / "09_feature_importance.png")

    # ------------------------------------------------------------------ #
    # 5. Score 2025 claims -> investigation queue (feeds Power BI)
    # ------------------------------------------------------------------ #
    scored = test[["claim_id", "incident_date", "claim_type", "incident_severity", "total_claim_amount",
                   "is_fraud", "red_flag_score"]].copy()
    scored["fraud_probability"] = gb_p.round(4)
    scored["expected_fraud_loss"] = (gb_p * amt).round(0)
    scored["priority_score"] = priority
    scored["priority_rank"] = scored.priority_score.rank(ascending=False, method="first").astype(int)
    pct = scored.priority_rank / len(scored)
    scored["risk_band"] = np.select([pct <= 0.05, pct <= M.SIU_CAPACITY, pct <= 0.25],
                                    ["1-Critical", "2-High", "3-Medium"], "4-Low")
    scored["flag_for_siu"] = (pct <= M.SIU_CAPACITY).astype(int)
    k = int(round(M.SIU_CAPACITY * len(scored)))
    scored["rules_flag"] = 0
    tie_break = np.random.default_rng(0).uniform(0, 1e-6, len(scored))  # same tie-break as modeling.top_k_metrics
    rules_top = np.argsort(-(scored.red_flag_score.to_numpy(float) + tie_break))[:k]
    scored.iloc[rules_top, scored.columns.get_loc("rules_flag")] = 1
    scored["reason_codes"] = M.reason_codes(test).values
    scored = scored.drop(columns="priority_score").sort_values("priority_rank")
    scored.to_csv(PROCESSED / "scored_claims_2025.csv", index=False)

    # ------------------------------------------------------------------ #
    # 6. Headline numbers
    # ------------------------------------------------------------------ #
    gb_row = test_df.set_index("model").loc[
        "Gradient Boosting (ranked by expected ₹ loss)" if use_expected_loss else "Gradient Boosting"]
    rb_row = test_df.set_index("model").loc["Rules engine (baseline)"]
    best_cap = curves["Gradient Boosting"].loc[curves["Gradient Boosting"].net_benefit.idxmax()]
    summary = {
        "data": {"train_claims": len(train), "valid_claims": len(valid), "test_claims": len(test),
                 "test_fraud_rate": float(y.mean())},
        "selected_model": {"name": "HistGradientBoostingClassifier", "params": best_gb_params,
                           "ranking": "expected loss (p x amount)" if use_expected_loss else "probability"},
        "assumptions": {"siu_capacity": M.SIU_CAPACITY, "cost_per_investigation_inr": M.COST_PER_INVESTIGATION,
                        "recovery_rate": M.RECOVERY_RATE, "false_positive_friction_inr": M.FALSE_POSITIVE_FRICTION},
        "test_2025": {
            "model": {k: float(v) for k, v in gb_row.items()},
            "rules_baseline": {k: float(v) for k, v in rb_row.items()},
            "uplift": {
                "recall_points": float(gb_row.recall_at_capacity - rb_row.recall_at_capacity),
                "precision_multiple": float(gb_row.precision_at_capacity / rb_row.precision_at_capacity),
                "extra_fraud_amount_caught_inr": float(gb_row.fraud_amount_caught - rb_row.fraud_amount_caught),
                "extra_net_benefit_inr": float(gb_row.net_benefit - rb_row.net_benefit),
            },
            "optimal_review_share": float(best_cap.pct_reviewed),
            "net_benefit_at_optimum_inr": float(best_cap.net_benefit),
        },
        "top_drivers": imp.head(8).feature.tolist(),
    }
    (ROOT / "reports" / "model_results.json").write_text(json.dumps(summary, indent=2))
    u = summary["test_2025"]["uplift"]
    print(f"\nAt {M.SIU_CAPACITY:.0%} capacity on 2025: recall {gb_row.recall_at_capacity:.1%} vs "
          f"{rb_row.recall_at_capacity:.1%} (rules); precision x{u['precision_multiple']:.1f}; "
          f"extra fraud caught ₹{u['extra_fraud_amount_caught_inr']/1e7:.2f} Cr; "
          f"extra net benefit ₹{u['extra_net_benefit_inr']/1e7:.2f} Cr")
    print(f"Optimal review share: {best_cap.pct_reviewed:.0%} (net ₹{best_cap.net_benefit/1e7:.2f} Cr)")


if __name__ == "__main__":
    main()
