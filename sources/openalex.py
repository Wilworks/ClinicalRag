"""
OpenAlex source integration.
No API key required (uses polite pool with email param).
Returns concepts, institutions, countries — used for West Africa tagging.
Endpoint: https://api.openalex.org/works
"""
import requests
from .schema import Result, classify_region_tag, classify_evidence_tier

BASE_URL = "https://api.openalex.org/works"
POLITE_EMAIL = "evidance-tool@example.com"   # polite pool — no key needed
TIMEOUT = 12

WEST_AFRICA_COUNTRY_CODES = {
    "GH", "NG", "SN", "CI", "ML", "BF", "GN", "BJ", "TG", "LR",
    "SL", "GM", "GW", "CV", "MR", "NE",
}
SUBSAHARAN_COUNTRY_CODES = {
    "ET", "KE", "TZ", "UG", "CM", "CD", "ZA", "ZM", "ZW", "MZ",
    "MW", "RW", "SO", "SD", "SS", "TD", "AO", "NA",
}


def _infer_region_from_institutions(authorships: list) -> str:
    """Use OpenAlex institution country codes for precise region tagging."""
    found_codes = set()
    for authorship in authorships:
        for inst in authorship.get("institutions", []):
            cc = inst.get("country_code", "")
            if cc:
                found_codes.add(cc)

    if found_codes & WEST_AFRICA_COUNTRY_CODES:
        return "regional"
    if found_codes & SUBSAHARAN_COUNTRY_CODES:
        return "adjacent"
    return "extrapolated"


def fetch(query: str, settings: dict = None) -> list:
    """
    Search OpenAlex for the given query.
    Returns list of Result objects with institution-based region tagging.
    """
    settings = settings or {}
    params = {
        "search": query,
        "per-page": 12,
        "mailto": POLITE_EMAIL,
        "select": "id,title,authorships,publication_year,primary_location,abstract_inverted_index,cited_by_count,type",
    }

    try:
        resp = requests.get(BASE_URL, params=params, timeout=TIMEOUT,
                            headers={"User-Agent": "EvidAnce/1.0"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[OpenAlex] fetch error: {e}")
        return []

    results = []
    for item in data.get("results", []):
        title = (item.get("title") or "").strip()
        year = item.get("publication_year")

        # Reconstruct abstract from inverted index (OpenAlex format)
        inv_idx = item.get("abstract_inverted_index") or {}
        abstract = _reconstruct_abstract(inv_idx)

        # Journal / source info
        location = item.get("primary_location") or {}
        source_info = location.get("source") or {}
        journal = source_info.get("display_name")
        landing_url = location.get("landing_page_url") or item.get("id", "")

        # Authors
        authorships = item.get("authorships") or []
        authors = [
            a.get("author", {}).get("display_name", "")
            for a in authorships[:6]
        ]

        # Region tag from institution country codes (precise)
        region_tag = _infer_region_from_institutions(authorships)
        if region_tag == "extrapolated":
            # Fallback to text-based classification
            region_tag = classify_region_tag(f"{title} {abstract}")

        evidence_tier = classify_evidence_tier(f"{title} {abstract}")
        work_type = item.get("type", "")
        if work_type in ("review", "book-chapter"):
            evidence_tier = "systematic_review"

        if not title:
            continue

        results.append(Result(
            source="openalex",
            title=title,
            authors=authors,
            year=year,
            journal=journal,
            abstract=abstract[:1200],
            url=landing_url,
            region_tag=region_tag,
            evidence_tier=evidence_tier,
        ))

    return results


def _reconstruct_abstract(inverted_index: dict) -> str:
    """
    OpenAlex stores abstracts as an inverted index: {word: [positions]}.
    This reconstructs the original text.
    """
    if not inverted_index:
        return ""
    try:
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort(key=lambda x: x[0])
        return " ".join(w for _, w in word_positions)
    except Exception:
        return ""
