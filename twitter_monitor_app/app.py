from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pandas as pd
import streamlit as st

from components.charts import render_charts
from components.filters import render_sidebar_filters
from components.metrics import render_kpis
from components.tables import render_rankings, render_results_table
from components.taxonomy_editor import render_taxonomy_editor
from config.settings import get_settings
from data.keywords import get_default_catalog
from services.classifier import post_process_tweets
from services.exporter import dataframe_to_csv_bytes, dataframe_to_excel_bytes
from services.query_builder import append_date_operators, build_query_plan
from services.scoring import enrich_scores
from services.twitter_client import TwitterApiError, TwitterClient

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


def collect_api_data(filters: Dict, catalog: dict) -> List[Dict]:
    client = TwitterClient()
    collected: List[Dict] = []
    query_plan = build_query_plan(
        filters["selected_categories"],
        filters["selected_people"],
        filters["selected_companies"],
        catalog,
    )

    if not client.enabled:
        raise TwitterApiError("No hay API key configurada. Activa simulación o define TWITTERAPI_IO_KEY.")

    per_query_limit = max(20, filters["limit"] // max(len(query_plan), 1))

    for item in query_plan:
        query = append_date_operators(item["query"], filters["start_date"], filters["end_date"])
        tweets = client.search_tweets(
            query=query,
            max_results=per_query_limit,
            start_date=filters["start_date"],
            end_date=filters["end_date"],
        )
        for tweet in tweets:
            tweet["query_batch"] = item["query"]
            tweet["query_category"] = item["category"]
        collected.extend(tweets)

    if filters["include_user_timelines"]:
        for username in catalog["monitor_users"]:
            tweets = client.get_user_tweets(username=username, max_results=20)
            for tweet in tweets:
                tweet["query_batch"] = f"user:{username}"
                tweet["query_category"] = "Timeline"
            collected.extend(tweets)

    return collected


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
            raw_tweets = mock_tweets() if filters["simulation_mode"] else collect_api_data(filters, catalog)
        except TwitterApiError as exc:
            st.error(str(exc))
            return

        processed = post_process_tweets(raw_tweets, catalog)
        df = build_dataframe(processed, catalog)

    render_kpis(df)
    render_limitations(df)

    st.subheader("Resultados")
    render_results_table(df)

    st.subheader("Visualizaciones")
    render_charts(df)

    st.subheader("Rankings")
    render_rankings(df)

    st.subheader("Exportación")
    if not df.empty:
        st.download_button("Descargar CSV", data=dataframe_to_csv_bytes(df), file_name="twitter_monitor_results.csv", mime="text/csv")
        st.download_button(
            "Descargar Excel",
            data=dataframe_to_excel_bytes(df),
            file_name="twitter_monitor_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.caption("Sin datos exportables.")


if __name__ == "__main__":
    main()
