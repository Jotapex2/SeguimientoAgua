import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class AppConfig:
    app_name: str = "Monitoreo Sectorial X/Twitter Chile"
    api_key: str = os.getenv("TWITTERAPI_IO_KEY", "")
    base_url: str = os.getenv("BASE_URL", "https://api.twitterapi.io")
    default_limit: int = 10000
    max_limit: int = 10000
    request_timeout: int = 30
    max_retries: int = 3
    backoff_factor: float = 1.5
    page_size: int = 20
    default_query_type: str = "Latest"
    supported_languages: List[str] = field(default_factory=lambda: ["es"])
    priority_people_boost: float = 10.0
    context_terms: List[str] = field(
        default_factory=lambda: [
            "chile",
            "santiago",
            "valparaiso",
            "biobio",
            "atacama",
            "antofagasta",
            "apr",
            "superintendencia",
            "siss",
            "mop",
            "dga",
        ]
    )


def get_settings() -> AppConfig:
    return AppConfig()
