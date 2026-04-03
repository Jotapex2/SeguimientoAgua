from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from config.settings import get_settings


def render_sidebar_filters(catalog: dict):
    settings = get_settings()
    st.sidebar.header("Filtros")
    sector_topics = catalog["sector_topics"]
    people = catalog["people"]
    companies = catalog["companies"]
    simulation_mode = st.sidebar.toggle("Simulación sin API", value=True)
    selected_categories = st.sidebar.multiselect("Categorías", options=list(sector_topics.keys()), default=list(sector_topics.keys())[:4])
    selected_people = st.sidebar.multiselect("Personas", options=list(people.keys()), default=[])
    company_defaults = [name for name in ["Andess", "Aguas Andinas"] if name in companies]
    selected_companies = st.sidebar.multiselect("Empresas", options=list(companies.keys()), default=company_defaults)
    date_range = st.sidebar.date_input("Rango de fechas", value=(date.today() - timedelta(days=7), date.today()))
    strategy = st.sidebar.selectbox("Estrategia de consumo API", options=["Rápida", "Balanceada", "Profunda"], index=1)
    limit = st.sidebar.slider("Límite de resultados", min_value=20, max_value=settings.max_limit, value=settings.default_limit, step=20)
    use_cache = st.sidebar.toggle("Usar caché local", value=True)
    cache_ttl_hours = st.sidebar.slider("TTL caché (horas)", min_value=1, max_value=48, value=settings.default_cache_ttl_hours, step=1)
    incremental_mode = st.sidebar.toggle("Modo incremental: traer sólo posts nuevos", value=True)
    include_user_timelines = st.sidebar.toggle("Incluir timelines de usuarios monitoreados", value=False)
    chile_only = st.sidebar.toggle("Sólo posts hechos desde Chile (CL)", value=False)
    export_only_high_views = st.sidebar.toggle("Exportar sólo posts con viewCount > 1000", value=False)
    run = st.sidebar.button("Ejecutar monitoreo", use_container_width=True, type="primary")

    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = end_date = date.today()

    return {
        "simulation_mode": simulation_mode,
        "selected_categories": selected_categories,
        "selected_people": selected_people,
        "selected_companies": selected_companies,
        "start_date": start_date,
        "end_date": end_date,
        "strategy": strategy,
        "limit": limit,
        "use_cache": use_cache,
        "cache_ttl_hours": cache_ttl_hours,
        "incremental_mode": incremental_mode,
        "include_user_timelines": include_user_timelines,
        "chile_only": chile_only,
        "export_only_high_views": export_only_high_views,
        "run": run,
    }
