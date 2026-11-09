"""
Generate a realistic, synthetic motor-insurance dataset for claims fraud detection.

Why synthetic?  Real claims data is confidential. Public fraud datasets are either
tiny (~1,000 rows) or fully anonymised (V1..V28), which makes business
storytelling impossible. This generator builds a *relational* dataset
(customers, agents, garages, policies, claims) with fraud patterns modelled on
common industry red flags, plus deliberate noise so that no single rule or model
is perfect.

Tables written to data/raw/:
    customers.csv, agents.csv, garages.csv, policies.csv, claims.csv

Usage:
    python src/generate_data.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
N_CUSTOMERS = 30_000
N_AGENTS = 150
N_GARAGES = 320
DATA_START = np.datetime64("2022-01-01")
DATA_END = np.datetime64("2025-12-31")

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "raw"

rng = np.random.default_rng(SEED)

# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #
CITIES = {  # city: (state, relative weight)
    "Mumbai": ("Maharashtra", 10), "Pune": ("Maharashtra", 6), "Nagpur": ("Maharashtra", 2),
    "New Delhi": ("Delhi", 10), "Gurugram": ("Haryana", 4), "Noida": ("Uttar Pradesh", 4),
    "Lucknow": ("Uttar Pradesh", 3), "Kanpur": ("Uttar Pradesh", 2),
    "Bengaluru": ("Karnataka", 9), "Mysuru": ("Karnataka", 1),
    "Chennai": ("Tamil Nadu", 7), "Coimbatore": ("Tamil Nadu", 2),
    "Hyderabad": ("Telangana", 7), "Kolkata": ("West Bengal", 6),
    "Ahmedabad": ("Gujarat", 5), "Surat": ("Gujarat", 3),
    "Jaipur": ("Rajasthan", 3), "Ludhiana": ("Punjab", 2),
    "Indore": ("Madhya Pradesh", 2), "Bhopal": ("Madhya Pradesh", 2), "Kochi": ("Kerala", 2),
}
CITY_NAMES = np.array(list(CITIES))
CITY_W = np.array([v[1] for v in CITIES.values()], dtype=float)
CITY_W /= CITY_W.sum()

VEHICLES = [  # make, model, segment, fuel, IDV range when new (INR)
    ("Maruti Suzuki", "Swift", "Hatchback", "Petrol", (600_000, 850_000)),
    ("Maruti Suzuki", "Baleno", "Hatchback", "Petrol", (700_000, 950_000)),
    ("Maruti Suzuki", "Dzire", "Sedan", "CNG", (700_000, 900_000)),
    ("Maruti Suzuki", "Brezza", "SUV", "Petrol", (900_000, 1_350_000)),
    ("Hyundai", "i20", "Hatchback", "Petrol", (750_000, 1_100_000)),
    ("Hyundai", "Creta", "SUV", "Diesel", (1_150_000, 1_900_000)),
    ("Hyundai", "Verna", "Sedan", "Petrol", (1_100_000, 1_650_000)),
    ("Tata", "Nexon", "SUV", "Petrol", (850_000, 1_450_000)),
    ("Tata", "Punch", "SUV", "Petrol", (650_000, 950_000)),
    ("Tata", "Nexon EV", "SUV", "Electric", (1_450_000, 1_900_000)),
    ("Mahindra", "Scorpio-N", "SUV", "Diesel", (1_400_000, 2_300_000)),
    ("Mahindra", "XUV700", "SUV", "Diesel", (1_500_000, 2_500_000)),
    ("Mahindra", "Thar", "SUV", "Diesel", (1_200_000, 1_700_000)),
    ("Honda", "City", "Sedan", "Petrol", (1_200_000, 1_600_000)),
    ("Honda", "Amaze", "Sedan", "Petrol", (750_000, 950_000)),
    ("Toyota", "Innova Crysta", "MUV", "Diesel", (2_000_000, 2_600_000)),
    ("Toyota", "Fortuner", "SUV", "Diesel", (3_500_000, 5_000_000)),
    ("Kia", "Seltos", "SUV", "Petrol", (1_100_000, 2_000_000)),
    ("Kia", "Sonet", "SUV", "Diesel", (800_000, 1_400_000)),
    ("MG", "Hector", "SUV", "Petrol", (1_500_000, 2_200_000)),
    ("Skoda", "Slavia", "Sedan", "Petrol", (1_100_000, 1_800_000)),
    ("Volkswagen", "Virtus", "Sedan", "Petrol", (1_150_000, 1_900_000)),
]
VEH_W = np.array([12, 8, 9, 7, 6, 7, 3, 7, 5, 2, 4, 3, 3, 4, 3, 3, 1, 4, 3, 2, 2, 2], dtype=float)
VEH_W /= VEH_W.sum()

OCCUPATIONS = ["Salaried", "Self-employed", "Business Owner", "Professional", "Retired", "Student"]
OCC_W = [0.46, 0.18, 0.14, 0.12, 0.07, 0.03]

CHANNELS = ["Agent", "Broker", "Dealer", "Online", "Bancassurance"]
CHANNEL_W = [0.38, 0.17, 0.22, 0.15, 0.08]

GARAGE_WORDS_1 = ["Shree", "Sai", "Royal", "City", "Metro", "National", "Galaxy", "Prime",
                  "Star", "Balaji", "Ganesh", "Classic", "Supreme", "New India", "Highway"]
GARAGE_WORDS_2 = ["Motors", "Auto Works", "Car Care", "Automobiles", "Service Centre",
                  "Auto Garage", "Motor Works", "Car Clinic"]


def rand_dates(start: np.datetime64, end: np.datetime64, n: int) -> np.ndarray:
    span = int((end - start).astype(int))
    return start + rng.integers(0, span + 1, n).astype("timedelta64[D]")


# --------------------------------------------------------------------------- #
# Dimension tables
# --------------------------------------------------------------------------- #
def make_customers() -> pd.DataFrame:
    n = N_CUSTOMERS
    city = rng.choice(CITY_NAMES, n, p=CITY_W)
    occupation = rng.choice(OCCUPATIONS, n, p=OCC_W)
    age = np.clip(rng.normal(41, 11, n).round(), 21, 78).astype(int)
    age[occupation == "Retired"] = rng.integers(58, 79, (occupation == "Retired").sum())
    age[occupation == "Student"] = rng.integers(21, 26, (occupation == "Student").sum())

    base_income = {"Salaried": 900_000, "Self-employed": 1_000_000, "Business Owner": 1_800_000,
                   "Professional": 1_600_000, "Retired": 600_000, "Student": 250_000}
    income = np.array([base_income[o] for o in occupation]) * rng.lognormal(0, 0.45, n)
    income = (income / 1000).round() * 1000

    df = pd.DataFrame({
        "customer_id": [f"C{100000 + i}" for i in range(n)],
        "age": age,
        "gender": rng.choice(["Male", "Female"], n, p=[0.72, 0.28]),
        "occupation": occupation,
        "annual_income": income,
        "city": city,
        "state": [CITIES[c][0] for c in city],
        "customer_since": rand_dates(np.datetime64("2012-01-01"), np.datetime64("2025-06-30"), n),
    })
    # Data-quality issue: ~2% of incomes not captured at onboarding
    df.loc[rng.random(n) < 0.02, "annual_income"] = np.nan
    # Hidden behavioural trait (NOT exported): opportunistic / serial claimants
    df["_serial"] = rng.random(n) < 0.04
    return df


def make_agents() -> pd.DataFrame:
    n = N_AGENTS
    city = rng.choice(CITY_NAMES, n, p=CITY_W)
    df = pd.DataFrame({
        "agent_id": [f"A{1000 + i}" for i in range(n)],
        "channel": rng.choice(CHANNELS, n, p=CHANNEL_W),
        "city": city,
        "state": [CITIES[c][0] for c in city],
        "years_experience": rng.integers(0, 25, n),
    })
    df["_colluding"] = rng.random(n) < 0.05  # hidden
    return df


def make_garages() -> pd.DataFrame:
    n = N_GARAGES
    city = rng.choice(CITY_NAMES, n, p=CITY_W)
    names = [f"{rng.choice(GARAGE_WORDS_1)} {rng.choice(GARAGE_WORDS_2)}" for _ in range(n)]
    df = pd.DataFrame({
        "garage_id": [f"G{500 + i}" for i in range(n)],
        "garage_name": names,
        "city": city,
        "state": [CITIES[c][0] for c in city],
        "is_network_garage": (rng.random(n) < 0.7).astype(int),  # cashless network partner
        "empanelled_since": rand_dates(np.datetime64("2010-01-01"), np.datetime64("2024-06-30"), n),
    })
    df["_colluding"] = rng.random(n) < 0.04  # hidden
    # colluding garages are slightly more often non-network and recently empanelled
    col = df["_colluding"].to_numpy()
    df.loc[col & (rng.random(n) < 0.5), "is_network_garage"] = 0
    return df


# --------------------------------------------------------------------------- #
# Policies (one row per policy-year; vehicles renew year on year)
# --------------------------------------------------------------------------- #
def make_policies(customers: pd.DataFrame, agents: pd.DataFrame) -> pd.DataFrame:
    rows = []
    agent_ids = agents["agent_id"].to_numpy()
    agent_city = agents["city"].to_numpy()
    agents_by_city = {c: agent_ids[agent_city == c] for c in CITY_NAMES}
    pol_no = 0

    for cust in customers.itertuples(index=False):
        n_vehicles = 1 if rng.random() < 0.87 else 2
        for _ in range(n_vehicles):
            v = VEHICLES[rng.choice(len(VEHICLES), p=VEH_W)]
            make, model, segment, fuel, (lo, hi) = v
            price_new = rng.uniform(lo, hi)
            age_at_first = int(rng.choice(range(0, 12), p=np.array(
                [14, 12, 11, 10, 9, 8, 7, 6, 6, 6, 6, 5]) / 100))
            first_start = rand_dates(DATA_START - np.timedelta64(365, "D"),
                                     np.datetime64("2025-09-30"), 1)[0]
            years = int(rng.choice([1, 2, 3, 4, 5], p=[0.25, 0.25, 0.22, 0.16, 0.12]))
            # agent mostly from same city
            pool = agents_by_city.get(cust.city)
            agent = rng.choice(pool) if pool is not None and len(pool) and rng.random() < 0.85 \
                else rng.choice(agent_ids)
            is_new_business = rng.random() < 0.45  # came from another insurer at first policy
            zero_dep = rng.random() < (0.55 if age_at_first <= 4 else 0.15)
            ncb_ladder = [0, 20, 25, 35, 45, 50]
            ncb_idx = int(rng.integers(0, 4)) if is_new_business else 0

            for y in range(years):
                start = first_start + np.timedelta64(365 * y, "D")
                if start > DATA_END:
                    break
                veh_age = age_at_first + y
                idv = price_new * max(0.95 - 0.1 * veh_age, 0.30)
                policy_type = "Comprehensive" if (veh_age < 10 or rng.random() < 0.5) else "Third Party"
                rate = rng.uniform(0.022, 0.032)
                od_premium = 0 if policy_type == "Third Party" else idv * rate * (1 - ncb_ladder[ncb_idx] / 100)
                if zero_dep and policy_type == "Comprehensive" and veh_age <= 5:
                    od_premium *= 1.18
                tp_premium = 3_416 if price_new < 1_500_000 else 7_897
                pol_no += 1
                rows.append({
                    "policy_id": f"P{2000000 + pol_no}",
                    "customer_id": cust.customer_id,
                    "agent_id": agent,
                    "vehicle_make": make,
                    "vehicle_model": model,
                    "vehicle_segment": segment,
                    "fuel_type": fuel,
                    "vehicle_age_years": veh_age,
                    "policy_type": policy_type,
                    "zero_dep_addon": int(zero_dep and policy_type == "Comprehensive" and veh_age <= 5),
                    "idv": round(idv, -3) if policy_type == "Comprehensive" else 0,
                    "ncb_percent": ncb_ladder[ncb_idx],
                    "voluntary_deductible": int(rng.choice([0, 0, 0, 2500, 5000, 7500])),
                    "annual_premium": round(od_premium + tp_premium),
                    "policy_start_date": start,
                    "policy_end_date": start + np.timedelta64(364, "D"),
                    "is_renewal": int(y > 0),
                    "is_new_business": int(is_new_business and y == 0),
                    "_veh_key": f"{cust.customer_id}-{make}-{model}-{pol_no - y}",
                })
                ncb_idx = min(ncb_idx + 1, 5)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Claims + fraud label
# --------------------------------------------------------------------------- #
CLAIM_TYPES_OD = ["Collision", "Theft", "Fire", "Flood", "Vandalism", "Glass Damage"]
CLAIM_TYPES_OD_W = [0.60, 0.05, 0.03, 0.07, 0.09, 0.16]


def make_claims(customers, agents, garages, policies) -> pd.DataFrame:
    cust = customers.set_index("customer_id")
    agent_colluding = agents.set_index("agent_id")["_colluding"]
    gar = garages.copy()
    garage_ids_by_city = {c: gar.loc[gar.city == c, "garage_id"].to_numpy() for c in CITY_NAMES}
    colluding_garages_by_city = {c: gar.loc[(gar.city == c) & gar._colluding, "garage_id"].to_numpy()
                                 for c in CITY_NAMES}
    garage_colluding = gar.set_index("garage_id")["_colluding"]

    pol = policies.merge(customers[["customer_id", "city", "_serial", "annual_income"]], on="customer_id")
    pol["_agent_colluding"] = pol["agent_id"].map(agent_colluding).to_numpy()

    # claim frequency per policy-year
    lam = np.full(len(pol), 0.26)
    lam[pol["_serial"].to_numpy()] = 0.95
    lam[pol["_agent_colluding"].to_numpy()] *= 1.6
    lam[pol["policy_type"].to_numpy() == "Third Party"] *= 0.35
    n_claims = rng.poisson(lam)
    # itertuples() drops names starting with "_", so expose hidden columns as h_*
    pol = pol.rename(columns=lambda col: "h" + col if col.startswith("_") else col)

    rows = []
    claim_no = 0
    for p, k in zip(pol.itertuples(index=False), n_claims):
        for _ in range(k):
            start = p.policy_start_date
            # opportunistic claims cluster early in the policy (or just before expiry)
            if (p.h_serial or p.h_agent_colluding or p.is_new_business) and rng.random() < 0.35:
                offset = int(rng.integers(1, 45)) if rng.random() < 0.75 else int(rng.integers(345, 365))
            else:
                offset = int(rng.integers(1, 365))
            incident = start + np.timedelta64(offset, "D")
            if incident > DATA_END or incident < DATA_START:
                continue

            if p.policy_type == "Third Party":
                ctype = "Third Party Injury"
            else:
                ctype = str(rng.choice(CLAIM_TYPES_OD, p=CLAIM_TYPES_OD_W))
                if rng.random() < 0.04:
                    ctype = "Third Party Injury"

            if ctype == "Theft":
                severity = "Total Loss"
            elif ctype == "Glass Damage":
                severity = "Minor"
            elif ctype in ("Fire", "Flood"):
                severity = str(rng.choice(["Major", "Total Loss"], p=[0.7, 0.3]))
            elif ctype == "Third Party Injury":
                severity = str(rng.choice(["Minor", "Major"], p=[0.6, 0.4]))
            else:
                severity = str(rng.choice(["Minor", "Major", "Total Loss"], p=[0.62, 0.33, 0.05]))

            night = rng.random() < (0.30 if (p.h_serial or p.h_agent_colluding) else 0.12)
            hour = int(rng.integers(0, 5)) if night else int(rng.integers(6, 24))
            delay = int(rng.exponential(2.5))
            if p.h_serial and rng.random() < 0.3:
                delay += int(rng.integers(7, 40))
            if rng.random() < 0.03:
                delay += int(rng.integers(10, 60))  # genuine late reporters
            police = 1 if (severity != "Minor" and rng.random() < 0.82) else int(rng.random() < 0.15)
            if ctype == "Theft":
                police = int(rng.random() < 0.93)
            witnesses = int(rng.choice([0, 1, 2, 3], p=[0.45, 0.30, 0.17, 0.08]))
            has_lawyer = int(ctype == "Third Party Injury" and rng.random() < 0.35)
            n_veh = 1 if ctype in ("Theft", "Fire", "Flood", "Vandalism", "Glass Damage") \
                else int(rng.choice([1, 2, 3], p=[0.45, 0.45, 0.10]))

            # garage choice (none for theft / injury-only)
            garage = None
            if ctype not in ("Theft", "Third Party Injury"):
                col_pool = colluding_garages_by_city.get(p.city, np.array([]))
                if (p.h_serial or p.h_agent_colluding) and len(col_pool) and rng.random() < 0.45:
                    garage = rng.choice(col_pool)
                else:
                    pool = garage_ids_by_city.get(p.city)
                    garage = rng.choice(pool) if pool is not None and len(pool) else None

            claim_no += 1
            rows.append({
                "claim_id": f"CL{3000000 + claim_no}",
                "policy_id": p.policy_id,
                "garage_id": garage,
                "incident_date": incident,
                "incident_hour": hour,
                "report_date": incident + np.timedelta64(delay, "D"),
                "claim_type": ctype,
                "incident_severity": severity,
                "incident_city": p.city if rng.random() < 0.9 else str(rng.choice(CITY_NAMES, p=CITY_W)),
                "police_report_filed": police,
                "witness_count": witnesses,
                "num_vehicles_involved": n_veh,
                "claimant_has_lawyer": has_lawyer,
                "claim_channel": str(rng.choice(["Mobile App", "Call Centre", "Agent", "Garage"],
                                                p=[0.35, 0.30, 0.15, 0.20])),
                # hidden drivers used to build the label
                "_serial": p.h_serial,
                "_agent_colluding": p.h_agent_colluding,
                "_garage_colluding": bool(garage_colluding.get(garage, False)) if garage else False,
                "_idv": p.idv, "_veh_age": p.vehicle_age_years, "_policy_type": p.policy_type,
                "_new_business": p.is_new_business, "_offset": offset, "_income": p.annual_income,
                "_zero_dep": p.zero_dep_addon, "_veh_key": p.h_veh_key,
            })
    c = pd.DataFrame(rows).sort_values("incident_date").reset_index(drop=True)

    # prior claims on the same vehicle in last 365 days (any policy year)
    c["_prior"] = 0
    for _, g in c.groupby("_veh_key"):
        d = g["incident_date"].to_numpy()
        prior = [(d[:i] >= d[i] - np.timedelta64(365, "D")).sum() for i in range(len(d))]
        c.loc[g.index, "_prior"] = prior

    # ---------------- fraud propensity (latent logit) ---------------- #
    delay = (c["report_date"] - c["incident_date"]).dt.days
    logit = np.full(len(c), -4.35)
    logit += np.where(c._offset <= 30, 1.5, np.where(c._offset <= 90, 0.5, 0))
    logit += np.where(c._offset >= 345, 0.7, 0)
    logit += np.where(delay > 30, 1.3, np.where(delay > 7, 0.8, 0))
    logit += np.where(c.incident_hour <= 4, 0.7, 0)
    logit += np.where((c.police_report_filed == 0) & (c.incident_severity != "Minor"), 0.9, 0)
    logit += np.where(c.witness_count == 0, 0.3, -0.1)
    logit += np.where(c._garage_colluding, 2.0, 0)
    logit += np.where(c._agent_colluding, 1.2, 0)
    logit += np.where(c._serial, 0.8, 0)
    logit += np.where(c._prior >= 2, 0.9, np.where(c._prior == 1, 0.35, 0))
    logit += np.where((c.claim_type == "Theft") & (c._veh_age >= 7), 1.0, 0)
    logit += np.where(c.claim_type.isin(["Fire", "Theft"]), 0.4, 0)
    logit += np.where(c.claim_type == "Glass Damage", -0.8, 0)
    logit += np.where(c._new_business == 1, 0.45, 0)
    logit += np.where(c.claimant_has_lawyer == 1, 0.9, 0)
    logit += np.where((c._zero_dep == 1) & (c._offset <= 60), 0.4, 0)
    logit += rng.normal(0, 0.9, len(c))  # unexplained variation
    p_fraud = 1 / (1 + np.exp(-logit))
    c["is_fraud"] = (rng.random(len(c)) < p_fraud).astype(int)

    # ---------------- claim amounts ---------------- #
    idv = np.where(c._idv > 0, c._idv, 600_000).astype(float)
    sev = c.incident_severity.to_numpy()
    ctype = c.claim_type.to_numpy()
    n_c = len(c)
    # genuine repair bills: right-skewed with long tails, so genuine and padded bills overlap
    minor = np.clip(28_000 * rng.lognormal(0, 0.6, n_c), 3_000, 180_000)
    major = idv * np.clip(rng.lognormal(np.log(0.20), 0.5, n_c), 0.05, 0.75)
    total = idv * rng.uniform(0.75, 1.00, n_c)
    veh_amt = np.where(sev == "Minor", minor, np.where(sev == "Major", major, total))
    veh_amt = np.where(ctype == "Glass Damage", np.clip(11_000 * rng.lognormal(0, 0.55, n_c), 2_500, 60_000), veh_amt)
    veh_amt = np.where(ctype == "Third Party Injury", 0, veh_amt)
    inj_amt = np.where(ctype == "Third Party Injury",
                       np.where(sev == "Major", 500_000 * rng.lognormal(0, 0.6, n_c),
                                110_000 * rng.lognormal(0, 0.6, n_c)),
                       np.where((c.num_vehicles_involved > 1) & (rng.random(n_c) < 0.15),
                                60_000 * rng.lognormal(0, 0.7, n_c), 0))
    prop_amt = np.where((ctype == "Collision") & (c.num_vehicles_involved > 1),
                        35_000 * rng.lognormal(0, 0.7, n_c), 0)
    prop_amt = np.where((ctype == "Collision") & (c.num_vehicles_involved == 1) & (rng.random(n_c) < 0.1),
                        20_000 * rng.lognormal(0, 0.7, n_c), prop_amt)

    # fraudsters pad their bills - moderately, so padding shifts the distribution
    # rather than creating an impossible-for-genuine region
    fraud = c.is_fraud.to_numpy() == 1
    pad = np.where(fraud, rng.uniform(1.10, 1.55, n_c), rng.lognormal(0, 0.08, n_c))
    veh_amt = np.minimum(veh_amt * pad, idv)
    inj_amt = inj_amt * np.where(fraud, rng.uniform(1.1, 1.6, n_c), 1)

    c["vehicle_claim_amount"] = veh_amt.round(-2)
    c["injury_claim_amount"] = inj_amt.round(-2)
    c["property_claim_amount"] = prop_amt.round(-2)
    c["total_claim_amount"] = c[["vehicle_claim_amount", "injury_claim_amount", "property_claim_amount"]].sum(axis=1)

    # ---------------- investigation outcome (post-event, leakage columns) ---------------- #
    r = rng.random(len(c))
    status = np.where(fraud,
                      np.where(r < 0.62, "Rejected", np.where(r < 0.80, "Partially Approved", "Approved")),
                      np.where(r < 0.88, "Approved", np.where(r < 0.97, "Partially Approved", "Rejected")))
    c["claim_status"] = status
    c["settled_amount"] = np.where(status == "Approved", c.total_claim_amount,
                           np.where(status == "Partially Approved",
                                    (c.total_claim_amount * rng.uniform(0.4, 0.8, len(c))).round(-2), 0))

    # ---------------- data-quality issues (realistic) ---------------- #
    n = len(c)
    c["incident_hour"] = c["incident_hour"].astype("Int64")
    c.loc[rng.random(n) < 0.01, "incident_hour"] = pd.NA            # time not captured
    bad = rng.random(n) < 0.002                                      # report date keyed before incident
    c.loc[bad, "report_date"] = c.loc[bad, "incident_date"] - pd.to_timedelta(rng.integers(1, 5, bad.sum()), "D")

    c = c.sort_values("claim_id").reset_index(drop=True)
    return c


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    customers = make_customers()
    agents = make_agents()
    garages = make_garages()
    policies = make_policies(customers, agents)
    claims = make_claims(customers, agents, garages, policies)

    def public(df: pd.DataFrame) -> pd.DataFrame:
        return df[[col for col in df.columns if not col.startswith("_")]]

    for name, df in [("customers", customers), ("agents", agents), ("garages", garages),
                     ("policies", policies), ("claims", claims)]:
        out = public(df).copy()
        for col in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[col]):
                out[col] = pd.to_datetime(out[col]).dt.strftime("%Y-%m-%d")
        out.to_csv(OUT_DIR / f"{name}.csv", index=False)
        print(f"{name:<10} {len(out):>7,} rows")

    print(f"\nFraud rate: {claims.is_fraud.mean():.2%}  |  "
          f"claims {claims.incident_date.min().date()} -> {claims.incident_date.max().date()}")


if __name__ == "__main__":
    main()
