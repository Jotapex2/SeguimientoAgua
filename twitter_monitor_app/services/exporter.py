from __future__ import annotations

from io import BytesIO

import pandas as pd


def build_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    export_df = df.copy()
    if "matches" in export_df.columns:
        export_df["matches"] = export_df["matches"].apply(
            lambda values: ", ".join(f"{item['match_type']}:{item['group']}:{item['term']}" for item in values) if isinstance(values, list) else ""
        )
    if "risk_terms" in export_df.columns:
        export_df["risk_terms"] = export_df["risk_terms"].apply(lambda values: ", ".join(values) if isinstance(values, list) else "")
    return export_df


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return build_export_frame(df).to_csv(index=False).encode("utf-8")


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        build_export_frame(df).to_excel(writer, sheet_name="tweets", index=False)
    return output.getvalue()
