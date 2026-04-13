from __future__ import annotations

import argparse
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("google_social_monitor")

GOOGLE_SEARCH_URL = "https://www.google.com/search"
DEFAULT_KEYWORDS = ["Andess", "agua potable", "APR", "servicios sanitarios", "Aguas Andinas"]
DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}\s+de\s+[a-záéíóúñ]+(?:\s+de\s+\d{4})?|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:ene|feb|mar|abr|may|jun|jul|ago|sept?|oct|nov|dic)\.?\s+\d{1,2},?\s+\d{4})\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class PlatformConfig:
    name: str
    search_site: str
    allowed_url_fragments: tuple[str, ...]
    default_output_csv: str
    default_output_excel: str


PLATFORM_CONFIG = {
    "linkedin": PlatformConfig(
        name="linkedin",
        search_site="site:linkedin.com/posts",
        allowed_url_fragments=("linkedin.com/posts",),
        default_output_csv="linkedin_scraping_results.csv",
        default_output_excel="linkedin_scraping_results.xlsx",
    ),
    "x": PlatformConfig(
        name="x",
        search_site="site:x.com/status OR site:twitter.com/status",
        allowed_url_fragments=("/status/",),
        default_output_csv="x_google_scraping_results.csv",
        default_output_excel="x_google_scraping_results.xlsx",
    ),
}


class GoogleSearchError(RuntimeError):
    pass


def build_session(timeout: int = 20) -> Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
    )
    session.request_timeout = timeout
    return session


def build_google_query(keyword: str, platform: PlatformConfig) -> str:
    return f'{platform.search_site} "{keyword}"'


def extract_google_result_url(raw_href: str) -> str:
    if not raw_href:
        return ""
    if raw_href.startswith("/url?"):
        parsed = urlparse(raw_href)
        query = parse_qs(parsed.query)
        return unquote(query.get("q", [""])[0])
    return raw_href


def is_allowed_result(url: str, platform: PlatformConfig) -> bool:
    normalized_url = (url or "").lower()
    if not normalized_url.startswith("http"):
        return False
    return any(fragment in normalized_url for fragment in platform.allowed_url_fragments)


def extract_result_date(snippet: str) -> str:
    match = DATE_PATTERN.search(snippet or "")
    return match.group(0) if match else ""


def score_result(keyword: str, title: str, snippet: str, url: str) -> int:
    normalized_keyword = keyword.casefold().strip()
    score = 0
    if normalized_keyword and normalized_keyword in (title or "").casefold():
        score += 1
    if normalized_keyword and normalized_keyword in (snippet or "").casefold():
        score += 1
    if normalized_keyword and normalized_keyword in (url or "").casefold():
        score += 1
    return score


def fetch_google_page(session: Session, query: str, start: int, language: str) -> Response:
    params = {
        "q": query,
        "hl": language,
        "gl": "cl",
        "lr": f"lang_{language}",
        "num": 10,
        "start": start,
        "safe": "off",
    }
    response = session.get(GOOGLE_SEARCH_URL, params=params, timeout=session.request_timeout)
    if response.status_code >= 400:
        raise GoogleSearchError(f"Google devolvió HTTP {response.status_code} para start={start}.")
    return response


def parse_google_results(html: str, keyword: str, platform: PlatformConfig) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    parsed_results: list[dict] = []

    for result_block in soup.select("div.g"):
        link_tag = result_block.select_one("a[href]")
        title_tag = result_block.select_one("h3")
        snippet_tag = result_block.select_one("div.VwiC3b, div.yXK7lf, span.aCOpRe, div.s3v9rd")

        if not link_tag or not title_tag:
            continue

        link = extract_google_result_url(link_tag.get("href", ""))
        if not is_allowed_result(link, platform):
            continue

        title = " ".join(title_tag.get_text(" ", strip=True).split())
        snippet = " ".join((snippet_tag.get_text(" ", strip=True) if snippet_tag else "").split())
        parsed_results.append(
            {
                "platform": platform.name,
                "keyword": keyword,
                "titulo": title,
                "descripcion": snippet,
                "link": link,
                "fecha": extract_result_date(snippet),
                "relevancia_score": score_result(keyword, title, snippet, link),
            }
        )

    return parsed_results


def search_keyword(
    session: Session,
    keyword: str,
    results_per_keyword: int,
    language: str,
    platform: PlatformConfig,
    min_delay_seconds: float,
    max_delay_seconds: float,
) -> list[dict]:
    query = build_google_query(keyword, platform)
    collected: list[dict] = []
    seen_links: set[str] = set()

    for start in range(0, max(results_per_keyword, 10), 10):
        try:
            response = fetch_google_page(session, query=query, start=start, language=language)
        except requests.RequestException as exc:
            raise GoogleSearchError(f"Fallo de red consultando Google para '{keyword}': {exc}") from exc

        page_results = parse_google_results(response.text, keyword=keyword, platform=platform)
        if not page_results:
            logger.info("Sin resultados parseables para '%s' en start=%s.", keyword, start)
            break

        new_results = 0
        for item in page_results:
            if item["link"] in seen_links:
                continue
            collected.append(item)
            seen_links.add(item["link"])
            new_results += 1
            if len(collected) >= results_per_keyword:
                break

        if len(collected) >= results_per_keyword or new_results == 0:
            break

        sleep_seconds = random.uniform(min_delay_seconds, max_delay_seconds)
        logger.info("Sleep %.2fs antes de la siguiente página para '%s'.", sleep_seconds, keyword)
        time.sleep(sleep_seconds)

    return collected[:results_per_keyword]


def clean_results(results: Iterable[dict], platform: PlatformConfig, lowercase_text: bool = False) -> pd.DataFrame:
    df = pd.DataFrame(results)
    expected_columns = [
        "platform",
        "keyword",
        "titulo",
        "descripcion",
        "link",
        "fecha",
        "relevancia_score",
    ]
    if df.empty:
        return pd.DataFrame(columns=expected_columns + ["execution_timestamp"])

    df = df.drop_duplicates(subset=["keyword", "link"]).copy()
    df = df[df["link"].map(lambda value: is_allowed_result(str(value), platform))].copy()
    if lowercase_text:
        for column in ("titulo", "descripcion"):
            df[column] = df[column].fillna("").str.lower()
    df["execution_timestamp"] = datetime.now(timezone.utc).isoformat()
    df = df.sort_values(by=["keyword", "relevancia_score", "titulo"], ascending=[True, False, True]).reset_index(drop=True)
    return df[expected_columns + ["execution_timestamp"]]


def export_results(df: pd.DataFrame, csv_path: Path, excel_path: Path | None) -> None:
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    if excel_path is not None:
        df.to_excel(excel_path, index=False)


def print_console_summary(df: pd.DataFrame) -> None:
    if df.empty:
        print("Sin resultados para los parámetros indicados.")
        return
    for row in df.itertuples(index=False):
        print(f"{row.titulo} — {row.keyword} — {row.link}")


def run_monitor(
    keywords: list[str],
    results_per_keyword: int,
    language: str,
    platform_name: str,
    lowercase_text: bool,
    export_excel: bool,
    min_delay_seconds: float,
    max_delay_seconds: float,
) -> pd.DataFrame:
    platform = PLATFORM_CONFIG[platform_name]
    session = build_session()
    all_results: list[dict] = []

    for keyword in keywords:
        keyword = keyword.strip()
        if not keyword:
            continue
        logger.info("Buscando '%s' en Google para plataforma=%s.", keyword, platform.name)
        keyword_results = search_keyword(
            session=session,
            keyword=keyword,
            results_per_keyword=results_per_keyword,
            language=language,
            platform=platform,
            min_delay_seconds=min_delay_seconds,
            max_delay_seconds=max_delay_seconds,
        )
        all_results.extend(keyword_results)

        sleep_seconds = random.uniform(min_delay_seconds, max_delay_seconds)
        logger.info("Sleep %.2fs antes de la siguiente keyword.", sleep_seconds)
        time.sleep(sleep_seconds)

    cleaned_df = clean_results(all_results, platform=platform, lowercase_text=lowercase_text)
    csv_path = Path(platform.default_output_csv)
    excel_path = Path(platform.default_output_excel) if export_excel else None
    export_results(cleaned_df, csv_path=csv_path, excel_path=excel_path)
    return cleaned_df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitorea menciones públicas en LinkedIn o X usando Google como proxy de búsqueda.",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=DEFAULT_KEYWORDS,
        help='Lista de keywords. Ejemplo: --keywords "Andess" "agua potable" "APR"',
    )
    parser.add_argument("--results-per-keyword", type=int, default=20, help="Máximo de resultados a recuperar por keyword.")
    parser.add_argument("--language", default="es", help="Idioma para Google. Por defecto: es.")
    parser.add_argument(
        "--platform",
        choices=sorted(PLATFORM_CONFIG.keys()),
        default="linkedin",
        help="Plataforma objetivo. Usa 'linkedin' para linkedin.com/posts o 'x' como opción 2 vía Google.",
    )
    parser.add_argument("--lowercase-text", action="store_true", help="Normaliza título y descripción a minúsculas.")
    parser.add_argument("--no-excel", action="store_true", help="Desactiva la exportación a Excel.")
    parser.add_argument("--min-delay", type=float, default=2.0, help="Espera mínima entre requests.")
    parser.add_argument("--max-delay", type=float, default=4.0, help="Espera máxima entre requests.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.results_per_keyword <= 0:
        raise SystemExit("--results-per-keyword debe ser mayor que 0.")
    if args.min_delay < 0 or args.max_delay < 0 or args.min_delay > args.max_delay:
        raise SystemExit("Los delays deben ser no negativos y min-delay no puede ser mayor que max-delay.")

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s | %(levelname)s | %(message)s")

    df = run_monitor(
        keywords=args.keywords,
        results_per_keyword=args.results_per_keyword,
        language=args.language,
        platform_name=args.platform,
        lowercase_text=args.lowercase_text,
        export_excel=not args.no_excel,
        min_delay_seconds=args.min_delay,
        max_delay_seconds=args.max_delay,
    )

    print_console_summary(df)
    print("")
    print("DataFrame generado con columnas:", ", ".join(df.columns))
    print(f"Total filas: {len(df)}")
    print(f"CSV: {PLATFORM_CONFIG[args.platform].default_output_csv}")
    if not args.no_excel:
        print(f"Excel: {PLATFORM_CONFIG[args.platform].default_output_excel}")


if __name__ == "__main__":
    main()
