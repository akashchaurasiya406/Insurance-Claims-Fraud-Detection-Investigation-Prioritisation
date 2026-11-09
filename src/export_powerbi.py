"""
Export a star-schema dataset for the Power BI dashboard.

    powerbi/data/
        fact_claims.csv          one row per claim (2022-2025) + model scores for 2025
        dim_policy.csv           policies that have at least one claim
        dim_customer.csv         customers who have claimed
        dim_agent.csv
        dim_garage.csv
        model_comparison.csv     2025 hold-out metrics per approach
        capacity_curve.csv       % reviewed vs fraud caught / net benefit (model, rules, random)
        feature_importance.csv   permutation importance

Usage:
    python src/export_powerbi.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "insurance_claims.db"
OUT = ROOT / "powerbi" / "data"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)

    fact = pd.read_sql("""
        SELECT b.claim_id, b.policy_id, b.customer_id, b.agent_id, b.garage_id,
               b.incident_date, b.report_date, b.incident_year,
               b.claim_type, b.incident_severity, b.claim_channel, b.incident_city,
               b.incident_hour, b.police_report_filed, b.witness_count, b.claimant_has_lawyer,
               b.vehicle_claim_amount, b.injury_claim_amount, b.property_claim_amount, b.total_claim_amount,
               CAST(b.days_policy_to_incident AS INTEGER) AS days_policy_to_incident,
               CAST(b.report_delay_days AS INTEGER)       AS report_delay_days,
               b.is_fraud, c.claim_status, c.settled_amount,
               f.red_flag_score,
               f.rf_early_claim, f.rf_near_expiry, f.rf_late_report, f.rf_night_incident,
               f.rf_no_police_report, f.rf_high_claim_vs_idv, f.rf_repeat_claimant,
               f.rf_lawyer_involved, f.rf_old_vehicle_theft, f.rf_new_business
        FROM v_claim_base b
        JOIN claims c          ON b.claim_id = c.claim_id
        JOIN claim_red_flags f ON b.claim_id = f.claim_id
    """, con)

    # bucket columns pre-built so the report has sensible sort orders
    fact["policy_age_bucket"] = pd.cut(fact.days_policy_to_incident, [-1, 30, 90, 180, 330, 400],
                                       labels=["1. 0-30 days", "2. 31-90 days", "3. 91-180 days",
                                               "4. 181-330 days", "5. Last 35 days"]).astype(object)
    fact["report_delay_bucket"] = pd.cut(fact.report_delay_days, [-1, 1, 7, 30, 10_000],
                                         labels=["1. 0-1 days", "2. 2-7 days", "3. 8-30 days",
                                                 "4. 30+ days"]).astype(object).fillna("Unknown")
    fact["fraud_label"] = fact.is_fraud.map({1: "Fraud", 0: "Genuine"})

    scored = pd.read_csv(ROOT / "data" / "processed" / "scored_claims_2025.csv")[
        ["claim_id", "fraud_probability", "expected_fraud_loss", "priority_rank", "risk_band",
         "flag_for_siu", "rules_flag", "reason_codes"]]
    fact = fact.merge(scored, on="claim_id", how="left")
    fact["is_scored"] = fact.fraud_probability.notna().astype(int)
    # nullable whole numbers: write "22", not "22.0", so Power BI can type them as whole numbers
    for col in ["incident_hour", "report_delay_days", "priority_rank", "flag_for_siu", "rules_flag"]:
        fact[col] = fact[col].round().astype("Int64")
    fact.to_csv(OUT / "fact_claims.csv", index=False)

    claim_policies = "SELECT DISTINCT policy_id FROM claims"
    pd.read_sql(f"SELECT * FROM policies WHERE policy_id IN ({claim_policies})", con) \
        .to_csv(OUT / "dim_policy.csv", index=False)
    pd.read_sql(f"""SELECT * FROM customers WHERE customer_id IN
                    (SELECT customer_id FROM policies WHERE policy_id IN ({claim_policies}))""", con) \
        .to_csv(OUT / "dim_customer.csv", index=False)
    pd.read_sql("SELECT * FROM agents", con).to_csv(OUT / "dim_agent.csv", index=False)
    pd.read_sql("SELECT * FROM garages", con).to_csv(OUT / "dim_garage.csv", index=False)
    con.close()

    reports = ROOT / "reports"
    mc = pd.read_csv(reports / "test_model_comparison.csv")
    mc["display_order"] = range(1, len(mc) + 1)
    mc.to_csv(OUT / "model_comparison.csv", index=False)
    cc = pd.read_csv(reports / "capacity_curve_2025.csv")
    cc["pct_reviewed"] = (cc.pct_reviewed * 100).round(0).astype(int)
    cc.to_csv(OUT / "capacity_curve.csv", index=False)
    pd.read_csv(reports / "feature_importance.csv").to_csv(OUT / "feature_importance.csv", index=False)

    for f in sorted(OUT.glob("*.csv")):
        print(f"{f.name:<26} {sum(1 for _ in open(f)) - 1:>7,} rows")


if __name__ == "__main__":
    main()
