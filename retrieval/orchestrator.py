"""
Retrieval orchestrator.
Fans out to all active sources in parallel using ThreadPoolExecutor.
Merges, deduplicates, and scores results.
"""
import time
import hashlib
import concurrent.futures
from datetime import datetime

from sources import europepmc, semanticscholar, openalex
from sources.schema import Result


# ── Source registry ─────────────────────────────────────────────────────────
# Maps source name → module. Add P1+ sources here as they are implemented.

SOURCE_MODULES = {
    "europepmc": europepmc,
    "semanticscholar": semanticscholar,
    "openalex": openalex,
}

DEFAULT_ACTIVE_SOURCES = ["europepmc", "semanticscholar", "openalex"]

# ── Evidence tier weights ────────────────────────────────────────────────────

TIER_WEIGHTS = {
    "systematic_review": 1.0,
    "guideline": 1.0,
    "rct": 0.8,
    "observational": 0.5,
    "other": 0.2,
}

REGION_WEIGHTS = {
    "regional": 1.0,
    "adjacent": 0.6,
    "extrapolated": 0.2,
}

CURRENT_YEAR = datetime.now().year


def _recency_score(year) -> float:
    """Linear decay: current year = 1.0, >10 years old = 0.3"""
    if not year:
        return 0.5
    age = CURRENT_YEAR - int(year)
    if age <= 0:
        return 1.0
    if age >= 10:
        return 0.3
    return round(1.0 - (age * 0.07), 2)


def _semantic_score(query: str, result: Result, embedder=None) -> float:
    """
    Compute semantic similarity between query and result title+abstract.
    Uses the shared sentence-transformers embedder if available.
    Falls back to simple keyword overlap if embedder not provided.
    """
    if embedder is not None:
        import numpy as np
        try:
            import faiss
            combined = f"{result.title}. {result.abstract[:500]}"
            vecs = embedder.encode([query, combined], convert_to_numpy=True)
            faiss.normalize_L2(vecs)
            sim = float(np.dot(vecs[0], vecs[1]))
            return max(0.0, min(1.0, (sim + 1) / 2))  # map [-1,1] → [0,1]
        except Exception:
            pass

    # Fallback: keyword overlap ratio
    query_words = set(query.lower().split())
    text_words = set((result.title + " " + result.abstract[:300]).lower().split())
    if not query_words:
        return 0.5
    overlap = len(query_words & text_words) / len(query_words)
    return min(1.0, overlap)


def score_result(result: Result, query: str, embedder=None) -> float:
    """
    Weighted relevance score per spec §4.2:
      0.40 semantic similarity
      0.25 evidence tier
      0.15 recency
      0.20 region tag
    """
    sem = _semantic_score(query, result, embedder)
    tier = TIER_WEIGHTS.get(result.evidence_tier, 0.2)
    rec = _recency_score(result.year)
    reg = REGION_WEIGHTS.get(result.region_tag, 0.2)

    score = (sem * 0.40) + (tier * 0.25) + (rec * 0.15) + (reg * 0.20)
    return round(min(1.0, score), 3)


def assign_confidence(results: list) -> str:
    """
    Per spec §4.3:
    High:     3+ results with relevance >= 0.75 AND at least one Tier 1 source
    Moderate: At least 1 result >= 0.60 OR multiple lower-tier results
    Low:      No results above 0.50 or all Tier 3/4
    """
    if not results:
        return "Low"

    high_relevance = [r for r in results if r.relevance >= 0.75]
    tier1 = [r for r in results if r.evidence_tier in ("systematic_review", "guideline", "rct")]

    if len(high_relevance) >= 3 and tier1:
        return "High"

    mid_relevance = [r for r in results if r.relevance >= 0.60]
    if mid_relevance or len(results) >= 3:
        return "Moderate"

    return "Low"


def _dedup(results: list) -> list:
    """Deduplicate by URL and title fingerprint."""
    seen_urls = set()
    seen_titles = set()
    unique = []
    for r in results:
        title_key = hashlib.md5(r.title.lower().strip().encode()).hexdigest()
        url_key = r.url.strip().rstrip("/")
        if url_key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        unique.append(r)
    return unique


def fetch_all(query: str, settings: dict = None, embedder=None, progress_cb=None) -> list:
    """
    Fan out to all active sources in parallel.
    Returns scored, deduplicated, sorted list of Result objects.

    progress_cb(source_name, status, count) called per source completion.
    """
    settings = settings or {}
    active = settings.get("active_sources", DEFAULT_ACTIVE_SOURCES)

    # Only call sources that are (a) active and (b) implemented
    to_fetch = {k: v for k, v in SOURCE_MODULES.items() if k in active}

    all_results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        future_map = {
            executor.submit(mod.fetch, query, settings): name
            for name, mod in to_fetch.items()
        }

        for future in concurrent.futures.as_completed(future_map):
            source_name = future_map[future]
            try:
                results = future.result(timeout=20)
                if progress_cb:
                    progress_cb(source_name, "done", len(results))
                all_results.extend(results)
            except Exception as e:
                print(f"[Orchestrator] {source_name} failed: {e}")
                if progress_cb:
                    progress_cb(source_name, "error", 0)

    # Score all results
    for r in all_results:
        r.relevance = score_result(r, query, embedder)

    # Dedup and sort by relevance
    unique = _dedup(all_results)
    unique.sort(key=lambda r: r.relevance, reverse=True)

    return unique
