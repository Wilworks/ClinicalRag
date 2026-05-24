"""
Result schema shared by all evidence source modules.
Every source's fetch() must return a list of Result objects.

Region classification (Spec §3.4):
  - 'regional'     = study conducted in / explicitly covers West Africa
  - 'adjacent'     = sub-Saharan or broader African study (may transfer)
  - 'extrapolated' = no African context, requires careful extrapolation

Evidence tiers (Spec §3.5):
  - 'systematic_review' — highest: meta-analyses, Cochrane reviews
  - 'guideline'         — WHO, national STG, FDA label, clinical protocols
  - 'rct'               — randomised controlled trials, phase 2/3 trials
  - 'observational'     — cohort, case-control, cross-sectional
  - 'other'             — case report, commentary, editorial, opinion
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Result:
    source: str                   # 'pubmed' | 'europepmc' | 'semanticscholar' | ...
    title: str
    authors: list                 # list[str]
    year: Optional[int]
    journal: Optional[str]
    abstract: str
    url: str
    relevance: float = 0.0        # 0.0–1.0, filled by retrieval scorer
    region_tag: str = "extrapolated"   # 'regional' | 'adjacent' | 'extrapolated'
    evidence_tier: str = "other"  # 'systematic_review' | 'guideline' | 'rct' | 'observational' | 'other'

    def to_dict(self):
        return {
            "source":        self.source,
            "title":         self.title,
            "authors":       self.authors,
            "year":          self.year,
            "journal":       self.journal,
            "abstract":      self.abstract,
            "url":           self.url,
            "relevance":     round(self.relevance, 3),
            "region_tag":    self.region_tag,
            "evidence_tier": self.evidence_tier,
        }


# ── Region classifier data ──────────────────────────────────────────────────

# Tier-1: True West African countries → 'regional'
WEST_AFRICA_COUNTRIES = frozenset({
    # ECOWAS core
    "ghana", "nigeria", "senegal", "ivory coast", "côte d'ivoire", "cote d'ivoire",
    "mali", "burkina faso", "guinea", "guinea conakry", "benin", "togo",
    "liberia", "sierra leone", "gambia", "the gambia", "guinea-bissau",
    "cabo verde", "cape verde", "mauritania", "niger",
    # Common informal / journal usage
    "accra", "lagos", "abuja", "dakar", "ouagadougou", "conakry", "freetown",
    "monrovia", "banjul", "cotonou", "lomé", "lome", "niamey", "bamako",
    "abidjan", "praia",
    # Regional labels
    "west africa", "west african", "ecowas",
})

# Tier-2: Broader sub-Saharan / pan-African → 'adjacent'
SUBSAHARAN_ADJACENT = frozenset({
    # East Africa
    "ethiopia", "kenya", "tanzania", "uganda", "rwanda", "burundi",
    "nairobi", "kampala", "dar es salaam", "addis ababa", "kigali",
    # Southern Africa
    "south africa", "zambia", "zimbabwe", "mozambique", "malawi",
    "botswana", "namibia", "angola", "eswatini", "swaziland", "lesotho",
    "johannesburg", "cape town", "pretoria", "lusaka", "harare", "lilongwe",
    # Central Africa
    "democratic republic of congo", "drc", "dr congo", "congo", "cameroon",
    "central african republic", "gabon", "equatorial guinea", "sao tome",
    "kinshasa", "yaoundé", "yaounde",
    # Horn of Africa / North Africa (partial SSA context)
    "somalia", "djibouti", "eritrea", "sudan", "south sudan", "chad",
    # General African terms
    "africa", "african", "sub-saharan", "subsaharan", "sub saharan",
    "low-income country", "low income country", "lmic", "low-and-middle-income",
    "resource-limited", "resource limited", "resource-constrained",
    "developing country", "developing world", "global south",
    # Disease-specific African context terms
    "sickle cell africa", "malaria endemic", "tropical africa",
    "hiv africa", "tb africa",
})

# Tier-3: High-confidence regional disease or organism terms
# These alone strongly suggest regional applicability even without country mention
REGIONAL_DISEASE_MARKERS = frozenset({
    "plasmodium falciparum",    # predominant malaria species in West Africa
    "hbss",                     # HbSS sickle cell (prevalent in West Africa)
    "sickle cell trait",
    "g6pd deficiency",          # very high prevalence in West Africa
    "burkitt lymphoma",         # endemic in sub-Saharan Africa
    "lassa fever",              # West African haemorrhagic fever
    "ebola west africa",
    "yellow fever west africa",
    "cholera africa",
    "meningococcal africa",     # meningitis belt
    "sleeping sickness",        # trypanosomiasis, West/Central Africa
    "schistosomiasis africa",
    "onchocerciasis",           # river blindness, West Africa
    "loiasis",
    "lymphatic filariasis west",
})

EVIDENCE_TIER_KEYWORDS = {
    "systematic_review": [
        "systematic review", "meta-analysis", "meta analysis", "metaanalysis",
        "cochrane review", "cochrane database", "pooled analysis", "network meta",
    ],
    "guideline": [
        "guideline", "clinical guideline", "who recommendation",
        "standard treatment", "treatment guideline", "treatment protocol",
        "standard of care", "clinical practice guideline", "who position",
        "essential medicines", "formulary", "fda label", "package insert",
        "prescribing information",
    ],
    "rct": [
        "randomized controlled trial", "randomised controlled trial",
        "rct", "randomized trial", "randomised trial",
        "placebo-controlled", "double-blind", "single-blind",
        "clinical trial", "phase 3", "phase iii", "phase 2", "phase ii",
        "randomly assigned", "random assignment",
    ],
    "observational": [
        "cohort study", "cohort analysis", "case-control", "case control",
        "cross-sectional", "cross sectional", "prospective study",
        "retrospective study", "observational study", "registry study",
        "surveillance", "epidemiological study",
    ],
}


def classify_region_tag(text: str, countries: list = None) -> str:
    """
    Classify region tag from title/abstract/journal/country list.
    
    Priority:
      1. Country list (authoritative, from ClinicalTrials location data)
      2. West African country/city names in text
      3. Regional disease markers (biological proxy for West African context)
      4. Sub-Saharan / broader African terms
      5. LMIC / resource-limited proxy terms
    """
    t = text.lower()

    # Priority 1: authoritative country list
    if countries:
        country_str = ' '.join(c.lower() for c in countries)
        if any(c in country_str for c in WEST_AFRICA_COUNTRIES):
            return "regional"
        if any(c in country_str for c in SUBSAHARAN_ADJACENT):
            return "adjacent"

    # Priority 2: West African country/city names in text
    if any(c in t for c in WEST_AFRICA_COUNTRIES):
        return "regional"

    # Priority 3: Regional disease markers
    if any(marker in t for marker in REGIONAL_DISEASE_MARKERS):
        return "regional"

    # Priority 4: Broader African / SSA terms
    if any(c in t for c in SUBSAHARAN_ADJACENT):
        return "adjacent"

    return "extrapolated"


def classify_evidence_tier(text: str) -> str:
    """
    Classify evidence tier from title/abstract.
    Checks in descending quality order.
    """
    t = text.lower()
    for tier in ("systematic_review", "guideline", "rct", "observational"):
        if any(k in t for k in EVIDENCE_TIER_KEYWORDS[tier]):
            return tier
    return "other"


# ── Tier scores for weighted ranking (used by orchestrator) ────────────────
TIER_SCORE = {
    "systematic_review": 1.0,
    "guideline":         0.9,
    "rct":               0.8,
    "observational":     0.6,
    "other":             0.4,
}

REGION_SCORE = {
    "regional":      1.0,
    "adjacent":      0.7,
    "extrapolated":  0.4,
}
