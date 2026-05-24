"""
DOAJ (Directory of Open Access Journals) source integration.
REST API — no key required.
Endpoint: https://doaj.org/api/search/articles/{query}
Returns open-access African health journal articles, particularly strong
for Malawi Medical Journal, African Journal of Medicine, etc.
"""
import requests
from .schema import Result, classify_region_tag, classify_evidence_tier

BASE_URL = "https://doaj.org/api/search/articles/{query}"
TIMEOUT = 12

# African health journals indexed in DOAJ
AFRICAN_JOURNALS = {
    'african journal',
    'ghana medical',
    'nigerian medical',
    'east african',
    'south african medical',
    'malawi medical',
    'kenya medical',
    'ethiopian journal',
    'annals of african',
    'pan african',
    'west african journal',
    'journal of west african',
    'tropical medicine',
    'tropical doctor',
    'bulletin of the world health organization',
}


def fetch(query: str, settings: dict = None) -> list:
    """
    Search DOAJ for open-access articles matching the query.
    Biases toward African journal results.
    """
    settings = settings or {}
    region = settings.get('region', 'west_africa')
    results = []

    # Build DOAJ query — add African filter for regional queries
    doaj_query = query
    if region in ('west_africa', 'subsaharan', 'pan_africa'):
        doaj_query = f"{query} Africa"

    import urllib.parse
    encoded = urllib.parse.quote(doaj_query)
    url = BASE_URL.format(query=encoded)

    params = {
        "pageSize": 10,
        "page":     1,
        "sort":     "year:desc",
    }

    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT,
                            headers={
                                "User-Agent": "EvidAnce/1.0",
                                "Accept": "application/json",
                            })
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[DOAJ] fetch error: {e}")
        return []

    for item in data.get('results', [])[:10]:
        bibjson = item.get('bibjson', {})

        title   = bibjson.get('title', '')
        abstract_text = bibjson.get('abstract', '')
        journal = bibjson.get('journal', {})
        journal_title = journal.get('title', '') if isinstance(journal, dict) else ''
        year    = bibjson.get('year')
        if year:
            try:
                year = int(year)
            except (TypeError, ValueError):
                year = None

        # Authors
        raw_authors = bibjson.get('author', [])
        authors = [
            f"{a.get('name','')}" for a in raw_authors[:3]
            if a.get('name')
        ]

        # URL / DOI
        link_list = bibjson.get('link', [])
        article_url = next(
            (l.get('url', '') for l in link_list if l.get('type') == 'fulltext'),
            next((l.get('url', '') for l in link_list), '')
        )
        doi = bibjson.get('identifier', [{}])
        doi_val = next((i.get('id') for i in doi if i.get('type') == 'doi'), None)
        if doi_val and not article_url:
            article_url = f"https://doi.org/{doi_val}"
        if not article_url:
            article_url = 'https://doaj.org'

        if not title or not abstract_text:
            continue

        combined = f"{title} {abstract_text} {journal_title}".lower()
        region_tag    = classify_region_tag(combined)
        evidence_tier = classify_evidence_tier(combined)

        # Boost score for known African journals
        is_african_journal = any(kw in journal_title.lower() for kw in AFRICAN_JOURNALS)
        if is_african_journal and region_tag == 'extrapolated':
            region_tag = 'adjacent'

        results.append(Result(
            source='doaj',
            title=title,
            authors=authors,
            year=year,
            journal=journal_title or 'DOAJ',
            abstract=abstract_text[:1200],
            url=article_url,
            region_tag=region_tag,
            evidence_tier=evidence_tier,
        ))

    return results
