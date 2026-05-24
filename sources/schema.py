"""
Result schema shared by all evidence source modules.
Every source's fetch() must return a list of Result objects.
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
    evidence_tier: str = "other"  # 'rct' | 'systematic_review' | 'guideline' | 'other'

    def to_dict(self):
        return {
            "source": self.source,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "journal": self.journal,
            "abstract": self.abstract,
            "url": self.url,
            "relevance": round(self.relevance, 3),
            "region_tag": self.region_tag,
            "evidence_tier": self.evidence_tier,
        }


# ── Region tag helpers ─────────────────────────────────────────────────────

WEST_AFRICA_COUNTRIES = {
    "ghana", "nigeria", "senegal", "ivory coast", "côte d'ivoire", "mali",
    "burkina faso", "guinea", "benin", "togo", "liberia", "sierra leone",
    "gambia", "guinea-bissau", "cabo verde", "cape verde", "mauritania", "niger",
}

SUBSAHARAN_ADJACENT = {
    "ethiopia", "kenya", "tanzania", "uganda", "cameroon", "democratic republic of congo",
    "drc", "congo", "south africa", "zambia", "zimbabwe", "mozambique", "malawi",
    "rwanda", "somalia", "sudan", "south sudan", "chad", "angola", "namibia",
    "africa", "african", "sub-saharan", "subsaharan",
}

EVIDENCE_TIER_KEYWORDS = {
    "systematic_review": ["systematic review", "meta-analysis", "meta analysis", "cochrane"],
    "guideline": ["guideline", "recommendation", "who", "standard treatment", "protocol", "clinical practice"],
    "rct": ["randomized", "randomised", "clinical trial", "rct", "placebo-controlled", "double-blind"],
}


def classify_region_tag(text: str) -> str:
    """Classify region tag from title/abstract/journal text."""
    t = text.lower()
    if any(c in t for c in WEST_AFRICA_COUNTRIES):
        return "regional"
    if any(c in t for c in SUBSAHARAN_ADJACENT):
        return "adjacent"
    return "extrapolated"


def classify_evidence_tier(text: str) -> str:
    """Classify evidence tier from title/abstract."""
    t = text.lower()
    for tier, keywords in EVIDENCE_TIER_KEYWORDS.items():
        if any(k in t for k in keywords):
            return tier
    return "other"
