"""
Reusable modelling utilities for the claims-fraud project.
Used by both src/train_model.py (pipeline) and notebooks/02_fraud_model_and_business_impact.ipynb (walkthrough).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
FEATURES_CSV = ROOT / "data" / "processed" / "claim_features.csv"

# --------------------------------------------------------------------------- #
# Business assumptions (stated explicitly so they can be challenged)
# --------------------------------------------------------------------------- #
COST_PER_INVESTIGATION = 5_000      # INR: desk review + field visit, blended
RECOVERY_RATE = 0.60                # share of a fraudulent claim's amount actually saved when caught
                                    # (inflated claims often still pay the genuine portion)
FALSE_POSITIVE_FRICTION = 15_000    # INR: cost of investigating a genuine customer
                                    # (settlement delay, complaint handling, higher churn risk)
SIU_CAPACITY = 0.10                 # SIU can investigate ~10% of incoming claims
RANDOM_STATE = 42

TARGET = "is_fraud"
ID_COLS = ["claim_id", "incident_date", "incident_year"]
BASELINE_COL = "red_flag_score"     # rules engine output: benchmark, not a feature

CATEGORICAL = ["claim_type", "incident_severity", "claim_channel", "policy_type",
               "vehicle_segment", "fuel_type", "sales_channel", "gender", "occupation"]

NUMERIC = [
    "incident_hour", "incident_hour_missing", "is_night_incident", "is_weekend",
    "police_report_filed", "witness_count", "num_vehicles_involved", "claimant_has_lawyer",
    "incident_outside_home_city", "days_policy_to_incident", "days_incident_to_expiry",
    "report_delay_days", "dq_report_before_incident", "total_claim_amount",
    "vehicle_claim_amount", "injury_claim_amount", "property_claim_amount",
    "claim_to_idv_ratio", "claim_to_premium_ratio", "claim_to_income_ratio",
    "vehicle_age_years", "idv", "annual_premium", "ncb_percent", "zero_dep_addon",
    "voluntary_deductible", "is_new_business", "is_renewal", "customer_age", "annual_income",
    "income_missing", "customer_tenure_years", "cust_prior_claims_365d", "cust_prior_claims_total",
    "policy_prior_claims", "has_garage", "is_network_garage", "garage_tenure_years",
    "garage_prior_claims", "garage_hist_fraud_rate", "agent_prior_claims", "agent_hist_fraud_rate",
]
FEATURES = CATEGORICAL + NUMERIC
LEAKAGE_COLS = ["claim_status", "settled_amount"]  # decided after investigation: never features


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_features(path: Path = FEATURES_CSV) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["incident_date"])
    assert not set(LEAKAGE_COLS) & set(df.columns), "leakage column found in feature table"
    for c in CATEGORICAL:
        df[c] = df[c].astype("object")
    return df


def time_split(df: pd.DataFrame):
    """Out-of-time split, mirroring how the model is used: learn from the past, score the future.
    train = 2022-2023, validation = 2024 (model selection / tuning), test = 2025 (final, untouched)."""
    train = df[df.incident_year <= 2023]
    valid = df[df.incident_year == 2024]
    test = df[df.incident_year == 2025]
    return train, valid, test


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
def _onehot():
    return OneHotEncoder(handle_unknown="ignore", min_frequency=20, sparse_output=False)


def make_logistic() -> Pipeline:
    pre = ColumnTransformer([
        ("cat", _onehot(), CATEGORICAL),
        ("num", Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)),
                          ("scale", StandardScaler())]), NUMERIC),
    ])
    clf = LogisticRegression(C=0.3, class_weight="balanced", max_iter=3000)
    return Pipeline([("prep", pre), ("model", clf)])


def make_random_forest() -> Pipeline:
    pre = ColumnTransformer([
        ("cat", _onehot(), CATEGORICAL),
        ("num", SimpleImputer(strategy="median", add_indicator=True), NUMERIC),
    ])
    clf = RandomForestClassifier(n_estimators=400, min_samples_leaf=5, max_features="sqrt",
                                 class_weight="balanced_subsample", n_jobs=-1,
                                 random_state=RANDOM_STATE)
    return Pipeline([("prep", pre), ("model", clf)])


def make_gradient_boosting(learning_rate=0.05, max_leaf_nodes=31, l2_regularization=1.0,
                           class_weight=None, max_iter=400) -> Pipeline:
    # HistGradientBoosting handles missing values natively: no imputation needed
    pre = ColumnTransformer([
        ("cat", _onehot(), CATEGORICAL),
        ("num", "passthrough", NUMERIC),
    ])
    clf = HistGradientBoostingClassifier(
        learning_rate=learning_rate, max_leaf_nodes=max_leaf_nodes,
        l2_regularization=l2_regularization, class_weight=class_weight, max_iter=max_iter,
        early_stopping=True, validation_fraction=0.15, n_iter_no_change=30,
        random_state=RANDOM_STATE)
    return Pipeline([("prep", pre), ("model", clf)])


# --------------------------------------------------------------------------- #
# Evaluation: statistical + business metrics
# --------------------------------------------------------------------------- #
def top_k_metrics(y, score, amount, capacity=SIU_CAPACITY) -> dict:
    """Metrics when the SIU investigates the top `capacity` share of claims by score."""
    y, score, amount = np.asarray(y), np.asarray(score, float), np.asarray(amount, float)
    k = int(round(capacity * len(y)))
    # tiny jitter breaks ties for discrete scores (e.g. rules) deterministically
    order = np.argsort(-(score + np.random.default_rng(0).uniform(0, 1e-6, len(score))))[:k]
    tp = y[order].sum()
    fraud_amt_caught = amount[order][y[order] == 1].sum()
    return {
        "precision_at_capacity": tp / k,
        "recall_at_capacity": tp / y.sum(),
        "fraud_amount_caught": fraud_amt_caught,
        "fraud_amount_recall": fraud_amt_caught / amount[y == 1].sum(),
        "investigations": k,
        "false_positives": k - tp,
        "fraud_savings": RECOVERY_RATE * fraud_amt_caught,
        "net_benefit": RECOVERY_RATE * fraud_amt_caught - k * COST_PER_INVESTIGATION
                       - (k - tp) * FALSE_POSITIVE_FRICTION,
    }


def evaluate(y, score, amount, capacity=SIU_CAPACITY) -> dict:
    return {"roc_auc": roc_auc_score(y, score),
            "pr_auc": average_precision_score(y, score),
            **top_k_metrics(y, score, amount, capacity)}


def capacity_curve(y, score, amount, grid=None) -> pd.DataFrame:
    """Recall, precision, ₹ caught and net benefit as the SIU reviews more claims."""
    grid = grid if grid is not None else np.round(np.arange(0.01, 0.51, 0.01), 2)
    rows = [{"pct_reviewed": g, **top_k_metrics(y, score, amount, g)} for g in grid]
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Explainability: business-readable reason codes for each flagged claim
# --------------------------------------------------------------------------- #
REASON_RULES = [
    ("Garage has high historical fraud rate", lambda d: d.garage_hist_fraud_rate >= 0.25),
    ("Agent has high historical fraud rate", lambda d: d.agent_hist_fraud_rate >= 0.20),
    ("Claim within 30 days of policy start", lambda d: d.days_policy_to_incident <= 30),
    ("Claim in last 20 days before expiry", lambda d: d.days_incident_to_expiry <= 20),
    ("Reported more than 7 days late", lambda d: d.report_delay_days > 7),
    ("Night-time incident (00:00-05:00)", lambda d: d.is_night_incident == 1),
    ("No police report on major loss", lambda d: (d.police_report_filed == 0) & (d.incident_severity != "Minor")),
    ("Repeat claimant (claim in last 12 months)", lambda d: d.cust_prior_claims_365d >= 1),
    ("Lawyer involved in injury claim", lambda d: d.claimant_has_lawyer == 1),
    ("Theft of an old vehicle (7+ yrs)", lambda d: (d.claim_type == "Theft") & (d.vehicle_age_years >= 7)),
    ("Policy recently ported from another insurer", lambda d: d.is_new_business == 1),
    ("Claim > 50% of insured value", lambda d: (d.claim_to_idv_ratio > 0.5) & (d.incident_severity != "Total Loss")),
]


def reason_codes(df: pd.DataFrame, max_reasons: int = 3) -> pd.Series:
    """Top triggered red flags, ordered by business priority, as one readable string."""
    hits = pd.DataFrame({name: rule(df).fillna(False).astype(bool) for name, rule in REASON_RULES},
                        index=df.index)
    return hits.apply(lambda r: "; ".join(list(r[r].index)[:max_reasons]) or "Model pattern (no single red flag)",
                      axis=1)
