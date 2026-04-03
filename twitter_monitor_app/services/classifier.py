from __future__ import annotations

from typing import Dict, List

from data.keywords import CHILE_CONTEXT_TERMS, COMPANIES, PEOPLE, RISK_TERMS, SECTOR_TOPICS
from utils.text_utils import contains_any_term, find_matching_terms, looks_spanish, normalize_text


def detect_chile_context(text: str) -> bool:
    return contains_any_term(text, CHILE_CONTEXT_TERMS)


def classify_tweet(tweet: Dict) -> Dict:
    text = tweet.get("text", "")
    normalized = normalize_text(text)
    matches: List[Dict] = []

    for category, terms in SECTOR_TOPICS.items():
        for term in find_matching_terms(normalized, terms):
            matches.append({"match_type": "category", "group": category, "term": term})

    for company, aliases in COMPANIES.items():
        for term in find_matching_terms(normalized, aliases):
            matches.append({"match_type": "company", "group": company, "term": term})

    for person, aliases in PEOPLE.items():
        for term in find_matching_terms(normalized, aliases):
            matches.append({"match_type": "person", "group": person, "term": term})

    risk_matches = find_matching_terms(normalized, RISK_TERMS)
    for term in risk_matches:
        matches.append({"match_type": "risk", "group": "Riesgo reputacional", "term": term})

    category_detected = ", ".join(sorted({item["group"] for item in matches if item["match_type"] == "category"})) or "Sin categoría"
    first_keyword = matches[0]["term"] if matches else ""

    return {
        "normalized_text": normalized,
        "is_spanish": looks_spanish(tweet),
        "is_chile_context": detect_chile_context(normalized),
        "matches": matches,
        "category_detected": category_detected,
        "matched_keyword": first_keyword,
        "risk_terms": risk_matches,
    }


def post_process_tweets(tweets: List[Dict], strict_keyword_filter: bool = True) -> List[Dict]:
    processed = []
    seen_ids = set()

    for tweet in tweets:
        tweet_id = tweet.get("id")
        if tweet_id in seen_ids:
            continue
        seen_ids.add(tweet_id)

        enriched = {**tweet, **classify_tweet(tweet)}
        if not enriched["is_spanish"]:
            continue
        if strict_keyword_filter and not enriched["matches"]:
            continue
        processed.append(enriched)

    return processed
