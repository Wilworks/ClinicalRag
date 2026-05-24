"""
Europe PMC source integration.
REST API — no key required. Strong African/open-access coverage.
Endpoint: https://www.ebi.ac.uk/europepmc/webservices/rest/search
"""
import requests
from .schema import Result, classify_region_tag, classify_evidence_tier

BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
TIMEOUT = 12


def fetch(query: str, settings: dict = None) -> list:
    """
    Search Europe PMC for the given query.
    Returns list of Result objects.
    """
    settings = settings or {}
    params = {
        "query": query,
        "format": "json",
        "pageSize": 15,
        "resultType": "core",
        "sort": "CITED desc",
    }

    try:
        resp = requests.get(BASE_URL, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[EuropePMC] fetch error: {e}")
        return []

    results = []
    for item in data.get("resultList", {}).get("result", []):
        title = item.get("title", "").strip().rstrip(".")
        abstract = item.get("abstractText", "") or ""
        journal = item.get("journalTitle", None)
        year_raw = item.get("pubYear", None)
        year = int(year_raw) if year_raw else None

        # Authors list
        author_list = item.get("authorList", {}).get("author", [])
        authors = [
            f"{a.get('lastName', '')} {a.get('initials', '')}".strip()
            for a in author_list
        ][:6]

        url = item.get("fullTextUrlList", {})
        url_links = url.get("fullTextUrl", []) if url else []
        source_url = next(
            (u["url"] for u in url_links if "europepmc" in u.get("url", "")),
            f"https://europepmc.org/article/{item.get('source','')}/{item.get('id','')}",
        )

        combined_text = f"{title} {abstract} {journal or ''}"
        region_tag = classify_region_tag(combined_text)
        evidence_tier = classify_evidence_tier(f"{title} {abstract}")

        if not title:
            continue

        results.append(Result(
            source="europepmc",
            title=title,
            authors=authors,
            year=year,
            journal=journal,
            abstract=abstract[:1200],
            url=source_url,
            region_tag=region_tag,
            evidence_tier=evidence_tier,
        ))

    return results
