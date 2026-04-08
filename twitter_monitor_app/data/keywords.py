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
        "martin arrau",
        "ivan poduje",
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
    "Ministro Martín Arrau": ["martin arrau", "ministro de obras publicas"],
    "Iván Poduje": ["ivan poduje"],
    "Jorge Quiroz": ["jorge quiroz"],
    "Joaquín Daga": ["joaquin daga"],
}

PRIORITY_PEOPLE = {
    "Presidente José Antonio Kast",
    "Ministro Martín Arrau",
    "Iván Poduje",
    "Jorge Quiroz",
    "Joaquín Daga",
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
