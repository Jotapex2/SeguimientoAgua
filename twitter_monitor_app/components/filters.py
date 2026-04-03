from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

def render_sidebar_filters(catalog: dict):
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
    limit = st.sidebar.slider("Límite de resultados", min_value=20, max_value=200, value=80, step=20)
    include_user_timelines = st.sidebar.toggle("Incluir timelines de usuarios monitoreados", value=False)
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
        "limit": limit,
        "include_user_timelines": include_user_timelines,
        "run": run,
    }
