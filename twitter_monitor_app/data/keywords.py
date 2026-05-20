from copy import deepcopy


SECTOR_TOPICS = {
    "Andess": [
        "andess",
    ],
    "Regulación sanitaria": [
        "siss",
        "direccion general de aguas",
        "codigo de aguas",
        "superintendencia de servicios sanitarios",
    ],
    "Industria sanitaria": [
        "agua potable",
        "aguas servidas",
        "tratamiento de aguas",
        "territorio operacional",
        "desaladora",
    ],
    "Empresas asociadas": [
        "aguas del altiplano",
        "aguas antofagasta",
        "nueva atacama",
        "aguas del valle",
        "esval",
        "aguas andinas",
        "sacyr agua",
        "essbio",
        "nuevosur",
        "aguas araucania",
        "suralis",
        "aguas patagonia",
        "aguas magallanes",
    ],
    "Agua Potable Rural": [
        "agua potable rural",
        "servicios sanitarios rurales",
        "apr",
    ],
    "Agua, sequía y cambio climático": [
        "deficit hidrico",
        "megasequia",
        "racionamiento",
        "sequia",
    ],
    "Líderes del sector": [
        "jose antonio kast",
        "ivan poduje",
        "louis de grange",
        "nicolas balmaceda",
        "jorge quiroz",
        "joaquin daga",
    ],
    "Riesgo regulatorio": [
        "sanciones",
        "fiscalizacion",
        "multa",
        "sobreconsumo",
        "tarifas",
    ],
}

COMPANIES = {
    "Andess": ["andess"],
    "Aguas del Altiplano": ["aguas del altiplano"],
    "Aguas Antofagasta": ["aguas antofagasta"],
    "Nueva Atacama": ["nueva atacama"],
    "Aguas del Valle": ["aguas del valle"],
    "Aguas Andinas": ["aguas andinas"],
    "Sacyr Agua": ["sacyr agua"],
    "Essbio": ["essbio"],
    "Esval": ["esval"],
    "Nuevosur": ["nuevosur"],
    "Aguas Araucanía": ["aguas araucania"],
    "Suralis": ["suralis"],
    "Aguas Patagonia": ["aguas patagonia"],
    "Aguas Magallanes": ["aguas magallanes"],
    "SMAPA": ["smapa"],
}

PEOPLE = {
    "Presidente José Antonio Kast": ["jose antonio kast", "presidente jose antonio kast"],
    "Iván Poduje": ["ivan poduje", "ministro ivan poduje", "ministro iván poduje", "poduje"],
    "Louis de Grange": ["louis de grange", "louis de grange concha", "de grange", "louisdegrange"],
    "Nicolás Balmaceda": [
        "nicolas balmaceda",
        "nicolás balmaceda",
        "nicolas balmaceda jimeno",
        "nicolás balmaceda jimeno",
        "subsecretario de obras publicas",
        "subsecretario de obras públicas",
    ],
    "Jorge Quiroz": ["jorge quiroz"],
    "Joaquín Daga": ["joaquin daga"],
}

PRIORITY_PEOPLE = [
    "Presidente José Antonio Kast",
    "Iván Poduje",
    "Louis de Grange",
    "Nicolás Balmaceda",
    "Jorge Quiroz",
    "Joaquín Daga",
]

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
    "antofagasta",
    "mop",
    "siss",
    "dga",
    "apr",
]

MONITOR_USERS = [
    "andesschile",
    "aguas_andinas",
    "mop_chile",
    "louisdegrange",
    "MTTChile",
    "superdesal",
    "gore_rm",
]

MONITOR_ACCOUNTS = {
    "andesschile": "Andess",
    "aguas_andinas": "Aguas Andinas",
    "mop_chile": "Ministerio de Obras Públicas",
    "louisdegrange": "Louis de Grange",
    "MTTChile": "Ministerio de Transportes y Telecomunicaciones",
    "superdesal": "Superintendencia de Servicios Sanitarios",
    "gore_rm": "Gobierno Regional Metropolitano",
}


def get_default_catalog() -> dict:
    return deepcopy(
        {
            "sector_topics": SECTOR_TOPICS,
            "companies": COMPANIES,
            "people": PEOPLE,
            "priority_people": PRIORITY_PEOPLE,
            "risk_terms": RISK_TERMS,
            "chile_context_terms": CHILE_CONTEXT_TERMS,
            "monitor_users": MONITOR_USERS,
            "monitor_accounts": MONITOR_ACCOUNTS,
        }
    )
