-- =====================================================================
-- 01_schema.sql
-- Relational schema for the motor-insurance claims database.
-- Dialect: SQLite (ANSI-style; ports to PostgreSQL / MySQL with minor
-- changes to date functions).
--
--   customers 1──* policies *──1 agents
--                     │
--                     1
--                     │
--                     * claims *──1 garages
-- =====================================================================

DROP TABLE IF EXISTS claims;
DROP TABLE IF EXISTS policies;
DROP TABLE IF EXISTS garages;
DROP TABLE IF EXISTS agents;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    customer_id      TEXT PRIMARY KEY,
    age              INTEGER NOT NULL,
    gender           TEXT,
    occupation       TEXT,
    annual_income    REAL,                 -- nullable: not always captured at onboarding
    city             TEXT,
    state            TEXT,
    customer_since   DATE
);

CREATE TABLE agents (
    agent_id         TEXT PRIMARY KEY,
    channel          TEXT,                 -- Agent / Broker / Dealer / Online / Bancassurance
    city             TEXT,
    state            TEXT,
    years_experience INTEGER
);

CREATE TABLE garages (
    garage_id         TEXT PRIMARY KEY,
    garage_name       TEXT,
    city              TEXT,
    state             TEXT,
    is_network_garage INTEGER,             -- 1 = cashless network partner
    empanelled_since  DATE
);

CREATE TABLE policies (
    policy_id            TEXT PRIMARY KEY,
    customer_id          TEXT NOT NULL REFERENCES customers(customer_id),
    agent_id             TEXT NOT NULL REFERENCES agents(agent_id),
    vehicle_make         TEXT,
    vehicle_model        TEXT,
    vehicle_segment      TEXT,
    fuel_type            TEXT,
    vehicle_age_years    INTEGER,
    policy_type          TEXT,             -- Comprehensive / Third Party
    zero_dep_addon       INTEGER,
    idv                  REAL,             -- Insured Declared Value (0 for Third Party)
    ncb_percent          INTEGER,          -- No-Claim Bonus
    voluntary_deductible INTEGER,
    annual_premium       REAL,
    policy_start_date    DATE,
    policy_end_date      DATE,
    is_renewal           INTEGER,
    is_new_business      INTEGER           -- ported in from another insurer
);

CREATE TABLE claims (
    claim_id              TEXT PRIMARY KEY,
    policy_id             TEXT NOT NULL REFERENCES policies(policy_id),
    garage_id             TEXT REFERENCES garages(garage_id),   -- NULL for theft / injury-only
    incident_date         DATE NOT NULL,
    incident_hour         INTEGER,
    report_date           DATE NOT NULL,
    claim_type            TEXT,
    incident_severity     TEXT,
    incident_city         TEXT,
    police_report_filed   INTEGER,
    witness_count         INTEGER,
    num_vehicles_involved INTEGER,
    claimant_has_lawyer   INTEGER,
    claim_channel         TEXT,
    is_fraud              INTEGER,         -- label: confirmed by Special Investigation Unit (SIU)
    vehicle_claim_amount  REAL,
    injury_claim_amount   REAL,
    property_claim_amount REAL,
    total_claim_amount    REAL,
    claim_status          TEXT,            -- POST-decision field: never used as a model feature
    settled_amount        REAL             -- POST-decision field: never used as a model feature
);

CREATE INDEX idx_policies_customer ON policies(customer_id);
CREATE INDEX idx_policies_agent    ON policies(agent_id);
CREATE INDEX idx_claims_policy     ON claims(policy_id);
CREATE INDEX idx_claims_garage     ON claims(garage_id, report_date);
CREATE INDEX idx_claims_incident   ON claims(incident_date);
