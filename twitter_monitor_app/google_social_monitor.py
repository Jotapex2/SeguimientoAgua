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
MAX_GOOGLE_PAGES_PER_KEYWORD = 20
DEFAULT_GOOGLE_BACKOFF_SECONDS = 30.0
# Batch size para agrupar keywords con OR y reducir peticiones a Google
GOOGLE_KEYWORDS_BATCH_SIZE = 5

DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}\s+de\s+[a-zÃ¡Ã©Ã­Ã³ÃºÃ±]+(?:\s+de\s+\d{4})?|\d{1,2}/\d{1,2}/\d{2,4}|"
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
        search_site="site:linkedin.com",
        allowed_url_fragments=(
            "linkedin.com/posts",
            "linkedin.com/feed/update",
            "linkedin.com/pulse",
            "linkedin.com/company/",
            "linkedin.com/in/",
        ),
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


class GoogleRateLimitError(GoogleSearchError):
    def __init__(self, start: int, retry_after: float | None = None):
        message = f"Google devolviÃ³ HTTP 429 para start={start}."
        if retry_after is not None:
            message += f" Reintenta en aproximadamente {int(retry_after)} segundos."
        super().__init__(message)
        self.start = start
        self.retry_after = retry_after


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


def chunk_list(data: list, size: int):
    """Divide una lista en trozos de tamaÃ±o fijo."""
    for i in range(0, len(data), size):
        yield data[i : i + size]


def build_google_query(keywords: list[str], platform: PlatformConfig) -> str:
    """Construye una query de Google usando OR para agrupar keywords."""
    joined_keywords = " OR ".join(f'"{kw}"' for kw in keywords)
    # Query simplificada para mayor compatibilidad
    return f'{platform.search_site} ({joined_keywords})'


def attribute_best_keyword(title: str, snippet: str, keywords: list[str]) -> str:
    """Identifica cuÃ¡l de las keywords del lote coincide mejor con el resultado."""
    text = f"{title} {snippet}".lower()
    for kw in keywords:
        if kw.lower() in text:
            return kw
    return keywords[0] # Fallback al primer elemento del lote


def extract_google_result_url(raw_href: str) -> str:
    if not raw_href:
        return ""
    if raw_href.startswith("/url?"):
        parsed = urlparse(raw_href)
        query = parse_qs(parsed.query)
        return unquote(query.get("q", [""])[0])
    if raw_href.startswith("http"):
        parsed = urlparse(raw_href)
        cleaned = parsed._replace(query="", fragment="")
        return cleaned.geturl().rstrip("/")
    return raw_href


def is_allowed_result(url: str, platform: PlatformConfig) -> bool:
    normalized_url = (url or "").lower()
    if not normalized_url.startswith("http"):
        return False
    # VerificaciÃ³n por fragmentos permitidos
    return any(fragment in normalized_url for fragment in platform.allowed_url_fragments)


def iter_result_blocks(soup: BeautifulSoup) -> list:
    selectors = (
        "div.g",
        "div.MjjYud",
        "div.Gx5Zad",
        "div.tF2Cxc",
        "div.mnr-c",
        "div.v55uic",
        "div.yuRUbf",
    )
    blocks: list = []
    seen_nodes: set[int] = set()
    for selector in selectors:
        for node in soup.select(selector):
            marker = id(node)
            if marker in seen_nodes:
                continue
            seen_nodes.add(marker)
            blocks.append(node)
            
    # Si no hay bloques con clases conocidas, buscamos enlaces de resultados directamente
    if not blocks:
        for a_tag in soup.select('a[href^="http"]'):
            if "google.com" in a_tag["href"]:
                continue
            # Buscamos el contenedor padre que parezca un bloque de resultado
            parent = a_tag.find_parent("div")
            if parent and len(parent.get_text()) > 20:
                marker = id(parent)
                if marker not in seen_nodes:
                    seen_nodes.add(marker)
                    blocks.append(parent)
    return blocks


def extract_result_title(result_block) -> str:
    title_tag = result_block.select_one("h3")
    if title_tag:
        return " ".join(title_tag.get_text(" ", strip=True).split())
    aria_title_tag = result_block.select_one("a[aria-label]")
    if aria_title_tag:
        return " ".join(aria_title_tag.get("aria-label", "").split())
    return ""


def extract_result_snippet(result_block) -> str:
    snippet_tag = result_block.select_one(
        "div.VwiC3b, div.yXK7lf, span.aCOpRe, div.s3v9rd, "
        "div[data-sncf='1'], div.ITZIwc, div.kb0PBd, div.gxMdVd, "
        "div.MUF9yc"
    )
    if snippet_tag:
        return " ".join(snippet_tag.get_text(" ", strip=True).split())
    text_fragments = [
        fragment.strip()
        for fragment in result_block.stripped_strings
        if fragment.strip()
    ]
    if len(text_fragments) <= 1:
        return ""
    return " ".join(text_fragments[1:4])


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
    logger.debug("URL consultada: %s", response.url)
    
    if response.status_code == 429:
        retry_after_header = response.headers.get("Retry-After", "").strip()
        retry_after: float | None = None
        if retry_after_header.isdigit():
            retry_after = float(retry_after_header)
        raise GoogleRateLimitError(start=start, retry_after=retry_after)
    if response.status_code >= 400:
        raise GoogleSearchError(f"Google devolviÃ³ HTTP {response.status_code} para start={start}.")
    return response


def clamp_results_per_keyword(results_per_keyword: int) -> int:
    return max(1, min(results_per_keyword, MAX_GOOGLE_PAGES_PER_KEYWORD * 10))


def compute_backoff_seconds(
    min_delay_seconds: float,
    max_delay_seconds: float,
    attempt: int,
    retry_after: float | None = None,
) -> float:
    if retry_after is not None and retry_after > 0:
        return retry_after
    base_delay = max(max_delay_seconds, min_delay_seconds, DEFAULT_GOOGLE_BACKOFF_SECONDS)
    return min(base_delay * (2 ** max(attempt - 1, 0)), 300.0)


def parse_google_results(html: str, keywords: list[str], platform: PlatformConfig) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    parsed_results: list[dict] = []
    seen_links: set[str] = set()

    blocks = iter_result_blocks(soup)
    if not blocks:
        logger.debug("No se encontraron bloques de resultados con los selectores actuales.")
        # Debug HTML length
        logger.debug("TamaÃ±o HTML recibido: %d", len(html))

    for result_block in blocks:
        link_tag = result_block.select_one("a[href]")
        if not link_tag:
            continue

        link = extract_google_result_url(link_tag.get("href", ""))
        title = extract_result_title(result_block)
        if not title:
            continue
        if not is_allowed_result(link, platform) or link in seen_links:
            continue

        snippet = extract_result_snippet(result_block)
        seen_links.add(link)
        
        # Identificar la mejor keyword del lote para este resultado concreto
        best_kw = attribute_best_keyword(title, snippet, keywords)
        
        parsed_results.append(
            {
                "platform": platform.name,
                "keyword": best_kw,
                "titulo": title,
                "descripcion": snippet,
                "link": link,
                "fecha": extract_result_date(snippet),
                "relevancia_score": score_result(best_kw, title, snippet, link),
            }
        )

    return parsed_results


def search_keywords_batch(
    session: Session,
    keywords: list[str],
    results_per_batch: int,
    language: str,
    platform: PlatformConfig,
    min_delay_seconds: float,
    max_delay_seconds: float,
) -> list[dict]:
    query = build_google_query(keywords, platform)
    collected: list[dict] = []
    seen_links: set[str] = set()
    effective_limit = clamp_results_per_keyword(results_per_batch)
    planned_pages = max(1, (effective_limit + 9) // 10)
    max_rate_limit_retries = 2

    batch_display = ", ".join(keywords[:3]) + ("..." if len(keywords) > 3 else "")

    for start in range(0, planned_pages * 10, 10):
        response: Response | None = None
        for attempt in range(1, max_rate_limit_retries + 2):
            try:
                response = fetch_google_page(session, query=query, start=start, language=language)
                break
            except GoogleRateLimitError as exc:
                if start == 0:
                    raise GoogleRateLimitError(start=start, retry_after=exc.retry_after) from exc
                if attempt > max_rate_limit_retries:
                    raise GoogleRateLimitError(start=start, retry_after=exc.retry_after) from exc
                sleep_seconds = compute_backoff_seconds(
                    min_delay_seconds=min_delay_seconds,
                    max_delay_seconds=max_delay_seconds,
                    attempt=attempt,
                    retry_after=exc.retry_after,
                )
                logger.warning(
                    "HTTP 429 para lote [%s] en start=%s. Reintentando en %.2fs (intento %s/%s).",
                    batch_display,
                    start,
                    sleep_seconds,
                    attempt,
                    max_rate_limit_retries + 1,
                )
                time.sleep(sleep_seconds)
            except requests.RequestException as exc:
                raise GoogleSearchError(f"Fallo de red consultando Google para lote [%s]: {exc}" % batch_display) from exc

        if response is None:
            break

        page_results = parse_google_results(response.text, keywords=keywords, platform=platform)
        if not page_results:
            logger.info("Sin resultados parseables para lote [%s] en start=%s.", batch_display, start)
            break

        new_results = 0
        for item in page_results:
            if item["link"] in seen_links:
                continue
            collected.append(item)
            seen_links.add(item["link"])
            new_results += 1
            if len(collected) >= effective_limit:
                break

        if len(collected) >= effective_limit or new_results == 0:
            break

        sleep_seconds = random.uniform(min_delay_seconds, max_delay_seconds)
        logger.info("Sleep %.2fs antes de la siguiente pÃ¡gina para lote [%s].", sleep_seconds, batch_display)
        time.sleep(sleep_seconds)

    return collected[:effective_limit]


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
        print("Sin resultados para los parÃ¡metros indicados.")
        return
    for row in df.itertuples(index=False):
        print(f"{row.titulo} â€” {row.keyword} â€” {row.link}")


def collect_monitor_results(
    keywords: list[str],
    results_per_keyword: int,
    language: str,
    platform_name: str,
    lowercase_text: bool,
    min_delay_seconds: float,
    max_delay_seconds: float,
) -> pd.DataFrame:
    platform = PLATFORM_CONFIG[platform_name]
    session = build_session()
    all_results: list[dict] = []
    
    # Normalizamos keywords
    clean_keywords = [kw.strip() for kw in keywords if kw.strip()]
    if not clean_keywords:
        return clean_results([], platform)

    # Agrupamos por lotes para reducir llamadas a Google
    batches = list(chunk_list(clean_keywords, GOOGLE_KEYWORDS_BATCH_SIZE))
    logger.info("Iniciando monitoreo Google en %d lotes (Total keywords: %d).", len(batches), len(clean_keywords))

    # Para el lote completo, pedimos un poco mÃ¡s de resultados que para una sola kw
    # pero manteniendo un lÃ­mite razonable para evitar bloqueos.
    results_per_batch = max(results_per_keyword, 30)

    for i, batch in enumerate(batches, 1):
        logger.info("Procesando lote %d/%d: %s", i, len(batches), batch)
        
        batch_results = search_keywords_batch(
            session=session,
            keywords=batch,
            results_per_batch=results_per_batch,
            language=language,
            platform=platform,
            min_delay_seconds=min_delay_seconds,
            max_delay_seconds=max_delay_seconds,
        )
        all_results.extend(batch_results)

        if i < len(batches):
            sleep_seconds = random.uniform(min_delay_seconds * 2, max_delay_seconds * 2)
            logger.info("Sleep de seguridad %.2fs antes del siguiente lote.", sleep_seconds)
            time.sleep(sleep_seconds)

    return clean_results(all_results, platform=platform, lowercase_text=lowercase_text)


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
    cleaned_df = collect_monitor_results(
        keywords=keywords,
        results_per_keyword=results_per_keyword,
        language=language,
        platform_name=platform_name,
        lowercase_text=lowercase_text,
        min_delay_seconds=min_delay_seconds,
        max_delay_seconds=max_delay_seconds,
    )
    csv_path = Path(platform.default_output_csv)
    excel_path = Path(platform.default_output_excel) if export_excel else None
    export_results(cleaned_df, csv_path=csv_path, excel_path=excel_path)
    return cleaned_df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitorea menciones pÃºblicas en LinkedIn o X usando Google como proxy de bÃºsqueda.",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=DEFAULT_KEYWORDS,
        help='Lista de keywords. Ejemplo: --keywords "Andess" "agua potable" "APR"',
    )
    parser.add_argument("--results-per-keyword", type=int, default=20, help="MÃ¡ximo de resultados a recuperar por keyword.")
    parser.add_argument("--language", default="es", help="Idioma para Google. Por defecto: es.")
    parser.add_argument(
        "--platform",
        choices=sorted(PLATFORM_CONFIG.keys()),
        default="linkedin",
        help="Plataforma objetivo. Usa 'linkedin' para linkedin.com/posts o 'x' como opciÃ³n 2 vÃ­a Google.",
    )
    parser.add_argument("--lowercase-text", action="store_true", help="Normaliza tÃ­tulo y descripciÃ³n a minÃºsculas.")
    parser.add_argument("--no-excel", action="store_true", help="Desactiva la exportaciÃ³n a Excel.")
    parser.add_argument("--min-delay", type=float, default=2.0, help="Espera mÃ­nima entre requests.")
    parser.add_argument("--max-delay", type=float, default=4.0, help="Espera mÃ¡xima entre requests.")
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
