-- =====================================================================
-- 04_red_flag_rules.sql
-- (a) v_claim_base: one clean, denormalised row per claim
-- (b) claim_red_flags: the "business-as-usual" rules engine that a
--     Special Investigation Unit (SIU) typically uses today. Each rule is
--     a 0/1 flag; red_flag_score = number of rules triggered.
--     This is the BASELINE the ML model has to beat.
-- =====================================================================

DROP VIEW IF EXISTS v_claim_base;
CREATE VIEW v_claim_base AS
SELECT
    c.claim_id,
    c.policy_id,
    p.customer_id,
    p.agent_id,
    c.garage_id,
    c.incident_date,
    c.report_date,
    CAST(strftime('%Y', c.incident_date) AS INTEGER)                     AS incident_year,
    c.claim_type,
    c.incident_severity,
    c.claim_channel,
    c.incident_city,
    cu.city                                                              AS customer_city,
    c.incident_hour,
    c.police_report_filed,
    c.witness_count,
    c.num_vehicles_involved,
    c.claimant_has_lawyer,
    c.vehicle_claim_amount,
    c.injury_claim_amount,
    c.property_claim_amount,
    c.total_claim_amount,
    p.policy_type,
    p.vehicle_make,
    p.vehicle_segment,
    p.fuel_type,
    p.vehicle_age_years,
    p.idv,
    p.annual_premium,
    p.ncb_percent,
    p.zero_dep_addon,
    p.voluntary_deductible,
    p.is_new_business,
    p.is_renewal,
    p.policy_start_date,
    p.policy_end_date,
    cu.age                                                               AS customer_age,
    cu.gender,
    cu.occupation,
    cu.annual_income,
    cu.customer_since,
    a.channel                                                            AS sales_channel,
    g.is_network_garage,
    g.empanelled_since                                                   AS garage_empanelled_since,
    julianday(c.incident_date) - julianday(p.policy_start_date)          AS days_policy_to_incident,
    julianday(p.policy_end_date) - julianday(c.incident_date)            AS days_incident_to_expiry,
    -- negative delays are data-entry errors -> NULL (flagged separately)
    CASE WHEN c.report_date >= c.incident_date
         THEN julianday(c.report_date) - julianday(c.incident_date) END  AS report_delay_days,
    CASE WHEN c.report_date <  c.incident_date THEN 1 ELSE 0 END         AS dq_report_before_incident,
    c.is_fraud
FROM claims c
JOIN policies  p  ON c.policy_id   = p.policy_id
JOIN customers cu ON p.customer_id = cu.customer_id
JOIN agents    a  ON p.agent_id    = a.agent_id
LEFT JOIN garages g ON c.garage_id = g.garage_id;


DROP VIEW IF EXISTS claim_red_flags;
CREATE VIEW claim_red_flags AS
WITH prior AS (
    SELECT claim_id,
           COUNT(*) OVER (
               PARTITION BY customer_id
               ORDER BY julianday(incident_date)
               RANGE BETWEEN 365 PRECEDING AND 1 PRECEDING
           ) AS cust_prior_claims_365d
    FROM v_claim_base
),
flags AS (
    SELECT b.claim_id,
           b.incident_year,
           b.is_fraud,
           b.total_claim_amount,
           CASE WHEN b.days_policy_to_incident <= 30 THEN 1 ELSE 0 END                AS rf_early_claim,
           CASE WHEN b.days_incident_to_expiry <= 20 THEN 1 ELSE 0 END                AS rf_near_expiry,
           CASE WHEN b.report_delay_days > 7 THEN 1 ELSE 0 END                        AS rf_late_report,
           CASE WHEN b.incident_hour BETWEEN 0 AND 4 THEN 1 ELSE 0 END                AS rf_night_incident,
           CASE WHEN b.police_report_filed = 0
                 AND b.incident_severity <> 'Minor' THEN 1 ELSE 0 END                 AS rf_no_police_report,
           CASE WHEN b.idv > 0 AND b.total_claim_amount > 0.5 * b.idv
                 AND b.incident_severity <> 'Total Loss' THEN 1 ELSE 0 END            AS rf_high_claim_vs_idv,
           CASE WHEN pr.cust_prior_claims_365d >= 1 THEN 1 ELSE 0 END                 AS rf_repeat_claimant,
           CASE WHEN b.claimant_has_lawyer = 1 THEN 1 ELSE 0 END                      AS rf_lawyer_involved,
           CASE WHEN b.claim_type = 'Theft' AND b.vehicle_age_years >= 7 THEN 1 ELSE 0 END AS rf_old_vehicle_theft,
           CASE WHEN b.is_new_business = 1 THEN 1 ELSE 0 END                          AS rf_new_business
    FROM v_claim_base b
    JOIN prior pr ON b.claim_id = pr.claim_id
)
SELECT *,
       rf_early_claim + rf_near_expiry + rf_late_report + rf_night_incident
     + rf_no_police_report + rf_high_claim_vs_idv + rf_repeat_claimant
     + rf_lawyer_involved + rf_old_vehicle_theft + rf_new_business AS red_flag_score
FROM flags;
