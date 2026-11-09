-- =====================================================================
-- 03_exploratory_analysis.sql
-- Business questions answered in SQL before any modelling.
-- Each query starts with a "-- Q<n>:" header. build_database.py runs them
-- and saves results to reports/sql_insights.md.
-- Techniques: CTEs, CASE bucketing, window functions (RANK, rolling
-- averages, LAG), HAVING filters, self-joins.
-- =====================================================================

-- Q1: Portfolio overview: how big is the fraud problem?
SELECT COUNT(*)                                             AS total_claims,
       SUM(is_fraud)                                        AS confirmed_fraud_claims,
       ROUND(100.0 * AVG(is_fraud), 2)                      AS fraud_rate_pct,
       ROUND(SUM(total_claim_amount) / 1e7, 2)              AS total_claimed_cr,
       ROUND(SUM(CASE WHEN is_fraud = 1 THEN total_claim_amount END) / 1e7, 2) AS fraud_claimed_cr,
       ROUND(SUM(CASE WHEN is_fraud = 1 THEN settled_amount END) / 1e7, 2)     AS fraud_paid_out_cr
FROM claims;

-- Q2: Fraud rate by claim type and severity
SELECT claim_type,
       incident_severity,
       COUNT(*)                                  AS claims,
       ROUND(100.0 * AVG(is_fraud), 1)           AS fraud_rate_pct,
       ROUND(AVG(total_claim_amount))            AS avg_claim_inr
FROM claims
GROUP BY claim_type, incident_severity
HAVING COUNT(*) >= 50
ORDER BY fraud_rate_pct DESC;

-- Q3: Do claims made soon after buying the policy carry more fraud?
WITH t AS (
    SELECT c.is_fraud,
           julianday(c.incident_date) - julianday(p.policy_start_date) AS days_since_start
    FROM claims c JOIN policies p ON c.policy_id = p.policy_id
)
SELECT CASE WHEN days_since_start <= 30  THEN '1. 0-30 days'
            WHEN days_since_start <= 90  THEN '2. 31-90 days'
            WHEN days_since_start <= 180 THEN '3. 91-180 days'
            WHEN days_since_start <= 330 THEN '4. 181-330 days'
            ELSE '5. Last 35 days of policy' END AS policy_age_bucket,
       COUNT(*)                                AS claims,
       ROUND(100.0 * AVG(is_fraud), 1)         AS fraud_rate_pct
FROM t
GROUP BY 1
ORDER BY 1;

-- Q4: Reporting delay vs fraud
WITH t AS (
    SELECT is_fraud, julianday(report_date) - julianday(incident_date) AS delay
    FROM claims
    WHERE report_date >= incident_date          -- exclude data-entry errors (see DQ checks)
)
SELECT CASE WHEN delay <= 1  THEN '1. Same/next day'
            WHEN delay <= 7  THEN '2. 2-7 days'
            WHEN delay <= 30 THEN '3. 8-30 days'
            ELSE '4. 30+ days' END AS report_delay,
       COUNT(*)                        AS claims,
       ROUND(100.0 * AVG(is_fraud), 1) AS fraud_rate_pct
FROM t
GROUP BY 1
ORDER BY 1;

-- Q5: Night-time incidents without a police report (major/total-loss claims only)
SELECT CASE WHEN incident_hour BETWEEN 0 AND 4 THEN 'Night (00-05)' ELSE 'Day/Evening' END AS time_of_incident,
       CASE WHEN police_report_filed = 1 THEN 'Police report' ELSE 'No police report' END  AS police_report,
       COUNT(*)                        AS claims,
       ROUND(100.0 * AVG(is_fraud), 1) AS fraud_rate_pct
FROM claims
WHERE incident_severity IN ('Major', 'Total Loss') AND incident_hour IS NOT NULL
GROUP BY 1, 2
ORDER BY fraud_rate_pct DESC;

-- Q6: Fraud by sales channel and new vs existing business
SELECT a.channel,
       CASE WHEN p.is_new_business = 1 THEN 'Ported-in (new)' ELSE 'Existing/Renewal' END AS business_type,
       COUNT(*)                          AS claims,
       ROUND(100.0 * AVG(c.is_fraud), 1) AS fraud_rate_pct
FROM claims c
JOIN policies p ON c.policy_id = p.policy_id
JOIN agents   a ON p.agent_id  = a.agent_id
GROUP BY 1, 2
ORDER BY 1, 2;

-- Q7: Top 10 garages by fraud rate (min 25 claims), ranked with a window function
WITH g AS (
    SELECT gr.garage_id, gr.garage_name, gr.city, gr.is_network_garage,
           COUNT(*)                             AS claims,
           SUM(c.is_fraud)                      AS fraud_claims,
           ROUND(100.0 * AVG(c.is_fraud), 1)    AS fraud_rate_pct,
           ROUND(SUM(CASE WHEN c.is_fraud = 1 THEN c.total_claim_amount END) / 1e5, 1) AS fraud_amount_lakh
    FROM claims c JOIN garages gr ON c.garage_id = gr.garage_id
    GROUP BY gr.garage_id
    HAVING COUNT(*) >= 25
)
SELECT RANK() OVER (ORDER BY fraud_rate_pct DESC) AS rnk, *
FROM g
ORDER BY rnk
LIMIT 10;

-- Q8: Agents whose fraud rate is more than 2x the portfolio average (min 20 claims)
WITH portfolio AS (SELECT AVG(is_fraud) AS avg_rate FROM claims),
agent_stats AS (
    SELECT p.agent_id, a.channel, a.city,
           COUNT(*)          AS claims,
           AVG(c.is_fraud)   AS fraud_rate
    FROM claims c
    JOIN policies p ON c.policy_id = p.policy_id
    JOIN agents   a ON p.agent_id  = a.agent_id
    GROUP BY p.agent_id
    HAVING COUNT(*) >= 20
)
SELECT s.agent_id, s.channel, s.city, s.claims,
       ROUND(100.0 * s.fraud_rate, 1)            AS fraud_rate_pct,
       ROUND(s.fraud_rate / pf.avg_rate, 1)      AS x_portfolio_avg
FROM agent_stats s CROSS JOIN portfolio pf
WHERE s.fraud_rate > 2 * pf.avg_rate
ORDER BY x_portfolio_avg DESC;

-- Q9: Monthly trend with 3-month rolling fraud rate and month-on-month change
WITH m AS (
    SELECT strftime('%Y-%m', incident_date) AS month,
           COUNT(*)        AS claims,
           SUM(is_fraud)   AS fraud_claims
    FROM claims
    GROUP BY 1
)
SELECT month, claims, fraud_claims,
       ROUND(100.0 * fraud_claims / claims, 1) AS fraud_rate_pct,
       ROUND(100.0 * SUM(fraud_claims) OVER w3 / SUM(claims) OVER w3, 1) AS rolling_3m_fraud_rate_pct,
       claims - LAG(claims) OVER (ORDER BY month) AS mom_change_in_claims
FROM m
WINDOW w3 AS (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)
ORDER BY month;

-- Q10: Repeat claimants: does a recent prior claim raise fraud risk?
WITH cc AS (
    SELECT c.claim_id, c.is_fraud, p.customer_id,
           julianday(c.incident_date) AS d
    FROM claims c JOIN policies p ON c.policy_id = p.policy_id
),
prior AS (
    SELECT a.claim_id, a.is_fraud,
           (SELECT COUNT(*) FROM cc b
             WHERE b.customer_id = a.customer_id
               AND b.d <  a.d
               AND b.d >= a.d - 365) AS prior_claims_12m
    FROM cc a
)
SELECT CASE WHEN prior_claims_12m >= 2 THEN '2+' ELSE CAST(prior_claims_12m AS TEXT) END AS prior_claims_last_12m,
       COUNT(*)                        AS claims,
       ROUND(100.0 * AVG(is_fraud), 1) AS fraud_rate_pct
FROM prior
GROUP BY 1
ORDER BY 1;

-- Q11: City view: where is fraud money leaking?
SELECT cu.city,
       COUNT(*)                                                       AS claims,
       ROUND(100.0 * AVG(c.is_fraud), 1)                              AS fraud_rate_pct,
       ROUND(SUM(CASE WHEN c.is_fraud = 1 THEN c.settled_amount END) / 1e5, 1) AS fraud_paid_lakh
FROM claims c
JOIN policies  p  ON c.policy_id   = p.policy_id
JOIN customers cu ON p.customer_id = cu.customer_id
GROUP BY cu.city
ORDER BY fraud_paid_lakh DESC
LIMIT 10;
