# Power BI Dashboard Guide

The dashboard is a **Power BI Project** (`Insurance_Fraud_Dashboard.pbip`): Power BI Desktop's text-based format, where the data model is stored as TMDL files and the report as JSON files. It is generated from code by `src/build_powerbi_project.py`, so it can be reviewed in Git and rebuilt on any machine.

## 1. Open it (2 minutes)

1. Make sure `powerbi/data/*.csv` exist. They are in the repo, and `python run_pipeline.py` rebuilds them.
2. Point the dashboard at your copy of the data: `python src/build_powerbi_project.py --set-data-folder`
3. In **Power BI Desktop** (December 2025 release or later): **File → Open → `powerbi/Insurance_Fraud_Dashboard.pbip`**
4. Click **Refresh now** in the yellow banner (or **Home → Refresh**). Loading takes about 10 seconds.
5. To get a single file to share: **File → Save as → Power BI file (*.pbix)**

**Why step 2?** Power Query needs an absolute path to the CSV folder, which differs on every machine. It's stored in the `DataFolder` parameter (`definition/expressions.tmdl`, not committed). You can also set it in Power BI: **Transform data → Edit parameters → DataFolder**, using the full path of `powerbi\data\` with the trailing backslash.

> `python src/build_powerbi_project.py --overwrite` regenerates the whole model and report from code and discards edits saved from Power BI Desktop.

## 2. What's inside

### Data model: star schema

| Table | Type | Rows | Joined to `fact_claims` on |
|---|---|---|---|
| `fact_claims` | Fact: one row per claim, with red flags and 2025 model scores | 16,810 | – |
| `dim_policy` | Dimension | 14,384 | `policy_id` |
| `dim_customer` | Dimension | 11,432 | `customer_id` |
| `dim_agent` | Dimension | 150 | `agent_id` |
| `dim_garage` | Dimension | 320 | `garage_id` (blank for theft and injury claims) |
| `Date` | Calculated calendar 2022–2025, marked as date table | 1,461 | `incident_date` |
| `model_comparison`, `capacity_curve`, `feature_importance` | Standalone metric tables | 5 / 150 / 51 | – |
| `Recovery Rate`, `Investigation Cost`, `Friction Cost` | What-if parameters | 15 / 20 / 11 | – |
| `_Measures` | Holds all 35 report measures, in display folders | – | – |

All relationships are one-to-many, single direction, from the dimension to the fact. Implicit measures are switched off (`discourageImplicitMeasures`), so every number on the report comes from an explicit DAX measure. The DAX is explained in [DAX_measures.md](DAX_measures.md).

### Report pages

| Page | For | Visuals |
|---|---|---|
| **Executive Overview** | Leadership | Year slicer; cards for Total Claims, Fraud Rate, Total / Fraud Claimed (₹ Cr), Fraud Leakage (₹ Cr); monthly fraud rate with 3-month rolling line; fraud rate by claim type |
| **Fraud Patterns** | Claims managers | Fraud rate by days since policy start (H1) and by reporting delay (H2); by sales channel; by red-flag score; severity table with lift |
| **Garage & Agent Network** | SIU head | Garages ranked by fraud rate with RANKX rank and a "Review" flag; agents with lift vs portfolio; fraud rate by city |
| **Model Impact** | CFO / business case | What-if slicers for recovery rate, investigation cost and friction; model vs rules net benefit and uplift; value recall and hit rate; capacity curve; model comparison table; top drivers |
| **SIU Investigation Queue** | Investigators, daily | Risk-band slicer; queue size and expected loss; table of the 505 flagged 2025 claims sorted by priority, with reason codes |

Every page header says the data is synthetic.

## 3. Checkpoint values

These were checked with DAX queries against the refreshed model in Power BI Desktop 2.150 and match `reports/model_results.json` and `reports/sql_insights.md`. If your numbers differ, the data or a measure has changed.

| Measure | Value (no filters, default sliders) |
|---|---|
| Total Claims | 16,810 |
| Fraud Rate | 10.2% |
| Total Claimed (Cr) | 273.89 |
| Fraud Claimed (Cr) | 37.71 |
| Fraud Leakage (Cr) | 12.69 |
| Avg Claim Amount | 1,62,935 |
| Model Flagged / Rules Flagged | 505 / 505 |
| Model Hit Rate / Rules Hit Rate | 35.6% / 31.1% |
| Model Value Recall / Rules Value Recall | 74.1% / 39.9% |
| Model Net Benefit (Cr) / Rules Net Benefit (Cr) | 4.41 / 1.99 |
| Net Benefit Uplift (Cr) | 2.41 |
| Queue Expected Loss (Cr) | 6.96 |
| Garage Risk Rank 1 | G738 New India Motor Works, 51.7% |
| Fraud Rate by year | 2022 12.2% · 2023 9.7% · 2024 9.9% · 2025 9.6% |

**Stress test with the what-if slicers (Model Impact page):**

| Recovery rate | Friction cost | Model net benefit | Rules net benefit |
|---|---|---|---|
| 60% (default) | ₹15,000 (default) | ₹4.41 Cr | ₹1.99 Cr |
| 40% | ₹15,000 | ₹2.69 Cr | ₹1.07 Cr |
| 40% | ₹20,000 | ₹2.53 Cr | ₹0.90 Cr |

The model stays well ahead even under pessimistic assumptions, because its advantage comes from ranking, not from the assumptions.

## 4. Optional enhancements in Power BI Desktop

Formatting that is quicker to apply in Power BI Desktop than in code:

1. **Colour the queue by risk.** On the SIU Investigation Queue table: select `risk_band` → **Conditional formatting → Background colour → Format style: Field value → What field: `_Measures[Risk Band Colour]`**.
2. **Show a reference line.** On the Fraud Patterns column charts: **Analytics pane → Constant line = 0.102**, labelled "Portfolio average".
3. **Tooltips.** Add `Fraud Rate Lift` to the tooltips of the bar charts.
4. **Mobile layout.** **View → Mobile layout** and drag the cards and queue table onto the phone canvas.

## 5. Building it manually

The same dashboard can be built from a blank report, without the generator script:

1. **Get data → Text/CSV** for each file in `powerbi/data/`. In Power Query, check the column types (dates as Date, amounts as Decimal, flags as Whole number).
2. **Model view:** drag `dim_*[x_id]` onto `fact_claims[x_id]` for the four dimensions. Check they're one-to-many and single direction.
3. **Modeling → New table:** paste the `Date` DAX from [DAX_measures.md](DAX_measures.md), then **Mark as date table** and relate `Date[Date]` to `fact_claims[incident_date]`.
4. **Home → Enter data** with one column to create `_Measures`, then add the measures from DAX_measures.md one by one.
5. **Modeling → New parameter → Numeric range** for the three what-if parameters.
6. **View → Themes → Browse for themes → `fraud_dashboard_theme.json`.**
7. Build the five pages from section 2, then compare your numbers with section 3.
