from copy import deepcopy


SECTOR_TOPICS = {
    "Empresas sanitarias": [
        "andess",
        "aguas andinas",
        "essbio",
        "esval",
        "nuevosur",
        "smapa",
        "aguas del valle",
        "empresa sanitaria",
        "empresas sanitarias",
        "sector sanitario",
        "industria sanitaria",
    ],
    "Regulación sanitaria": [
        "regulacion sanitaria",
        "siss",
        "superintendencia de servicios sanitarios",
        "fiscalizacion sanitaria",
        "norma sanitaria",
        "tarifas sanitarias",
        "concesion sanitaria",
        "marco regulatorio",
        "regulador",
        "fiscalizacion",
        "sancion",
        "sanciones",
    ],
    "Industria hídrica": [
        "agua potable",
        "aguas servidas",
        "saneamiento",
        "servicios sanitarios",
        "infraestructura hidrica",
        "seguridad hidrica",
    ],
    "Agua Potable Rural": [
        "agua potable rural",
        "apr",
        "servicios sanitarios rurales",
        "ssr",
        "comite de agua potable rural",
    ],
    "Sequía y cambio climático": [
        "sequía",
        "sequia",
        "cambio climatico",
        "escasez hidrica",
        "racionamiento",
        "megasequia",
    ],
    "Liderazgo y stakeholders": [
        "ministra de obras publicas",
        "ministerio de obras publicas",
        "mop",
        "direccion general de aguas",
        "dga",
        "superintendencia de servicios sanitarios",
        "siss",
        "gobierno de chile",
    ],
    "Riesgo regulatorio": [
        "sanciones",
        "fiscalizacion",
        "multa",
        "crisis",
        "sobreconsumo",
        "tarifas",
    ],
}

COMPANIES = {
    "Andess": ["andess"],
    "Aguas Andinas": ["aguas andinas"],
    "Essbio": ["essbio"],
    "Esval": ["esval"],
    "Nuevosur": ["nuevosur"],
    "SMAPA": ["smapa"],
}

PEOPLE = {
    "Jessica López": ["jessica lopez", "ministra de obras publicas"],
    "Autoridades SISS": ["siss", "superintendencia de servicios sanitarios"],
    "Dirección General de Aguas": ["dga", "direccion general de aguas"],
    "Gobierno de Chile": ["gobierno de chile", "ministerio de obras publicas", "mop"],
    "Andess": ["andess"],
    "Senado Chile": ["senado", "senado chile"],
    "Cámara de Diputadas y Diputados": ["camara de diputados", "camara de diputadas y diputados"],
}

PRIORITY_PEOPLE = {
    "Jessica López",
    "Autoridades SISS",
    "Dirección General de Aguas",
}

RISK_TERMS = [
    "crisis",
    "racionamiento",
    "sobreconsumo",
    "tarifas",
    "sanciones",
    "fiscalizacion",
    "corte",
    "denuncia",
    "multa",
]

CHILE_CONTEXT_TERMS = [
    "chile",
    "santiago",
    "valparaiso",
    "biobio",
    "araucania",
    "atacama",
    "mop",
    "siss",
    "dga",
    "apr",
]

MONITOR_USERS = [
    "andesschile",
    "aguas_andinas",
    "mop_chile",
    "superdesal",
    "gore_rm",
]


def get_default_catalog() -> dict:
    return deepcopy(
        {
            "sector_topics": SECTOR_TOPICS,
            "companies": COMPANIES,
            "people": PEOPLE,
            "priority_people": sorted(PRIORITY_PEOPLE),
            "risk_terms": RISK_TERMS,
            "chile_context_terms": CHILE_CONTEXT_TERMS,
            "monitor_users": MONITOR_USERS,
        }
    )
