"""
WHO IRIS source integration.
OAI-PMH API — no key required.
Endpoint: https://iris.who.int/oai/request
Returns WHO guidelines, technical reports, and policy documents.
"""
import requests
import xml.etree.ElementTree as ET
from .schema import Result, classify_region_tag, classify_evidence_tier

BASE_URL = "https://iris.who.int/oai/request"
TIMEOUT = 15

OAI_NS = {
    'oai': 'http://www.openarchives.org/OAI/2.0/',
    'dc':  'http://purl.org/dc/elements/1.1/',
    'oai_dc': 'http://www.openarchives.org/OAI/2.0/oai_dc/',
}


def fetch(query: str, settings: dict = None) -> list:
    """
    Search WHO IRIS via OAI-PMH ListRecords with dc:subject filtering.
    Falls back to keyword-filtered ListRecords from recent records.
    """
    settings = settings or {}
    results = []

    # OAI-PMH: search recent records, filter by query keywords
    params = {
        "verb": "ListRecords",
        "metadataPrefix": "oai_dc",
        "set": "col_10665_252197",  # WHO Essential Medicines collection
    }

    try:
        resp = requests.get(BASE_URL, params=params, timeout=TIMEOUT,
                            headers={"User-Agent": "EvidAnce/1.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception as e:
        print(f"[WHOIRIS] fetch error: {e}")
        return []

    keywords = set(query.lower().split())

    for record in root.findall('.//oai:record', OAI_NS):
        metadata = record.find('.//oai_dc:dc', OAI_NS)
        if metadata is None:
            continue

        def get_text(tag):
            elements = metadata.findall(f'dc:{tag}', OAI_NS)
            return [e.text.strip() for e in elements if e.text]

        titles   = get_text('title')
        subjects = get_text('subject')
        descs    = get_text('description')
        creators = get_text('creator')
        dates    = get_text('date')
        ids      = get_text('identifier')

        title    = titles[0] if titles else ''
        abstract = ' '.join(descs[:2])
        combined = f"{title} {abstract} {' '.join(subjects)}".lower()

        # Keyword relevance filter
        if not any(kw in combined for kw in keywords):
            continue

        # Extract year from date
        year = None
        for d in dates:
            if d and len(d) >= 4 and d[:4].isdigit():
                year = int(d[:4])
                break

        # Extract URL from identifiers
        url = next((i for i in ids if i.startswith('http')),
                   'https://iris.who.int/')

        region_tag    = classify_region_tag(combined)
        evidence_tier = classify_evidence_tier(combined)
        # WHO docs are always guidelines tier
        evidence_tier = 'guideline'

        if not title:
            continue

        results.append(Result(
            source='whoiris',
            title=title,
            authors=creators[:3],
            year=year,
            journal='WHO IRIS',
            abstract=abstract[:1200],
            url=url,
            region_tag=region_tag,
            evidence_tier=evidence_tier,
        ))

        if len(results) >= 8:
            break

    return results
