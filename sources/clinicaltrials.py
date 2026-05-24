"""
ClinicalTrials.gov source integration.
REST API v2 — no key required.
Endpoint: https://clinicaltrials.gov/api/v2/studies
Returns interventional studies, RCTs, and observational trials.
"""
import requests
from .schema import Result, classify_region_tag, classify_evidence_tier

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
TIMEOUT = 14

# West Africa country codes for location filtering
WEST_AFRICA_COUNTRIES = [
    'Nigeria', 'Ghana', 'Senegal', 'Côte d\'Ivoire', 'Mali', 'Niger',
    'Burkina Faso', 'Guinea', 'Benin', 'Togo', 'Liberia', 'Sierra Leone',
    'Gambia', 'Guinea-Bissau', 'Mauritania', 'Cape Verde',
    'Cameroon', 'South Africa', 'Kenya', 'Ethiopia', 'Tanzania',
    'Uganda', 'Zimbabwe', 'Zambia', 'Malawi', 'Mozambique',
]

STUDY_TYPE_TIER = {
    'INTERVENTIONAL':  'rct',
    'OBSERVATIONAL':   'observational',
    'EXPANDED_ACCESS': 'other',
}


def fetch(query: str, settings: dict = None) -> list:
    """
    Query ClinicalTrials.gov v2 API for relevant studies.
    Prioritises West African sites when the region setting indicates.
    """
    settings = settings or {}
    region = settings.get('region', 'west_africa')
    results = []

    params = {
        "query.cond":  query,
        "pageSize":    10,
        "sort":        "LastUpdatePostDate:desc",
        "fields":      "NCTId,BriefTitle,OfficialTitle,BriefSummary,DetailedDescription,"
                       "Phase,StudyType,StartDate,CompletionDate,OverallStatus,"
                       "LocationCountry,InterventionName,Condition,LeadSponsorName",
    }

    # Apply location filter for West Africa / Africa regions
    if region in ('west_africa', 'subsaharan', 'pan_africa'):
        params["query.locn"] = "Africa"

    try:
        resp = requests.get(BASE_URL, params=params, timeout=TIMEOUT,
                            headers={
                                "User-Agent": "EvidAnce/1.0",
                                "Accept": "application/json",
                            })
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[ClinicalTrials] fetch error: {e}")
        return []

    for study in data.get('studies', [])[:10]:
        proto = study.get('protocolSection', {})
        ident = proto.get('identificationModule', {})
        desc  = proto.get('descriptionModule', {})
        design = proto.get('designModule', {})
        status = proto.get('statusModule', {})
        contacts = proto.get('contactsLocationsModule', {})
        interventions = proto.get('armsInterventionsModule', {})
        sponsor = proto.get('sponsorCollaboratorsModule', {})

        nct_id    = ident.get('nctId', '')
        title     = ident.get('briefTitle') or ident.get('officialTitle') or ''
        summary   = desc.get('briefSummary', '')
        detail    = desc.get('detailedDescription', '')
        phase     = ' '.join(design.get('phases', []))
        study_type = design.get('studyType', 'INTERVENTIONAL')

        # Year from start date
        start_date = status.get('startDateStruct', {}).get('date', '')
        year = int(start_date[:4]) if start_date and start_date[:4].isdigit() else None

        # Countries for region tag
        locations = contacts.get('locations', [])
        countries  = list({loc.get('country', '') for loc in locations if loc.get('country')})
        if not countries:
            # Fall back from location module
            countries = design.get('locationCountries', {}).get('locationCountry', [])

        abstract = _build_abstract(summary, detail, phase, study_type, countries)
        if not title:
            continue

        # Region tag
        combined_for_tag = f"{title} {abstract} {' '.join(countries)}".lower()
        region_tag = classify_region_tag(combined_for_tag, countries=countries)

        evidence_tier = STUDY_TYPE_TIER.get(study_type, 'rct')
        if 'phase 3' in phase.lower() or 'phase 2' in phase.lower():
            evidence_tier = 'rct'

        # Author = lead sponsor
        lead_sponsor = sponsor.get('leadSponsor', {}).get('name', '')
        authors = [lead_sponsor] if lead_sponsor else []

        url = f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else "https://clinicaltrials.gov"

        results.append(Result(
            source='clinicaltrials',
            title=f"[Trial] {title}",
            authors=authors,
            year=year,
            journal=f"ClinicalTrials.gov · {phase}" if phase else "ClinicalTrials.gov",
            abstract=abstract[:1200],
            url=url,
            region_tag=region_tag,
            evidence_tier=evidence_tier,
        ))

    return results


def _build_abstract(summary, detail, phase, study_type, countries):
    parts = []
    if phase:
        parts.append(f"Phase: {phase} | Type: {study_type}")
    if countries:
        parts.append(f"Locations: {', '.join(countries[:6])}")
    if summary:
        parts.append(summary[:600])
    if detail and len(detail) > 50:
        parts.append(detail[:400])
    return '\n'.join(parts)
