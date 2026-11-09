# DAX Measures

Create a blank table called **`_Measures`** (Home → Enter data → name it `_Measures` → Load) and put every measure in it. That keeps them in one place in the Fields pane.

The **format** column is what to set under *Measure tools → Format*.

---

## 0. Date table (Modeling → New table)

```DAX
Date =
ADDCOLUMNS (
    CALENDAR ( DATE ( 2022, 1, 1 ), DATE ( 2025, 12, 31 ) ),
    "Year", YEAR ( [Date] ),
    "Quarter", "Q" & QUARTER ( [Date] ),
    "Month Num", MONTH ( [Date] ),
    "Month", FORMAT ( [Date], "MMM" ),
    "Year Month", FORMAT ( [Date], "yyyy-MM" )
)
```
Then: *Table tools → Mark as date table → Date*. Relate `Date[Date]` → `fact_claims[incident_date]`.

---

## 1. Portfolio KPIs

| Measure | DAX | Format |
|---|---|---|
| Total Claims | `Total Claims = COUNTROWS ( fact_claims )` | Whole number, `,` |
| Fraud Claims | `Fraud Claims = CALCULATE ( [Total Claims], fact_claims[is_fraud] = 1 )` | Whole number |
| Fraud Rate | `Fraud Rate = DIVIDE ( [Fraud Claims], [Total Claims] )` | Percentage, 1 dp |
| Total Claimed (Cr) | `Total Claimed (Cr) = DIVIDE ( SUM ( fact_claims[total_claim_amount] ), 1e7 )` | Custom `"₹"0.0" Cr"` |
| Fraud Claimed (Cr) | `Fraud Claimed (Cr) = CALCULATE ( [Total Claimed (Cr)], fact_claims[is_fraud] = 1 )` | Custom `"₹"0.0" Cr"` |
| Fraud Leakage (Cr) | `Fraud Leakage (Cr) = DIVIDE ( CALCULATE ( SUM ( fact_claims[settled_amount] ), fact_claims[is_fraud] = 1 ), 1e7 )` | Custom `"₹"0.00" Cr"` |
| Avg Claim Amount | `Avg Claim Amount = AVERAGE ( fact_claims[total_claim_amount] )` | Custom `"₹"#,##0` |

*Fraud Leakage* is money actually **paid** on claims later confirmed as fraud. It's the headline problem.

## 2. Comparison & trend measures

```DAX
Portfolio Fraud Rate =
CALCULATE ( [Fraud Rate], ALLSELECTED ( fact_claims ) )
```
```DAX
Fraud Rate Lift =
DIVIDE ( [Fraud Rate], [Portfolio Fraud Rate] )          -- format: 0.0"x"
```
```DAX
Fraud Rate 3M Rolling =
CALCULATE (
    [Fraud Rate],
    DATESINPERIOD ( 'Date'[Date], MAX ( 'Date'[Date] ), -3, MONTH )
)
```
```DAX
Fraud Rate YoY Change (pts) =
VAR CurrentRate = [Fraud Rate]
VAR LastYear    = CALCULATE ( [Fraud Rate], SAMEPERIODLASTYEAR ( 'Date'[Date] ) )
RETURN IF ( NOT ISBLANK ( LastYear ), CurrentRate - LastYear )   -- format: +0.0%;-0.0%
```

## 3. Network (garage / agent) measures

```DAX
Garage Fraud Rate (min 25 claims) =
IF ( [Total Claims] >= 25, [Fraud Rate] )
```
```DAX
Garage Risk Rank =
IF (
    HASONEVALUE ( dim_garage[garage_id] ) && [Total Claims] >= 25,
    RANKX (
        FILTER ( ALL ( dim_garage[garage_id] ), CALCULATE ( [Total Claims] ) >= 25 ),
        [Fraud Rate], , DESC, DENSE
    )
)
```
```DAX
High-Risk Garage Flag =
IF ( [Fraud Rate] > 2 * [Portfolio Fraud Rate] && [Total Claims] >= 25, "⚠ Review", "OK" )
```

## 4. What-if parameters (Modeling → New parameter → Numeric range)

| Parameter name | Min | Max | Increment | Default |
|---|---|---|---|---|
| Recovery Rate | 0.3 | 1 | 0.05 | 0.6 |
| Investigation Cost | 1000 | 20000 | 1000 | 5000 |
| Friction Cost | 0 | 50000 | 5000 | 15000 |

Power BI auto-creates `[Recovery Rate Value]`, `[Investigation Cost Value]` and `[Friction Cost Value]`. Tick *Add slicer to this page* on the Model Impact page.

## 5. Model vs rules engine (2025 hold-out)

```DAX
Scored Claims = CALCULATE ( [Total Claims], fact_claims[is_scored] = 1 )

Model Flagged   = CALCULATE ( [Total Claims], fact_claims[flag_for_siu] = 1 )
Rules Flagged   = CALCULATE ( [Total Claims], fact_claims[rules_flag] = 1 )

Model True Frauds = CALCULATE ( [Fraud Claims], fact_claims[flag_for_siu] = 1 )
Rules True Frauds = CALCULATE ( [Fraud Claims], fact_claims[rules_flag] = 1 )

Model Hit Rate = DIVIDE ( [Model True Frauds], [Model Flagged] )            -- %
Rules Hit Rate = DIVIDE ( [Rules True Frauds], [Rules Flagged] )            -- %

Fraud Value 2025 =
CALCULATE ( SUM ( fact_claims[total_claim_amount] ),
            fact_claims[is_fraud] = 1, fact_claims[is_scored] = 1 )

Model Fraud Value Caught =
CALCULATE ( SUM ( fact_claims[total_claim_amount] ),
            fact_claims[is_fraud] = 1, fact_claims[flag_for_siu] = 1 )

Rules Fraud Value Caught =
CALCULATE ( SUM ( fact_claims[total_claim_amount] ),
            fact_claims[is_fraud] = 1, fact_claims[rules_flag] = 1 )

Model Value Recall = DIVIDE ( [Model Fraud Value Caught], [Fraud Value 2025] )   -- %
Rules Value Recall = DIVIDE ( [Rules Fraud Value Caught], [Fraud Value 2025] )   -- %
```

```DAX
Model Net Benefit (Cr) =
VAR Savings     = [Recovery Rate Value] * [Model Fraud Value Caught]
VAR ReviewCost  = [Investigation Cost Value] * [Model Flagged]
VAR FalsePos    = [Model Flagged] - [Model True Frauds]
VAR Friction    = [Friction Cost Value] * FalsePos
RETURN DIVIDE ( Savings - ReviewCost - Friction, 1e7 )          -- "₹"0.00" Cr"
```
```DAX
Rules Net Benefit (Cr) =
VAR Savings     = [Recovery Rate Value] * [Rules Fraud Value Caught]
VAR ReviewCost  = [Investigation Cost Value] * [Rules Flagged]
VAR FalsePos    = [Rules Flagged] - [Rules True Frauds]
VAR Friction    = [Friction Cost Value] * FalsePos
RETURN DIVIDE ( Savings - ReviewCost - Friction, 1e7 )
```
```DAX
Net Benefit Uplift (Cr) = [Model Net Benefit (Cr)] - [Rules Net Benefit (Cr)]
```

## 6. Investigation-queue helpers

```DAX
Queue Size = CALCULATE ( [Total Claims], fact_claims[flag_for_siu] = 1 )

Queue Expected Loss (Cr) =
DIVIDE ( CALCULATE ( SUM ( fact_claims[expected_fraud_loss] ), fact_claims[flag_for_siu] = 1 ), 1e7 )

Risk Band Colour =
SWITCH ( SELECTEDVALUE ( fact_claims[risk_band] ),
    "1-Critical", "#e34948",
    "2-High",     "#eb6834",
    "3-Medium",   "#eda100",
    "#1baf7a" )
```
Use `Risk Band Colour` under *Conditional formatting → Background color → Format style: Field value*.
