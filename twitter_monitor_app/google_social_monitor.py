from __future__ import annotations

import argparse
import logging
import os
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
SERPER_API_URL = "https://google.serper.dev/search"

DEFAULT_KEYWORDS = ["Andess", "agua potable", "APR", "servicios sanitarios", "Aguas Andinas"]
MAX_GOOGLE_PAGES_PER_KEYWORD = 20
DEFAULT_GOOGLE_BACKOFF_SECONDS = 30.0
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
        allowed_methods=frozenset({"GET", "POST"}),
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
            "Accept": "application/json, text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        }
    )
    session.request_timeout = timeout
    return session


def chunk_list(data: list, size: int):
    for i in range(0, len(data), size):
        yield data[i : i + size]


def build_google_query(keywords: list[str], platform: PlatformConfig) -> str:
    joined_keywords = " OR ".join(f'"{kw}"' for kw in keywords)
    return f'{platform.search_site} ({joined_keywords})'


def attribute_best_keyword(title: str, snippet: str, keywords: list[str]) -> str:
    text = f"{title} {snippet}".lower()
    for kw in keywords:
        if kw.lower() in text:
            return kw
    return keywords[0]


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
    return any(fragment in normalized_url for fragment in platform.allowed_url_fragments)


def fetch_serper_results(session: Session, api_key: str, query: str, num: int, language: str) -> list[dict]:
    """Consulta la API de Serper.dev para obtener resultados de Google en JSON."""
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "q": query,
        "num": num,
        "gl": "cl",
        "hl": language,
    }
    try:
        response = session.post(SERPER_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        results = []
        # Serper devuelve resultados en 'organic'
        for item in data.get("organic", []):
            results.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "date": item.get("date", "")
            })
        return results
    except Exception as exc:
        logger.error("Error consultando Serper.dev: %s", exc)
        return []


def iter_result_blocks(soup: BeautifulSoup) -> list:
    selectors = ("div.g", "div.MjjYud", "div.Gx5Zad", "div.tF2Cxc", "div.mnr-c", "div.v55uic", "div.yuRUbf")
    blocks: list = []
    seen_nodes: set[int] = set()
    for selector in selectors:
        for node in soup.select(selector):
            marker = id(node)
            if marker in seen_nodes: continue
            seen_nodes.add(marker)
            blocks.append(node)
    if not blocks:
        for a_tag in soup.select('a[href^="http"]'):
            if "google.com" in a_tag["href"]: continue
            parent = a_tag.find_parent("div")
            if parent and len(parent.get_text()) > 20:
                marker = id(parent)
                if marker not in seen_nodes:
                    seen_nodes.add(marker)
                    blocks.append(parent)
    return blocks


def extract_result_title(result_block) -> str:
    title_tag = result_block.select_one("h3")
    if title_tag: return " ".join(title_tag.get_text(" ", strip=True).split())
    aria_title_tag = result_block.select_one("a[aria-label]")
    if aria_title_tag: return " ".join(aria_title_tag.get("aria-label", "").split())
    return ""


def extract_result_snippet(result_block) -> str:
    snippet_tag = result_block.select_one("div.VwiC3b, div.yXK7lf, span.aCOpRe, div.s3v9rd, div[data-sncf='1'], div.ITZIwc, div.kb0PBd, div.gxMdVd, div.MUF9yc")
    if snippet_tag: return " ".join(snippet_tag.get_text(" ", strip=True).split())
    text_fragments = [f.strip() for f in result_block.stripped_strings if f.strip()]
    return " ".join(text_fragments[1:4]) if len(text_fragments) > 1 else ""


def extract_result_date(snippet: str) -> str:
    match = DATE_PATTERN.search(snippet or "")
    return match.group(0) if match else ""


def score_result(keyword: str, title: str, snippet: str, url: str) -> int:
    normalized_keyword = keyword.casefold().strip()
    score = 0
    if normalized_keyword:
        if normalized_keyword in (title or "").casefold(): score += 1
        if normalized_keyword in (snippet or "").casefold(): score += 1
        if normalized_keyword in (url or "").casefold(): score += 1
    return score


def fetch_google_page(session: Session, query: str, start: int, language: str) -> Response:
    params = {"q": query, "hl": language, "gl": "cl", "lr": f"lang_{language}", "num": 10, "start": start, "safe": "off"}
    response = session.get(GOOGLE_SEARCH_URL, params=params, timeout=session.request_timeout)
    if response.status_code == 429:
        raise GoogleRateLimitError(start=start)
    response.raise_for_status()
    return response


def parse_google_results(html: str, keywords: list[str], platform: PlatformConfig) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    parsed_results: list[dict] = []
    seen_links: set[str] = set()
    for result_block in iter_result_blocks(soup):
        link_tag = result_block.select_one("a[href]")
        if not link_tag: continue
        link = extract_google_result_url(link_tag.get("href", ""))
        title = extract_result_title(result_block)
        if not title or not is_allowed_result(link, platform) or link in seen_links: continue
        snippet = extract_result_snippet(result_block)
        seen_links.add(link)
        best_kw = attribute_best_keyword(title, snippet, keywords)
        parsed_results.append({
            "platform": platform.name, "keyword": best_kw, "titulo": title, "descripcion": snippet,
            "link": link, "fecha": extract_result_date(snippet), "relevancia_score": score_result(best_kw, title, snippet, link)
        })
    return parsed_results


def search_keywords_batch(session: Session, keywords: list[str], results_per_batch: int, language: str, platform: PlatformConfig, min_delay: float, max_delay: float) -> list[dict]:
    # Intentar usar Serper API si hay KEY disponible
    api_key = os.environ.get("SERPER_API_KEY")
    if api_key:
        logger.info("Usando API Serper.dev para lote: %s", keywords)
        query = build_google_query(keywords, platform)
        raw_results = fetch_serper_results(session, api_key, query, results_per_batch, language)
        
        collected = []
        for res in raw_results:
            if not is_allowed_result(res["link"], platform): continue
            best_kw = attribute_best_keyword(res["title"], res["snippet"], keywords)
            collected.append({
                "platform": platform.name, "keyword": best_kw, "titulo": res["title"], "descripcion": res["snippet"],
                "link": res["link"], "fecha": res.get("date", extract_result_date(res["snippet"])),
                "relevancia_score": score_result(best_kw, res["title"], res["snippet"], res["link"])
            })
        return collected

    # Fallback a Scraping si no hay API Key
    logger.info("No se detectÃ³ SERPER_API_KEY. Usando scraping (inestable).")
    query = build_google_query(keywords, platform)
    collected: list[dict] = []
    seen_links: set[str] = set()
    effective_limit = max(1, min(results_per_batch, MAX_GOOGLE_PAGES_PER_KEYWORD * 10))
    
    for start in range(0, ((effective_limit + 9) // 10) * 10, 10):
        try:
            response = fetch_google_page(session, query, start, language)
            page_results = parse_google_results(response.text, keywords, platform)
            if not page_results: break
            
            for item in page_results:
                if item["link"] in seen_links: continue
                collected.append(item)
                seen_links.add(item["link"])
                if len(collected) >= effective_limit: break
            if len(collected) >= effective_limit: break
            time.sleep(random.uniform(min_delay, max_delay))
        except Exception as exc:
            logger.error("Error en scraping para lote: %s", exc)
            break
    return collected


def collect_monitor_results(keywords: list[str], results_per_kw: int, language: str, platform_name: str, lowercase: bool, min_delay: float, max_delay: float) -> pd.DataFrame:
    platform = PLATFORM_CONFIG[platform_name]
    session = build_session()
    all_results: list[dict] = []
    clean_kw = [k.strip() for k in keywords if k.strip()]
    if not clean_kw: return pd.DataFrame()

    batches = list(chunk_list(clean_kw, GOOGLE_KEYWORDS_BATCH_SIZE))
    results_per_batch = max(results_per_kw, 30)

    for i, batch in enumerate(batches, 1):
        logger.info("Procesando lote %d/%d: %s", i, len(batches), batch)
        batch_results = search_keywords_batch(session, batch, results_per_batch, language, platform, min_delay, max_delay)
        all_results.extend(batch_results)
        if i < len(batches) and not os.environ.get("SERPER_API_KEY"):
            time.sleep(random.uniform(min_delay * 2, max_delay * 2))

    df = pd.DataFrame(all_results)
    if df.empty: return pd.DataFrame(columns=["platform", "keyword", "titulo", "descripcion", "link", "fecha", "relevancia_score", "execution_timestamp"])
    
    df = df.drop_duplicates(subset=["keyword", "link"]).copy()
    if lowercase:
        for col in ("titulo", "descripcion"): df[col] = df[col].fillna("").str.lower()
    df["execution_timestamp"] = datetime.now(timezone.utc).isoformat()
    return df.sort_values(by=["keyword", "relevancia_score", "titulo"], ascending=[True, False, True]).reset_index(drop=True)


def run_monitor(keywords: list[str], results_per_kw: int, language: str, platform_name: str, lowercase: bool, export_excel: bool, min_delay: float, max_delay: float) -> pd.DataFrame:
    df = collect_monitor_results(keywords, results_per_kw, language, platform_name, lowercase, min_delay, max_delay)
    platform = PLATFORM_CONFIG[platform_name]
    df.to_csv(platform.default_output_csv, index=False, encoding="utf-8-sig")
    if export_excel: df.to_excel(platform.default_output_excel, index=False)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitorea LinkedIn/X usando Serper API o Google Scraping.")
    parser.add_argument("--keywords", nargs="+", default=DEFAULT_KEYWORDS)
    parser.add_argument("--results-per-keyword", type=int, default=20)
    parser.add_argument("--language", default="es")
    parser.add_argument("--platform", choices=sorted(PLATFORM_CONFIG.keys()), default="linkedin")
    parser.add_argument("--lowercase-text", action="store_true")
    parser.add_argument("--no-excel", action="store_true")
    parser.add_argument("--min-delay", type=float, default=2.0)
    parser.add_argument("--max-delay", type=float, default=4.0)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s | %(levelname)s | %(message)s")    
    df = run_monitor(args.keywords, args.results_per_keyword, args.language, args.platform, args.lowercase_text, not args.no_excel, args.min_delay, args.max_delay)
    
    if df.empty:
        print("Sin resultados.")
    else:
        for row in df.itertuples(index=False): print(f"{row.titulo} - {row.keyword} - {row.link}")
        print(f"\nTotal filas: {len(df)}")


if __name__ == "__main__":
    main()
