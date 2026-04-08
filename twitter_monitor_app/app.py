from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
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
from twitter_monitor_app.services.query_builder import append_date_operators, build_query_plan
from twitter_monitor_app.services.runtime_store import (
    get_history_count,
    load_cache,
    load_incremental_state,
    make_cache_key,
    persist_history,
    save_cache,
    update_incremental_state,
)
from twitter_monitor_app.services.scoring import enrich_scores
from twitter_monitor_app.services.twitter_client import TwitterApiError, TwitterClient
from twitter_monitor_app.utils.helpers import parse_datetime

logging.basicConfig(level=logging.INFO)


def mock_tweets() -> List[Dict]:
    now = datetime.now(timezone.utc)
    return [
        {
            "id": "1",
            "url": "https://x.com/example/status/1",
            "text": "Aguas Andinas y Andess advierten sobre sequía y riesgo de racionamiento en Chile central.",
            "createdAt": (now - timedelta(hours=2)).isoformat(),
            "lang": "es",
            "likeCount": 18,
            "retweetCount": 7,
            "replyCount": 4,
            "quoteCount": 1,
            "viewCount": 1500,
            "author": {"name": "Radio Sectorial", "userName": "radiosectorial"},
        },
        {
            "id": "2",
            "url": "https://x.com/example/status/2",
            "text": "La SISS inició fiscalización por tarifas y sanciones a empresa sanitaria en la región del Biobío.",
            "createdAt": (now - timedelta(hours=12)).isoformat(),
            "lang": "es",
            "likeCount": 28,
            "retweetCount": 10,
            "replyCount": 6,
            "quoteCount": 3,
            "viewCount": 4200,
            "author": {"name": "Prensa Regulatoria", "userName": "prensareg"},
        },
        {
            "id": "3",
            "url": "https://x.com/example/status/3",
            "text": "Nuevo debate sobre agua potable rural, APR y cambio climático en Chile.",
            "createdAt": (now - timedelta(days=1)).isoformat(),
            "lang": "es",
            "likeCount": 11,
            "retweetCount": 4,
            "replyCount": 2,
            "quoteCount": 0,
            "viewCount": None,
            "author": {"name": "Observatorio Hídrico", "userName": "obs_hidrico"},
        },
        {
            "id": "4",
            "url": "https://x.com/example/status/4",
            "text": "ESSBIO anuncia inversión en saneamiento y seguridad hídrica.",
            "createdAt": (now - timedelta(days=2)).isoformat(),
            "lang": "es",
            "likeCount": 8,
            "retweetCount": 2,
            "replyCount": 1,
            "quoteCount": 0,
            "viewCount": 900,
            "author": {"name": "Diario Regional", "userName": "diarioregional"},
        },
    ]


def get_strategy_profile(strategy: str, requested_limit: int) -> Dict[str, int]:
    if strategy == "Rápida":
        return {"effective_limit": min(requested_limit, 200), "max_batches": 6, "timeline_limit": 10, "min_per_query": 20}
    if strategy == "Profunda":
        return {"effective_limit": requested_limit, "max_batches": 9999, "timeline_limit": 40, "min_per_query": 50}
    return {"effective_limit": min(requested_limit, 1000), "max_batches": 20, "timeline_limit": 20, "min_per_query": 20}


def prioritize_query_plan(query_plan: List[Dict], strategy: str) -> List[Dict]:
    ordered = sorted(
        query_plan,
        key=lambda item: (
            0 if item["category"] in {"Personas", "Empresas"} else 1,
            len(item["query"]),
        ),
    )
    max_batches = get_strategy_profile(strategy, 0)["max_batches"]
    return ordered[:max_batches]


def newest_created_at(tweets: List[Dict]) -> str | None:
    timestamps = [tweet.get("createdAt") for tweet in tweets if tweet.get("createdAt")]
    return max(timestamps) if timestamps else None


def collect_api_data(filters: Dict, catalog: dict) -> tuple[List[Dict], Dict]:
    client = TwitterClient()
    collected: List[Dict] = []
    query_plan = build_query_plan(
        filters["selected_categories"],
        filters["selected_people"],
        filters["selected_companies"],
        catalog,
    )
    strategy_profile = get_strategy_profile(filters["strategy"], filters["limit"])
    query_plan = prioritize_query_plan(query_plan, filters["strategy"])
    incremental_state = load_incremental_state()
    stats = {
        "api_calls_saved_by_cache": 0,
        "query_batches_planned": len(query_plan),
        "query_batches_executed": 0,
        "timeline_users_executed": 0,
        "effective_limit": strategy_profile["effective_limit"],
        "stopped_early": False,
    }

    if not client.enabled:
        raise TwitterApiError("No hay API key configurada. Activa simulación o define TWITTERAPI_IO_KEY.")

    if not query_plan and not filters["selected_monitor_users"]:
        raise TwitterApiError("Selecciona al menos una categoría, persona, empresa o timeline para ejecutar el monitoreo.")

    per_query_limit = max(
        strategy_profile["min_per_query"],
        strategy_profile["effective_limit"] // max(len(query_plan), 1),
    )

    for item in query_plan:
        query = append_date_operators(item["query"], filters["start_date"], filters["end_date"])
        state_key = make_cache_key("incremental", {"query": query, "category": item["category"]})
        since_time = None
        if filters["incremental_mode"]:
            last_seen = incremental_state.get(state_key)
            parsed = parse_datetime(last_seen)
            if parsed:
                since_time = int(parsed.timestamp()) + 1

        cache_payload = {
            "mode": "search",
            "query": query,
            "max_results": per_query_limit,
            "start_date": filters["start_date"],
            "end_date": filters["end_date"],
            "since_time": since_time,
            "strategy": filters["strategy"],
        }
        cache_key = make_cache_key("search", cache_payload)
        tweets = load_cache(cache_key, filters["cache_ttl_hours"]) if filters["use_cache"] else None
        if tweets is None:
            tweets = client.search_tweets(
                query=query,
                max_results=per_query_limit,
                start_date=filters["start_date"],
                end_date=filters["end_date"],
                since_time=since_time,
            )
            if filters["use_cache"]:
                save_cache(cache_key, tweets)
        else:
            stats["api_calls_saved_by_cache"] += 1

        for tweet in tweets:
            tweet["query_batch"] = item["query"]
            tweet["query_category"] = item["category"]
        collected.extend(tweets)
        stats["query_batches_executed"] += 1
        update_incremental_state(state_key, newest_created_at(tweets))

        if len(collected) >= strategy_profile["effective_limit"]:
            stats["stopped_early"] = True
            break

    if filters["include_user_timelines"]:
        remaining_capacity = max(strategy_profile["effective_limit"] - len(collected), 0)
        timeline_limit = min(strategy_profile["timeline_limit"], remaining_capacity) if remaining_capacity else 0

        for username in filters["selected_monitor_users"]:
            if not timeline_limit:
                stats["stopped_early"] = True
                break

            cache_payload = {
                "mode": "timeline",
                "username": username,
                "max_results": timeline_limit,
            }
            cache_key = make_cache_key("timeline", cache_payload)
            tweets = load_cache(cache_key, filters["cache_ttl_hours"]) if filters["use_cache"] else None
            if tweets is None:
                tweets = client.get_user_tweets(username=username, max_results=timeline_limit)
                if filters["use_cache"]:
                    save_cache(cache_key, tweets)
            else:
                stats["api_calls_saved_by_cache"] += 1

            for tweet in tweets:
                tweet["query_batch"] = f"user:{username}"
                tweet["query_category"] = "Timeline"
            collected.extend(tweets)
            stats["timeline_users_executed"] += 1

            remaining_capacity = max(strategy_profile["effective_limit"] - len(collected), 0)
            timeline_limit = min(strategy_profile["timeline_limit"], remaining_capacity) if remaining_capacity else 0
            if len(collected) >= strategy_profile["effective_limit"]:
                stats["stopped_early"] = True
                break

    return collected[: strategy_profile["effective_limit"]], stats


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
