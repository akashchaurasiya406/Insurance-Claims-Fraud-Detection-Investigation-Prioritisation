-- =====================================================================
-- 02_data_quality_checks.sql
-- Validation run before any analysis. Each query returns one row:
-- check_name | issue_count | total_rows.
-- build_database.py runs every statement and writes
-- reports/data_quality_report.md.
-- =====================================================================

-- 1. Duplicate claim IDs
SELECT 'Duplicate claim_id' AS check_name,
       COUNT(*) - COUNT(DISTINCT claim_id) AS issue_count,
       COUNT(*) AS total_rows
FROM claims;

-- 2. Orphan claims (policy does not exist)
SELECT 'Claims with no matching policy' AS check_name,
       SUM(CASE WHEN p.policy_id IS NULL THEN 1 ELSE 0 END) AS issue_count,
       COUNT(*) AS total_rows
FROM claims c LEFT JOIN policies p ON c.policy_id = p.policy_id;

-- 3. Orphan policies (customer does not exist)
SELECT 'Policies with no matching customer' AS check_name,
       SUM(CASE WHEN cu.customer_id IS NULL THEN 1 ELSE 0 END) AS issue_count,
       COUNT(*) AS total_rows
FROM policies p LEFT JOIN customers cu ON p.customer_id = cu.customer_id;

-- 4. Report date earlier than incident date (data-entry error)
SELECT 'Report date before incident date' AS check_name,
       SUM(CASE WHEN report_date < incident_date THEN 1 ELSE 0 END) AS issue_count,
       COUNT(*) AS total_rows
FROM claims;

-- 5. Incident outside policy cover period
SELECT 'Incident outside policy period' AS check_name,
       SUM(CASE WHEN c.incident_date < p.policy_start_date
                  OR c.incident_date > p.policy_end_date THEN 1 ELSE 0 END) AS issue_count,
       COUNT(*) AS total_rows
FROM claims c JOIN policies p ON c.policy_id = p.policy_id;

-- 6. Missing incident hour
SELECT 'Missing incident_hour' AS check_name,
       SUM(CASE WHEN incident_hour IS NULL THEN 1 ELSE 0 END) AS issue_count,
       COUNT(*) AS total_rows
FROM claims;

-- 7. Missing customer income
SELECT 'Missing annual_income' AS check_name,
       SUM(CASE WHEN annual_income IS NULL THEN 1 ELSE 0 END) AS issue_count,
       COUNT(*) AS total_rows
FROM customers;

-- 8. Claim amount components do not add up
SELECT 'Total claim amount mismatch' AS check_name,
       SUM(CASE WHEN ABS(total_claim_amount
                 - (vehicle_claim_amount + injury_claim_amount + property_claim_amount)) > 1
                THEN 1 ELSE 0 END) AS issue_count,
       COUNT(*) AS total_rows
FROM claims;

-- 9. Vehicle claim exceeds insured value (comprehensive policies)
SELECT 'Vehicle claim above IDV' AS check_name,
       SUM(CASE WHEN p.idv > 0 AND c.vehicle_claim_amount > p.idv THEN 1 ELSE 0 END) AS issue_count,
       COUNT(*) AS total_rows
FROM claims c JOIN policies p ON c.policy_id = p.policy_id;

-- 10. Own-damage claim on a third-party-only policy (coverage mismatch)
SELECT 'Own-damage claim on Third Party policy' AS check_name,
       SUM(CASE WHEN p.policy_type = 'Third Party'
                 AND c.claim_type <> 'Third Party Injury' THEN 1 ELSE 0 END) AS issue_count,
       COUNT(*) AS total_rows
FROM claims c JOIN policies p ON c.policy_id = p.policy_id;

-- 11. Invalid ranges
SELECT 'Out-of-range values (hour, age, amount)' AS check_name,
       (SELECT COUNT(*) FROM claims WHERE incident_hour NOT BETWEEN 0 AND 23
                                       OR total_claim_amount <= 0)
     + (SELECT COUNT(*) FROM customers WHERE age NOT BETWEEN 18 AND 100) AS issue_count,
       (SELECT COUNT(*) FROM claims) AS total_rows;
