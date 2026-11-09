"""
Generate the Power BI dashboard as a Power BI Project (.pbip) from powerbi/data/*.csv.

A .pbip is Power BI Desktop's text-based project format: the semantic model is stored as
TMDL files and the report as PBIR JSON files. Power BI Desktop opens it directly
(File > Open > Insurance_Fraud_Dashboard.pbip), and File > Save as turns it into a .pbix.

    powerbi/
        Insurance_Fraud_Dashboard.pbip                 <- open this in Power BI Desktop
        Insurance_Fraud_Dashboard.SemanticModel/       <- tables, relationships, DAX measures (TMDL)
        Insurance_Fraud_Dashboard.Report/              <- 5 report pages with visuals (PBIR)

What it builds
    * Star schema: fact_claims + dim_policy, dim_customer, dim_agent, dim_garage + a Date table
    * Metric tables: model_comparison, capacity_curve, feature_importance
    * 35 DAX measures (powerbi/DAX_measures.md) in a _Measures table
    * What-if parameters: Recovery Rate, Investigation Cost, Friction Cost
    * 5 pages: Executive Overview, Fraud Patterns, Garage & Agent Network, Model Impact, SIU Investigation Queue

The CSV folder is a Power Query parameter (DataFolder). Its value is machine-specific, so it lives in
definition/expressions.tmdl, which is not committed; --set-data-folder writes it for this machine.

Usage:
    python src/build_powerbi_project.py --set-data-folder  # after cloning: point the dashboard at powerbi/data
    python src/build_powerbi_project.py --overwrite        # regenerate everything (discards Power BI Desktop edits)
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PBI = ROOT / "powerbi"
DATA = PBI / "data"
NAME = "Insurance_Fraud_Dashboard"
SM = PBI / f"{NAME}.SemanticModel"
RP = PBI / f"{NAME}.Report"

T = "\t"
_ns = uuid.UUID("6f1c2a52-6b0e-4b8f-9d55-1f6a3c7e2b10")


def save(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def tag(*parts: str) -> str:
    """Deterministic lineage tag, so regenerating gives stable files."""
    return str(uuid.uuid5(_ns, "/".join(parts)))


def q(name: str) -> str:
    """Quote a TMDL object name when it isn't a plain identifier."""
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else "'" + name.replace("'", "''") + "'"


# --------------------------------------------------------------------------- #
# Semantic model: tables from CSV
# --------------------------------------------------------------------------- #
CSV_TABLES = ["fact_claims", "dim_policy", "dim_customer", "dim_agent", "dim_garage",
              "model_comparison", "capacity_curve", "feature_importance"]
DATE_COLS = {"incident_date", "report_date", "customer_since", "empanelled_since",
             "policy_start_date", "policy_end_date"}
FORMATS = {  # column-level display formats
    "fraud_probability": "0.0%", "precision_at_capacity": "0.0%", "recall_at_capacity": "0.0%",
    "fraud_amount_recall": "0.0%", "roc_auc": "0.000", "pr_auc": "0.000", "importance": "0.0000",
    "std": "0.0000", "total_claim_amount": "#,##0", "expected_fraud_loss": "#,##0",
    "net_benefit": "#,##0", "fraud_amount_caught": "#,##0", "fraud_savings": "#,##0",
    "settled_amount": "#,##0", "vehicle_claim_amount": "#,##0", "injury_claim_amount": "#,##0",
    "property_claim_amount": "#,##0", "idv": "#,##0", "annual_premium": "#,##0", "annual_income": "#,##0",
}
SORT_BY = {("model_comparison", "model"): "display_order"}


def infer_type(name: str, values: pd.Series) -> str:
    if name in DATE_COLS:
        return "date"
    v = values[values != ""]
    if len(v) == 0:
        return "string"
    if v.str.fullmatch(r"-?\d+").all():
        return "int64"
    if v.str.fullmatch(r"-?\d+(\.\d+)?([eE]-?\d+)?").all():
        return "double"
    return "string"


M_TYPE = {"string": "type text", "int64": "Int64.Type", "double": "type number", "date": "type date"}
TMDL_TYPE = {"string": "string", "int64": "int64", "double": "double", "date": "dateTime"}


def csv_table(table: str) -> str:
    df = pd.read_csv(DATA / f"{table}.csv", dtype=str, keep_default_na=False)
    types = {c: infer_type(c, df[c]) for c in df.columns}
    out = [f"table {q(table)}", f"{T}lineageTag: {tag(table)}", ""]
    for c, ty in types.items():
        out += [f"{T}column {q(c)}", f"{T*2}dataType: {TMDL_TYPE[ty]}"]
        if ty == "date":
            out.append(f"{T*2}formatString: Short Date")
        elif c in FORMATS:
            out.append(f"{T*2}formatString: {FORMATS[c]}")
        elif ty == "int64":
            out.append(f"{T*2}formatString: 0")
        out += [f"{T*2}lineageTag: {tag(table, c)}", f"{T*2}summarizeBy: none", f"{T*2}sourceColumn: {c}"]
        if (table, c) in SORT_BY:
            out.append(f"{T*2}sortByColumn: {q(SORT_BY[(table, c)])}")
        out.append("")
        out.append(f"{T*2}annotation SummarizationSetBy = User")
        if ty == "date":
            out.append("")
            out.append(f"{T*2}annotation UnderlyingDateTimeDataType = Date")
        out.append("")
    type_list = ", ".join(f'{{"{c}", {M_TYPE[ty]}}}' for c, ty in types.items())
    m = [
        "let",
        f'    Source = Csv.Document(File.Contents(DataFolder & "{table}.csv"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
        '    Blanks = Table.TransformColumns(Promoted, {}, each if _ = "" then null else _),',
        f'    Typed = Table.TransformColumnTypes(Blanks, {{{type_list}}}, "en-US")',
        "in",
        "    Typed",
    ]
    out += [f"{T}partition {q(table)} = m", f"{T*2}mode: import", f"{T*2}source ="]
    out += [f"{T*4}{line}" for line in m]
    out += ["", f"{T}annotation PBI_ResultType = Table", ""]
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Semantic model: Date table, what-if parameters, measures
# --------------------------------------------------------------------------- #
def date_table() -> str:
    cols = [("Date", "dateTime", "Short Date"), ("Year", "int64", "0"), ("Quarter", "string", None),
            ("Month Num", "int64", "0"), ("Month", "string", None), ("Year Month", "string", None)]
    out = ["table Date", f"{T}lineageTag: {tag('Date')}", f"{T}dataCategory: Time", ""]
    for name, ty, fmt in cols:
        out += [f"{T}column {q(name)}", f"{T*2}dataType: {ty}"]
        if name == "Date":
            out.append(f"{T*2}isKey")
        if fmt:
            out.append(f"{T*2}formatString: {fmt}")
        out += [f"{T*2}lineageTag: {tag('Date', name)}", f"{T*2}summarizeBy: none",
                f"{T*2}isNameInferred", f"{T*2}sourceColumn: [{name}]"]
        if name == "Month":
            out.append(f"{T*2}sortByColumn: 'Month Num'")
        out += ["", f"{T*2}annotation SummarizationSetBy = User"]
        if name == "Date":
            out += ["", f"{T*2}annotation UnderlyingDateTimeDataType = Date"]
        out.append("")
    out += [f"{T}partition Date = calculated", f"{T*2}mode: import", f"{T*2}source ="]
    dax = [
        "ADDCOLUMNS (",
        "    CALENDAR ( DATE ( 2022, 1, 1 ), DATE ( 2025, 12, 31 ) ),",
        '    "Year", YEAR ( [Date] ),',
        '    "Quarter", "Q" & QUARTER ( [Date] ),',
        '    "Month Num", MONTH ( [Date] ),',
        '    "Month", FORMAT ( [Date], "MMM" ),',
        '    "Year Month", FORMAT ( [Date], "yyyy-MM" )',
        ")",
    ]
    out += [f"{T*4}{line}" for line in dax] + [""]
    return "\n".join(out)


WHAT_IF = [  # table/column name, value measure, GENERATESERIES args, default, format
    # whole-number steps / 100, so 0.4 is exactly 0.4 (GENERATESERIES(0.3, 1, 0.05) drifts to 0.39999...)
    ("Recovery Rate", "Recovery Rate Value", "30, 100, 5", "0.6", "0%", "double"),
    ("Investigation Cost", "Investigation Cost Value", "1000, 20000, 1000", "5000", "#,##0", "int64"),
    ("Friction Cost", "Friction Cost Value", "0, 50000, 5000", "15000", "#,##0", "int64"),
]


def what_if_table(name, measure, series, default, fmt, ty) -> str:
    source = (f'SELECTCOLUMNS ( GENERATESERIES ( {series} ), "Value", [Value] / 100 )' if ty == "double"
              else f"GENERATESERIES ( {series} )")
    return "\n".join([
        f"table {q(name)}", f"{T}lineageTag: {tag(name)}", "",
        f"{T}measure {q(measure)} = SELECTEDVALUE ( {q(name)}[{name}], {default} )",
        f"{T*2}formatString: {fmt}", f"{T*2}lineageTag: {tag(name, measure)}", "",
        f"{T}column {q(name)}", f"{T*2}dataType: {ty}", f"{T*2}formatString: {fmt}",
        f"{T*2}lineageTag: {tag(name, 'col')}", f"{T*2}summarizeBy: none", f"{T*2}sourceColumn: [Value]", "",
        f"{T*2}annotation SummarizationSetBy = User", "",
        f"{T}partition {q(name)} = calculated", f"{T*2}mode: import",
        f"{T*2}source = {source}", "",
    ])


# (name, DAX, format, display folder)
MEASURES = [
    ("Total Claims", "COUNTROWS ( fact_claims )", "#,##0", "1. Portfolio KPIs"),
    ("Fraud Claims", "CALCULATE ( [Total Claims], fact_claims[is_fraud] = 1 )", "#,##0", "1. Portfolio KPIs"),
    ("Fraud Rate", "DIVIDE ( [Fraud Claims], [Total Claims] )", "0.0%", "1. Portfolio KPIs"),
    ("Total Claimed (Cr)", "DIVIDE ( SUM ( fact_claims[total_claim_amount] ), 1e7 )", "#,##0.00", "1. Portfolio KPIs"),
    ("Fraud Claimed (Cr)", "CALCULATE ( [Total Claimed (Cr)], fact_claims[is_fraud] = 1 )", "#,##0.00", "1. Portfolio KPIs"),
    ("Fraud Leakage (Cr)", "DIVIDE ( CALCULATE ( SUM ( fact_claims[settled_amount] ), fact_claims[is_fraud] = 1 ), 1e7 )", "#,##0.00", "1. Portfolio KPIs"),
    ("Avg Claim Amount", "AVERAGE ( fact_claims[total_claim_amount] )", "#,##0", "1. Portfolio KPIs"),
    ("Portfolio Fraud Rate", "CALCULATE ( [Fraud Rate], ALLSELECTED ( fact_claims ) )", "0.0%", "2. Comparison & Trend"),
    ("Fraud Rate Lift", "DIVIDE ( [Fraud Rate], [Portfolio Fraud Rate] )", "0.0x", "2. Comparison & Trend"),
    ("Fraud Rate 3M Rolling", "CALCULATE ( [Fraud Rate], DATESINPERIOD ( 'Date'[Date], MAX ( 'Date'[Date] ), -3, MONTH ) )", "0.0%", "2. Comparison & Trend"),
    ("Fraud Rate YoY Change (pts)", [
        "VAR CurrentRate = [Fraud Rate]",
        "VAR LastYear = CALCULATE ( [Fraud Rate], SAMEPERIODLASTYEAR ( 'Date'[Date] ) )",
        "RETURN IF ( NOT ISBLANK ( LastYear ), CurrentRate - LastYear )"], "+0.0%;-0.0%;0.0%", "2. Comparison & Trend"),
    ("Garage Fraud Rate (min 25 claims)", "IF ( [Total Claims] >= 25, [Fraud Rate] )", "0.0%", "3. Network"),
    ("Garage Risk Rank", [
        "IF (",
        "    HASONEVALUE ( dim_garage[garage_id] ) && [Total Claims] >= 25,",
        "    RANKX (",
        "        FILTER ( ALL ( dim_garage[garage_id] ), CALCULATE ( [Total Claims] ) >= 25 ),",
        "        [Fraud Rate], , DESC, DENSE",
        "    )",
        ")"], "0", "3. Network"),
    ("High-Risk Garage Flag", 'IF ( [Fraud Rate] > 2 * [Portfolio Fraud Rate] && [Total Claims] >= 25, "Review", "OK" )', None, "3. Network"),
    ("Scored Claims", "CALCULATE ( [Total Claims], fact_claims[is_scored] = 1 )", "#,##0", "4. Model vs Rules"),
    ("Model Flagged", "CALCULATE ( [Total Claims], fact_claims[flag_for_siu] = 1 )", "#,##0", "4. Model vs Rules"),
    ("Rules Flagged", "CALCULATE ( [Total Claims], fact_claims[rules_flag] = 1 )", "#,##0", "4. Model vs Rules"),
    ("Model True Frauds", "CALCULATE ( [Fraud Claims], fact_claims[flag_for_siu] = 1 )", "#,##0", "4. Model vs Rules"),
    ("Rules True Frauds", "CALCULATE ( [Fraud Claims], fact_claims[rules_flag] = 1 )", "#,##0", "4. Model vs Rules"),
    ("Model Hit Rate", "DIVIDE ( [Model True Frauds], [Model Flagged] )", "0.0%", "4. Model vs Rules"),
    ("Rules Hit Rate", "DIVIDE ( [Rules True Frauds], [Rules Flagged] )", "0.0%", "4. Model vs Rules"),
    ("Fraud Value 2025", "CALCULATE ( SUM ( fact_claims[total_claim_amount] ), fact_claims[is_fraud] = 1, fact_claims[is_scored] = 1 )", "#,##0", "4. Model vs Rules"),
    ("Model Fraud Value Caught", "CALCULATE ( SUM ( fact_claims[total_claim_amount] ), fact_claims[is_fraud] = 1, fact_claims[flag_for_siu] = 1 )", "#,##0", "4. Model vs Rules"),
    ("Rules Fraud Value Caught", "CALCULATE ( SUM ( fact_claims[total_claim_amount] ), fact_claims[is_fraud] = 1, fact_claims[rules_flag] = 1 )", "#,##0", "4. Model vs Rules"),
    ("Model Value Recall", "DIVIDE ( [Model Fraud Value Caught], [Fraud Value 2025] )", "0.0%", "4. Model vs Rules"),
    ("Rules Value Recall", "DIVIDE ( [Rules Fraud Value Caught], [Fraud Value 2025] )", "0.0%", "4. Model vs Rules"),
    ("Model Net Benefit (Cr)", [
        "VAR Savings = [Recovery Rate Value] * [Model Fraud Value Caught]",
        "VAR ReviewCost = [Investigation Cost Value] * [Model Flagged]",
        "VAR FalsePos = [Model Flagged] - [Model True Frauds]",
        "VAR Friction = [Friction Cost Value] * FalsePos",
        "RETURN DIVIDE ( Savings - ReviewCost - Friction, 1e7 )"], "#,##0.00", "5. Business Case"),
    ("Rules Net Benefit (Cr)", [
        "VAR Savings = [Recovery Rate Value] * [Rules Fraud Value Caught]",
        "VAR ReviewCost = [Investigation Cost Value] * [Rules Flagged]",
        "VAR FalsePos = [Rules Flagged] - [Rules True Frauds]",
        "VAR Friction = [Friction Cost Value] * FalsePos",
        "RETURN DIVIDE ( Savings - ReviewCost - Friction, 1e7 )"], "#,##0.00", "5. Business Case"),
    ("Net Benefit Uplift (Cr)", "[Model Net Benefit (Cr)] - [Rules Net Benefit (Cr)]", "#,##0.00", "5. Business Case"),
    ("Capacity Value Recall", "AVERAGE ( capacity_curve[fraud_amount_recall] )", "0.0%", "5. Business Case"),
    ("Capacity Net Benefit (Cr)", "DIVIDE ( SUM ( capacity_curve[net_benefit] ), 1e7 )", "#,##0.00", "5. Business Case"),
    ("Feature Importance", "SUM ( feature_importance[importance] )", "0.0000", "5. Business Case"),
    ("Queue Size", "CALCULATE ( [Total Claims], fact_claims[flag_for_siu] = 1 )", "#,##0", "6. SIU Queue"),
    ("Queue Expected Loss (Cr)", "DIVIDE ( CALCULATE ( SUM ( fact_claims[expected_fraud_loss] ), fact_claims[flag_for_siu] = 1 ), 1e7 )", "#,##0.00", "6. SIU Queue"),
    ("Risk Band Colour", [
        "SWITCH ( SELECTEDVALUE ( fact_claims[risk_band] ),",
        '    "1-Critical", "#e34948",',
        '    "2-High", "#eb6834",',
        '    "3-Medium", "#eda100",',
        '    "#1baf7a"',
        ")"], None, "6. SIU Queue"),
]


def measures_table() -> str:
    out = ["table _Measures", f"{T}lineageTag: {tag('_Measures')}", ""]
    for name, dax, fmt, folder in MEASURES:
        if isinstance(dax, list):
            out.append(f"{T}measure {q(name)} =")
            out += [f"{T*3}{line}" for line in dax]
        else:
            out.append(f"{T}measure {q(name)} = {dax}")
        if fmt:
            out.append(f"{T*2}formatString: {fmt}")
        out += [f"{T*2}displayFolder: {folder}", f"{T*2}lineageTag: {tag('_Measures', name)}", ""]
    out += [f"{T}column Value", f"{T*2}dataType: int64", f"{T*2}isHidden", f"{T*2}formatString: 0",
            f"{T*2}lineageTag: {tag('_Measures', 'Value')}", f"{T*2}summarizeBy: none",
            f"{T*2}isNameInferred", f"{T*2}sourceColumn: [Value]", "",
            f"{T*2}annotation SummarizationSetBy = User", "",
            f"{T}partition _Measures = calculated", f"{T*2}mode: import", f"{T*2}source = {{1}}", ""]
    return "\n".join(out)


RELATIONSHIPS = [
    ("fact_claims", "incident_date", "Date", "Date"),
    ("fact_claims", "policy_id", "dim_policy", "policy_id"),
    ("fact_claims", "customer_id", "dim_customer", "customer_id"),
    ("fact_claims", "agent_id", "dim_agent", "agent_id"),
    ("fact_claims", "garage_id", "dim_garage", "garage_id"),
]


def write_data_folder() -> Path:
    """Write the DataFolder parameter (this machine's absolute path to powerbi/data)."""
    folder = str(DATA.resolve()).replace("/", "\\") + "\\"   # Windows path for File.Contents
    path = SM / "definition" / "expressions.tmdl"
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path, "\n".join([
        f'expression DataFolder = "{folder}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]',
        f"{T}lineageTag: {tag('DataFolder')}", "", f"{T}annotation PBI_ResultType = Text", ""]))
    return path


def write_semantic_model() -> None:
    d = SM / "definition"
    (d / "tables").mkdir(parents=True, exist_ok=True)
    save(SM / "definition.pbism", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2", "settings": {}}, indent=2))
    save(SM / ".platform", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "SemanticModel", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": tag("logical", "sm")}}, indent=2))
    save(d / "database.tmdl", f"database {NAME}\n{T}compatibilityLevel: 1600\n")
    tables = ["_Measures"] + CSV_TABLES + ["Date"] + [w[0] for w in WHAT_IF]
    model = ["model Model", f"{T}culture: en-US", f"{T}defaultPowerBIDataSourceVersion: powerBI_V3",
             f"{T}discourageImplicitMeasures", f"{T}sourceQueryCulture: en-US", f"{T}dataAccessOptions",
             f"{T*2}legacyRedirects", f"{T*2}returnErrorValuesAsNull", "",
             "annotation __PBI_TimeIntelligenceEnabled = 0", "",
             'annotation PBI_QueryOrder = ["DataFolder",' + ",".join(f'"{t}"' for t in CSV_TABLES) + "]", ""]
    model += [f"ref table {q(t)}" for t in tables] + [""]
    save(d / "model.tmdl", "\n".join(model))
    write_data_folder()
    rel = []
    for ft, fc, tt, tc in RELATIONSHIPS:
        rel += [f"relationship {tag('rel', ft, fc)}", f"{T}fromColumn: {q(ft)}.{q(fc)}", f"{T}toColumn: {q(tt)}.{q(tc)}", ""]
    save(d / "relationships.tmdl", "\n".join(rel))
    for t in CSV_TABLES:
        save(d / "tables" / f"{t}.tmdl", csv_table(t))
    save(d / "tables" / "Date.tmdl", date_table())
    save(d / "tables" / "_Measures.tmdl", measures_table())
    for w in WHAT_IF:
        save(d / "tables" / f"{w[0]}.tmdl", what_if_table(*w))


# --------------------------------------------------------------------------- #
# Report (PBIR)
# --------------------------------------------------------------------------- #
VC_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.7.0/schema.json"


def col(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def mea(prop, entity="_Measures"):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def proj(field, active=False):
    kind = "Column" if "Column" in field else "Measure"
    e = field[kind]["Expression"]["SourceRef"]["Entity"]
    p = field[kind]["Property"]
    out = {"field": field, "queryRef": f"{e}.{p}", "nativeQueryRef": p}
    if active:
        out["active"] = True
    return out


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


class Page:
    def __init__(self, name, display):
        self.name, self.display, self.visuals = name, display, []

    def add(self, vtype, x, y, w, h, query=None, title=None, sort=None, objects=None, filters=None):
        n = f"{self.name}_v{len(self.visuals) + 1:02d}"
        visual = {"visualType": vtype}
        if query is not None:
            visual["query"] = {"queryState": query}
            if sort:
                visual["query"]["sortDefinition"] = {"sort": [{"field": f, "direction": d} for f, d in sort]}
        if objects:
            visual["objects"] = objects
        if title:
            visual["visualContainerObjects"] = {"title": [{"properties": {"show": lit("true"), "text": lit(f"'{title}'")}}]}
        visual["drillFilterOtherVisuals"] = True
        v = {"$schema": VC_SCHEMA, "name": n,
             "position": {"x": x, "y": y, "z": len(self.visuals), "height": h, "width": w, "tabOrder": len(self.visuals)},
             "visual": visual}
        if filters:
            v["filterConfig"] = {"filters": filters}
        self.visuals.append(v)

    # helpers -------------------------------------------------------------- #
    def text(self, x, y, w, h, runs):
        paragraphs = [{"textRuns": [{"value": t, **({"textStyle": s} if s else {})}]} for t, s in runs]
        self.add("textbox", x, y, w, h, objects={"general": [{"properties": {"paragraphs": paragraphs}}]})

    def card(self, x, y, w, h, measure):
        self.add("card", x, y, w, h, {"Values": {"projections": [proj(mea(measure))]}})

    def chart(self, vtype, x, y, w, h, category, measures, title, series=None, sort_by=None, sort_dir="Descending"):
        qs = {"Category": {"projections": [proj(category, True)]},
              "Y": {"projections": [proj(mea(m)) for m in measures]}}
        if series is not None:
            qs["Series"] = {"projections": [proj(series)]}
        sort = [(sort_by, sort_dir)] if sort_by is not None else None
        self.add(vtype, x, y, w, h, qs, title, sort)

    def table(self, x, y, w, h, fields, title, sort=None, filters=None):
        self.add("tableEx", x, y, w, h, {"Values": {"projections": [proj(f) for f in fields]}}, title, sort, filters=filters)

    def slicer(self, x, y, w, h, field, title):
        self.add("slicer", x, y, w, h, {"Values": {"projections": [proj(field, True)]}}, title,
                 objects={"data": [{"properties": {"mode": lit("'Dropdown'")}}]})


def header(p: Page, title: str, subtitle: str):
    p.text(16, 4, 900, 76, [(title, {"fontSize": "20pt", "fontWeight": "bold"}),
                             (subtitle, {"fontSize": "10pt", "color": "#52514e"})])


def categorical_filter(name, entity, prop, value_literal):
    return {
        "name": name, "field": col(entity, prop), "type": "Categorical",
        "filter": {"Version": 2, "From": [{"Name": "f", "Entity": entity, "Type": 0}],
                   "Where": [{"Condition": {"In": {
                       "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": prop}}],
                       "Values": [[{"Literal": {"Value": value_literal}}]]}}}]},
    }


def build_pages() -> list[Page]:
    F, G, A = "fact_claims", "dim_garage", "dim_agent"
    pages = []

    p = Page("p1_overview", "Executive Overview")
    header(p, "Executive Overview", "Motor claims 2022-2025 · synthetic data generated for this portfolio project")
    p.slicer(1064, 16, 200, 56, col("Date", "Year"), "Year")
    for i, m in enumerate(["Total Claims", "Fraud Rate", "Total Claimed (Cr)", "Fraud Claimed (Cr)", "Fraud Leakage (Cr)"]):
        p.card(16 + i * 252, 88, 240, 110, m)
    p.chart("lineChart", 16, 214, 760, 490, col("Date", "Year Month"), ["Fraud Rate", "Fraud Rate 3M Rolling"],
            "Monthly fraud rate and 3-month rolling rate", sort_by=col("Date", "Year Month"), sort_dir="Ascending")
    p.chart("barChart", 788, 214, 476, 490, col(F, "claim_type"), ["Fraud Rate"], "Fraud rate by claim type",
            sort_by=mea("Fraud Rate"))
    pages.append(p)

    p = Page("p2_patterns", "Fraud Patterns")
    header(p, "Fraud Patterns", "The red flags behind hypotheses H1-H4 · dashed portfolio average = 10.2%")
    p.chart("columnChart", 16, 88, 616, 300, col(F, "policy_age_bucket"), ["Fraud Rate"],
            "H1 · Fraud rate by days since policy start", sort_by=col(F, "policy_age_bucket"), sort_dir="Ascending")
    p.chart("columnChart", 648, 88, 616, 300, col(F, "report_delay_bucket"), ["Fraud Rate"],
            "H2 · Fraud rate by reporting delay", sort_by=col(F, "report_delay_bucket"), sort_dir="Ascending")
    p.chart("barChart", 16, 404, 400, 300, col(A, "channel"), ["Fraud Rate"], "Fraud rate by sales channel",
            sort_by=mea("Fraud Rate"))
    p.chart("columnChart", 432, 404, 400, 300, col(F, "red_flag_score"), ["Fraud Rate"],
            "Rules engine · fraud rate by red-flag score", sort_by=col(F, "red_flag_score"), sort_dir="Ascending")
    p.table(848, 404, 416, 300, [col(F, "incident_severity"), mea("Total Claims"), mea("Fraud Rate"), mea("Fraud Rate Lift")],
            "Fraud by incident severity", sort=[(mea("Fraud Rate"), "Descending")])
    pages.append(p)

    p = Page("p3_network", "Garage & Agent Network")
    header(p, "Garage & Agent Network", "H5 · fraud concentrates in a few garages and agents (min 25 claims for a rank)")
    p.table(16, 88, 760, 616, [col(G, "garage_id"), col(G, "garage_name"), col(G, "city"), col(G, "is_network_garage"),
                               mea("Total Claims"), mea("Garage Fraud Rate (min 25 claims)"), mea("Garage Risk Rank"),
                               mea("High-Risk Garage Flag")],
            "Garages ranked by fraud rate", sort=[(mea("Garage Fraud Rate (min 25 claims)"), "Descending")])
    p.table(792, 88, 472, 380, [col(A, "agent_id"), col(A, "channel"), col(A, "city"), mea("Total Claims"),
                                mea("Fraud Rate"), mea("Fraud Rate Lift")],
            "Agents ranked by fraud rate", sort=[(mea("Fraud Rate"), "Descending")])
    p.chart("barChart", 792, 484, 472, 220, col(F, "incident_city"), ["Fraud Rate"], "Fraud rate by city",
            sort_by=mea("Fraud Rate"))
    pages.append(p)

    p = Page("p4_model", "Model Impact")
    header(p, "Model Impact", "2025 hold-out · same 10% SIU capacity · move the sliders to test the assumptions")
    for i, (t, c) in enumerate([("Recovery Rate", "Recovery rate"), ("Investigation Cost", "Cost per investigation (₹)"),
                                ("Friction Cost", "Friction per genuine customer (₹)")]):
        p.slicer(16 + i * 216, 88, 204, 64, col(t, t), c)
    for i, m in enumerate(["Model Net Benefit (Cr)", "Rules Net Benefit (Cr)", "Net Benefit Uplift (Cr)"]):
        p.card(672 + i * 200, 88, 192, 100, m)
    for i, m in enumerate(["Model Value Recall", "Rules Value Recall", "Model Hit Rate", "Rules Hit Rate"]):
        p.card(16 + i * 160, 168, 150, 100, m)
    p.chart("lineChart", 16, 284, 640, 420, col("capacity_curve", "pct_reviewed"), ["Capacity Value Recall"],
            "% of fraud value caught vs % of claims investigated", series=col("capacity_curve", "strategy"),
            sort_by=col("capacity_curve", "pct_reviewed"), sort_dir="Ascending")
    p.table(672, 204, 592, 220, [col("model_comparison", "model"), col("model_comparison", "pr_auc"),
                                 col("model_comparison", "precision_at_capacity"),
                                 col("model_comparison", "fraud_amount_recall"), col("model_comparison", "net_benefit")],
            "Model comparison (2025 hold-out)", sort=[(col("model_comparison", "model"), "Ascending")])
    p.chart("barChart", 672, 440, 592, 264, col("feature_importance", "feature"), ["Feature Importance"],
            "Top fraud drivers (permutation importance)", sort_by=mea("Feature Importance"))
    pages.append(p)

    p = Page("p5_queue", "SIU Investigation Queue")
    header(p, "SIU Investigation Queue", "2025 claims flagged for investigation, highest expected ₹ loss first")
    p.slicer(1064, 16, 200, 56, col(F, "risk_band"), "Risk band")
    for i, m in enumerate(["Queue Size", "Queue Expected Loss (Cr)", "Model Hit Rate"]):
        p.card(16 + i * 216, 88, 204, 100, m)
    p.table(16, 204, 1248, 500,
            [col(F, "priority_rank"), col(F, "claim_id"), col(F, "incident_date"), col(F, "claim_type"),
             col(F, "incident_severity"), col(F, "total_claim_amount"), col(F, "fraud_probability"),
             col(F, "expected_fraud_loss"), col(F, "risk_band"), col(F, "reason_codes"), col(F, "fraud_label")],
            "Investigation queue (flag_for_siu = 1)", sort=[(col(F, "priority_rank"), "Ascending")],
            filters=[categorical_filter("queue_only", F, "flag_for_siu", "1L")])
    pages.append(p)
    return pages


def write_report() -> None:
    d = RP / "definition"
    (d / "pages").mkdir(parents=True, exist_ok=True)
    save(RP / "definition.pbir", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}}, indent=2))
    save(RP / ".platform", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Report", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": tag("logical", "report")}}, indent=2))
    res = RP / "StaticResources" / "RegisteredResources"
    res.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PBI / "fraud_dashboard_theme.json", res / "fraud_dashboard_theme.json")
    save(d / "version.json", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0"}, indent=2))
    save(d / "report.json", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.0.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "CY24SU10", "reportVersionAtImport": {"visual": "1.8.95", "report": "2.0.95", "page": "1.3.95"},
                          "type": "SharedResources"},
            "customTheme": {"name": "fraud_dashboard_theme.json",
                            "reportVersionAtImport": {"visual": "2.1.0", "report": "2.1.0", "page": "2.0.0"},
                            "type": "RegisteredResources"}},
        "objects": {"outspacePane": [{"properties": {"expanded": lit("true")}}]},
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "fraud_dashboard_theme.json", "path": "fraud_dashboard_theme.json", "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True}}, indent=2))
    pages = build_pages()
    save(d / "pages" / "pages.json", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p.name for p in pages], "activePageName": pages[0].name}, indent=2))
    for p in pages:
        pd_ = d / "pages" / p.name
        (pd_ / "visuals").mkdir(parents=True, exist_ok=True)
        save(pd_ / "page.json", json.dumps({
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json",
            "name": p.name, "displayName": p.display, "displayOption": "FitToPage", "height": 720, "width": 1280},
            indent=2, ensure_ascii=False))
        for v in p.visuals:
            (pd_ / "visuals" / v["name"]).mkdir(exist_ok=True)
            save(pd_ / "visuals" / v["name"] / "visual.json", json.dumps(v, indent=2, ensure_ascii=False))


def main() -> None:
    if not (DATA / "fact_claims.csv").exists():
        sys.exit("powerbi/data/*.csv not found. Run python run_pipeline.py first.")
    if "--set-data-folder" in sys.argv:
        if not (SM / "definition" / "model.tmdl").exists():
            sys.exit(f"{NAME} not found. Run without arguments to generate it.")
        write_data_folder()
        print(f"DataFolder set to {DATA.resolve()}. Open powerbi/{NAME}.pbip in Power BI Desktop and click Refresh.")
        return
    if (SM.exists() or RP.exists()) and "--overwrite" not in sys.argv:
        sys.exit(f"{NAME} already exists. Use --set-data-folder to point it at this machine's data, "
                 "or --overwrite to regenerate everything (discards changes saved from Power BI Desktop).")
    for folder in (SM, RP):
        if folder.exists():
            shutil.rmtree(folder)
    write_semantic_model()
    write_report()
    save(PBI / f"{NAME}.pbip", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}}, indent=2))
    n_vis = sum(1 for _ in RP.glob("definition/pages/*/visuals/*/visual.json"))
    print(f"Wrote powerbi/{NAME}.pbip: {len(CSV_TABLES) + 5} tables, {len(MEASURES) + len(WHAT_IF)} measures, "
          f"{len(RELATIONSHIPS)} relationships, 5 pages, {n_vis} visuals.")
    print(f"Data folder parameter: {DATA}")
    print("Open it in Power BI Desktop, click Refresh, then File > Save as > .pbix if you want a single file.")


if __name__ == "__main__":
    main()
