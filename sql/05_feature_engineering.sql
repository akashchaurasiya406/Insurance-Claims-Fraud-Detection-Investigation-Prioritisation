-- =====================================================================
-- 05_feature_engineering.sql
-- Builds the modelling table `claim_features`: one row per claim, with
-- point-in-time-correct features only.
--
-- Leakage controls
--   * claim_status and settled_amount (decided AFTER investigation) are
--     excluded.
--   * Garage / agent "historical fraud rate" only uses claims reported at
--     least 90 days before the current claim. 90 days is the assumed time
--     an SIU investigation takes to close, so at scoring time we would
--     really know these outcomes.
--   * Rates are smoothed toward a 10% prior (weight = 10 claims) so a
--     garage with 1 claim and 1 fraud doesn't get a 100% rate.
-- =====================================================================

DROP TABLE IF EXISTS claim_features;
CREATE TABLE claim_features AS
WITH cust_hist AS (
    SELECT claim_id,
           COUNT(*) OVER (PARTITION BY customer_id ORDER BY julianday(incident_date)
                          RANGE BETWEEN 365 PRECEDING AND 1 PRECEDING)          AS cust_prior_claims_365d,
           COUNT(*) OVER (PARTITION BY customer_id ORDER BY julianday(incident_date)
                          RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)    AS cust_prior_claims_total,
           COUNT(*) OVER (PARTITION BY policy_id ORDER BY julianday(incident_date)
                          RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)    AS policy_prior_claims
    FROM v_claim_base
),
garage_hist AS (
    SELECT c.claim_id,
           (SELECT COUNT(*) FROM claims c2
             WHERE c2.garage_id = c.garage_id
               AND c2.report_date <= date(c.report_date, '-90 day'))           AS garage_prior_claims,
           (SELECT COALESCE(SUM(c2.is_fraud), 0) FROM claims c2
             WHERE c2.garage_id = c.garage_id
               AND c2.report_date <= date(c.report_date, '-90 day'))           AS garage_prior_frauds
    FROM claims c
    WHERE c.garage_id IS NOT NULL
),
agent_hist AS (
    SELECT c.claim_id,
           (SELECT COUNT(*) FROM claims c2 JOIN policies p2 ON c2.policy_id = p2.policy_id
             WHERE p2.agent_id = p.agent_id
               AND c2.report_date <= date(c.report_date, '-90 day'))           AS agent_prior_claims,
           (SELECT COALESCE(SUM(c2.is_fraud), 0) FROM claims c2 JOIN policies p2 ON c2.policy_id = p2.policy_id
             WHERE p2.agent_id = p.agent_id
               AND c2.report_date <= date(c.report_date, '-90 day'))           AS agent_prior_frauds
    FROM claims c JOIN policies p ON c.policy_id = p.policy_id
)
SELECT
    b.claim_id,
    b.incident_date,
    b.incident_year,
    b.is_fraud,                                                   -- target

    -- claim characteristics
    b.claim_type,
    b.incident_severity,
    b.claim_channel,
    COALESCE(b.incident_hour, -1)                                 AS incident_hour,
    CASE WHEN b.incident_hour IS NULL THEN 1 ELSE 0 END           AS incident_hour_missing,
    CASE WHEN b.incident_hour BETWEEN 0 AND 4 THEN 1 ELSE 0 END   AS is_night_incident,
    CAST(strftime('%w', b.incident_date) AS INTEGER) IN (0, 6)    AS is_weekend,
    b.police_report_filed,
    b.witness_count,
    b.num_vehicles_involved,
    b.claimant_has_lawyer,
    CASE WHEN b.incident_city <> b.customer_city THEN 1 ELSE 0 END AS incident_outside_home_city,

    -- timing
    b.days_policy_to_incident,
    b.days_incident_to_expiry,
    b.report_delay_days,
    b.dq_report_before_incident,

    -- money
    b.total_claim_amount,
    b.vehicle_claim_amount,
    b.injury_claim_amount,
    b.property_claim_amount,
    CASE WHEN b.idv > 0 THEN b.total_claim_amount / b.idv END             AS claim_to_idv_ratio,
    b.total_claim_amount / NULLIF(b.annual_premium, 0)                    AS claim_to_premium_ratio,
    b.total_claim_amount / NULLIF(b.annual_income, 0)                     AS claim_to_income_ratio,

    -- policy & vehicle
    b.policy_type,
    b.vehicle_segment,
    b.fuel_type,
    b.vehicle_age_years,
    b.idv,
    b.annual_premium,
    b.ncb_percent,
    b.zero_dep_addon,
    b.voluntary_deductible,
    b.is_new_business,
    b.is_renewal,
    b.sales_channel,

    -- customer
    b.customer_age,
    b.gender,
    b.occupation,
    b.annual_income,
    CASE WHEN b.annual_income IS NULL THEN 1 ELSE 0 END                   AS income_missing,
    (julianday(b.incident_date) - julianday(b.customer_since)) / 365.25   AS customer_tenure_years,
    ch.cust_prior_claims_365d,
    ch.cust_prior_claims_total,
    ch.policy_prior_claims,

    -- garage (NULL garage = theft / injury-only claim)
    CASE WHEN b.garage_id IS NULL THEN 0 ELSE 1 END                       AS has_garage,
    COALESCE(b.is_network_garage, 0)                                      AS is_network_garage,
    (julianday(b.incident_date) - julianday(b.garage_empanelled_since)) / 365.25 AS garage_tenure_years,
    COALESCE(gh.garage_prior_claims, 0)                                   AS garage_prior_claims,
    (COALESCE(gh.garage_prior_frauds, 0) + 1.0) / (COALESCE(gh.garage_prior_claims, 0) + 10.0) AS garage_hist_fraud_rate,

    -- agent
    ah.agent_prior_claims,
    (ah.agent_prior_frauds + 1.0) / (ah.agent_prior_claims + 10.0)       AS agent_hist_fraud_rate,

    -- rules-engine output (baseline), kept for comparison
    rf.red_flag_score
FROM v_claim_base b
JOIN cust_hist        ch ON b.claim_id = ch.claim_id
JOIN agent_hist       ah ON b.claim_id = ah.claim_id
LEFT JOIN garage_hist gh ON b.claim_id = gh.claim_id
JOIN claim_red_flags  rf ON b.claim_id = rf.claim_id;
