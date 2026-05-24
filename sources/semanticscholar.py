"""
Semantic Scholar source integration.
Free REST API — no key for basic usage.
Endpoint: https://api.semanticscholar.org/graph/v1/paper/search
Uses citation count as a relevance signal (stored in abstract metadata).
"""
import requests
from .schema import Result, classify_region_tag, classify_evidence_tier

BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
TIMEOUT = 12
FIELDS = "title,authors,year,abstract,externalIds,citationCount,influentialCitationCount,journal,publicationTypes"


def fetch(query: str, settings: dict = None) -> list:
    """
    Search Semantic Scholar for the given query.
    Returns list of Result objects.
    """
    settings = settings or {}
    params = {
        "query": query,
        "limit": 12,
        "fields": FIELDS,
    }

    try:
        resp = requests.get(BASE_URL, params=params, timeout=TIMEOUT,
                            headers={"User-Agent": "EvidAnce/1.0 (clinical-evidence-tool)"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[SemanticScholar] fetch error: {e}")
        return []

    results = []
    for item in data.get("data", []):
        title = (item.get("title") or "").strip()
        abstract = (item.get("abstract") or "").strip()
        year = item.get("year")
        citation_count = item.get("citationCount", 0) or 0
        journal_info = item.get("journal") or {}
        journal = journal_info.get("name") if journal_info else None

        authors = [
            a.get("name", "") for a in (item.get("authors") or [])
        ][:6]

        # Build URL from external IDs
        ext = item.get("externalIds") or {}
        doi = ext.get("DOI")
        paper_id = item.get("paperId", "")
        if doi:
            source_url = f"https://doi.org/{doi}"
        else:
            source_url = f"https://www.semanticscholar.org/paper/{paper_id}"

        # Embed citation count hint into abstract for scorer context
        citation_note = f" [Citations: {citation_count}]" if citation_count else ""
        enriched_abstract = abstract + citation_note

        combined_text = f"{title} {abstract} {journal or ''}"
        region_tag = classify_region_tag(combined_text)
        evidence_tier = classify_evidence_tier(f"{title} {abstract}")

        # Boost evidence tier for highly influential papers
        pub_types = item.get("publicationTypes") or []
        if "Review" in pub_types or "Meta-Analysis" in pub_types:
            evidence_tier = "systematic_review"
        elif "ClinicalTrial" in pub_types:
            evidence_tier = "rct"

        if not title:
            continue

        results.append(Result(
            source="semanticscholar",
            title=title,
            authors=authors,
            year=year,
            journal=journal,
            abstract=enriched_abstract[:1200],
            url=source_url,
            region_tag=region_tag,
            evidence_tier=evidence_tier,
        ))

    return results
