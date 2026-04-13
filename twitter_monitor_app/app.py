from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from twitter_monitor_app.components.charts import render_charts
from twitter_monitor_app.components.filters import render_sidebar_filters
from twitter_monitor_app.components.metrics import render_kpis
from twitter_monitor_app.components.tables import render_rankings, render_results_table
from twitter_monitor_app.components.taxonomy_editor import render_taxonomy_editor
from twitter_monitor_app.config.settings import get_settings
from twitter_monitor_app.data.keywords import get_default_catalog
from twitter_monitor_app.services.classifier import post_process_tweets
from twitter_monitor_app.services.exporter import dataframe_to_csv_bytes, dataframe_to_excel_bytes
from twitter_monitor_app.services.runtime_store import get_history_count, persist_history
from twitter_monitor_app.services.scoring import enrich_scores
from twitter_monitor_app.services.data_manager import mock_tweets, collect_api_data
from twitter_monitor_app.services.twitter_client import TwitterApiError

logging.basicConfig(level=logging.INFO)


def build_dataframe(tweets: List[Dict], catalog: dict) -> pd.DataFrame:
    normalized_rows = []
    for tweet in tweets:
        enriched = enrich_scores(tweet, catalog)
        author = enriched.get("author", {}) or {}
        normalized_rows.append(
            {
                **enriched,
                "author_name": author.get("name", ""),
                "author_username": author.get("userName", ""),
                "engagement_total": (
                    int(enriched.get("likeCount", 0) or 0)
                    + int(enriched.get("retweetCount", 0) or 0)
                    + int(enriched.get("replyCount", 0) or 0)
                    + int(enriched.get("quoteCount", 0) or 0)
                ),
            }
        )
    return pd.DataFrame(normalized_rows)


def render_limitations(df: pd.DataFrame):
    missing_views = bool(df.empty) or df["viewCount"].isna().any() if "viewCount" in df.columns else True
    limitations = [
        "twitterapi.io es una API de terceros, no la API oficial de X/Twitter.",
        "Algunos operadores avanzados pueden comportarse distinto; la app compensa con filtros en Python.",
        "La paginación depende de `cursor`; la propia documentación indica que `has_next_page` puede venir en `true` aun sin más resultados.",
    ]
    if missing_views:
        limitations.append("`viewCount` o métricas similares pueden faltar en algunas respuestas; la app usa fallback seguro.")
    st.info("\n".join(f"- {item}" for item in limitations))


def build_export_dataframe(df: pd.DataFrame, export_only_high_views: bool) -> pd.DataFrame:
    if df.empty:
        return df
    export_df = df.copy()
    if export_only_high_views:
        view_counts = pd.to_numeric(export_df.get("viewCount"), errors="coerce")
        export_df = export_df.loc[view_counts > 1000].copy()
    return export_df


def render_efficiency_summary(filters: Dict, query_stats: Dict, df: pd.DataFrame):
    history_count = get_history_count()
    messages = [
        f"Estrategia activa: {filters['strategy']}.",
        f"Límite efectivo aplicado en esta corrida: {query_stats.get('effective_limit', filters['limit'])}.",
        f"Batches ejecutados: {query_stats.get('query_batches_executed', 0)} de {query_stats.get('query_batches_planned', 0)}.",
    ]
    if filters["include_user_timelines"]:
        messages.append(f"Timelines consultadas: {query_stats.get('timeline_users_executed', 0)}.")
    if filters["use_cache"]:
        messages.append(f"Consultas evitadas por caché: {query_stats.get('api_calls_saved_by_cache', 0)}.")
    if filters["incremental_mode"]:
        messages.append("Modo incremental activo: se intentó pedir sólo contenido nuevo por query.")
    if query_stats.get("stopped_early"):
        messages.append("Se aplicó corte temprano al alcanzar el volumen objetivo.")
    messages.append(f"Histórico local acumulado: {history_count} posts.")
    messages.append(f"Posts procesados en la corrida actual: {len(df)}.")
    st.caption(" ".join(messages))


def main():
    settings = get_settings()
    st.set_page_config(page_title=settings.app_name, layout="wide")
    st.title(settings.app_name)
    st.caption("Monitoreo ejecutivo para conversaciones del sector sanitario, hídrico y regulatorio en Chile.")

    default_catalog = get_default_catalog()
    if "catalog" not in st.session_state:
        st.session_state["catalog"] = get_default_catalog()
    catalog = render_taxonomy_editor(st.session_state["catalog"], default_catalog)
    filters = render_sidebar_filters(catalog)

    if not filters["run"]:
        st.info("Configura filtros y ejecuta el monitoreo. El modo simulación está habilitado por defecto para probar la UI sin consumir la API.")
        return

    with st.spinner("Consultando y procesando tweets..."):
        try:
            if filters["simulation_mode"]:
                raw_tweets = mock_tweets()
                query_stats = {
                    "api_calls_saved_by_cache": 0,
                    "query_batches_planned": 0,
                    "query_batches_executed": 0,
                    "timeline_users_executed": 0,
                    "effective_limit": filters["limit"],
                    "stopped_early": False,
                }
            else:
                raw_tweets, query_stats = collect_api_data(filters, catalog)
        except TwitterApiError as exc:
            st.error(str(exc))
            return

        processed = post_process_tweets(raw_tweets, catalog, chile_only=filters["chile_only"])
        df = build_dataframe(processed, catalog)
        persist_history(df.to_dict(orient="records"))

    render_kpis(df)
    render_limitations(df)
    render_efficiency_summary(filters, query_stats, df)
    if filters["chile_only"]:
        st.caption("Filtro activo: sólo se muestran posts detectados como originados en Chile (CL).")

    st.subheader("Resultados")
    render_results_table(df)

    st.subheader("Visualizaciones")
    render_charts(df)

    st.subheader("Rankings")
    render_rankings(df)

    st.subheader("Exportación")
    export_df = build_export_dataframe(df, filters["export_only_high_views"])
    if filters["export_only_high_views"]:
        st.caption(f"Exportación filtrada: {len(export_df)} posts con viewCount mayor a 1000.")
    if not export_df.empty:
        st.download_button("Descargar CSV", data=dataframe_to_csv_bytes(export_df), file_name="twitter_monitor_results.csv", mime="text/csv")
        st.download_button(
            "Descargar Excel",
            data=dataframe_to_excel_bytes(export_df),
            file_name="twitter_monitor_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.caption("Sin datos exportables con el filtro actual.")


if __name__ == "__main__":
    main()