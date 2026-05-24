"""
OpenFDA source integration.
REST API — no key required (rate limited at 1000 req/day without key).
Endpoint: https://api.fda.gov/drug/label.json
Returns structured drug label information including indications, dosing,
warnings, and contraindications.
"""
import requests
from .schema import Result

BASE_URL = "https://api.fda.gov/drug/label.json"
TIMEOUT = 12


def fetch(query: str, settings: dict = None) -> list:
    """
    Query OpenFDA drug label search.
    Returns drug label results matching the query terms.
    """
    settings = settings or {}
    results = []

    # Extract drug/condition terms — OpenFDA does best with specific drug names
    # or conditions from the query
    params = {
        "search": f"indications_and_usage:{query}",
        "limit": 8,
    }

    try:
        resp = requests.get(BASE_URL, params=params, timeout=TIMEOUT,
                            headers={"User-Agent": "EvidAnce/1.0"})
        if resp.status_code == 404:
            # Try broader search
            params["search"] = query
            resp = requests.get(BASE_URL, params=params, timeout=TIMEOUT,
                                headers={"User-Agent": "EvidAnce/1.0"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[OpenFDA] fetch error: {e}")
        return []

    for item in data.get('results', [])[:8]:
        # Extract brand name or generic name
        brand  = item.get('openfda', {}).get('brand_name', [])
        generic = item.get('openfda', {}).get('generic_name', [])
        manufacturer = item.get('openfda', {}).get('manufacturer_name', [])

        title = (brand[0] if brand else '') or (generic[0] if generic else 'Unknown Drug')

        # Compose abstract from key label sections
        indications = ' '.join(item.get('indications_and_usage', [])[:1])
        dosage      = ' '.join(item.get('dosage_and_administration', [])[:1])
        warnings    = ' '.join(item.get('warnings', [])[:1])
        contraindications = ' '.join(item.get('contraindications', [])[:1])

        abstract = _build_abstract(indications, dosage, warnings, contraindications)
        if not abstract.strip():
            continue

        # Build a meaningful URL to FDA label search
        if generic:
            search_term = generic[0].replace(' ', '+')
        elif brand:
            search_term = brand[0].replace(' ', '+')
        else:
            search_term = query.replace(' ', '+')
        url = f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={item.get('openfda', {}).get('application_number', [''])[0]}"

        authors = [m for m in manufacturer[:2]]

        results.append(Result(
            source='openfda',
            title=f"Drug Label: {title}",
            authors=authors,
            year=None,
            journal='FDA Drug Label',
            abstract=abstract[:1200],
            url=url if 'ApplNo=' in url and url[-1] != '=' else f"https://labels.fda.gov/",
            region_tag='extrapolated',
            evidence_tier='guideline',
        ))

    return results


def _build_abstract(indications, dosage, warnings, contraindications):
    parts = []
    if indications:
        parts.append(f"INDICATIONS: {indications[:400]}")
    if dosage:
        parts.append(f"DOSAGE: {dosage[:400]}")
    if warnings:
        parts.append(f"WARNINGS: {warnings[:300]}")
    if contraindications:
        parts.append(f"CONTRAINDICATIONS: {contraindications[:300]}")
    return '\n'.join(parts)
