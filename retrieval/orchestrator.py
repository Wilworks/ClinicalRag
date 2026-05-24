"""
Retrieval orchestrator — parallel fan-out across all evidence sources.

Sources in priority order (also the order results are displayed):
  P0 sources (always included unless toggled off):
    pubmed          — handled separately by the existing RAG engine
    europepmc       — EvidAnce sources module
    semanticscholar — EvidAnce sources module
    openalex        — EvidAnce sources module

  P1 sources (opt-in via settings.active_sources):
    whoiris         — WHO IRIS OAI-PMH
    openfda         — OpenFDA drug labels
    clinicaltrials  — ClinicalTrials.gov v2
    doaj            — Directory of Open Access Journals

Scoring algorithm (Spec §3.3 weighted relevance):
  relevance = (
      0.40 × semantic_score    (all-MiniLM-L6-v2 cosine similarity)
    + 0.25 × evidence_tier_score
    + 0.20 × region_score
    + 0.15 × recency_score
  )
"""
import time
import concurrent.futures
from typing import Optional, Callable

from sources.schema import Result, TIER_SCORE, REGION_SCORE

# Source module registry
_SOURCE_MODULES = {}
try:
    from sources import europepmc
    _SOURCE_MODULES['europepmc'] = europepmc
except ImportError:
    pass
try:
    from sources import semanticscholar
    _SOURCE_MODULES['semanticscholar'] = semanticscholar
except ImportError:
    pass
try:
    from sources import openalex
    _SOURCE_MODULES['openalex'] = openalex
except ImportError:
    pass
try:
    from sources import whoiris
    _SOURCE_MODULES['whoiris'] = whoiris
except ImportError:
    pass
try:
    from sources import openfda
    _SOURCE_MODULES['openfda'] = openfda
except ImportError:
    pass
try:
    from sources import clinicaltrials
    _SOURCE_MODULES['clinicaltrials'] = clinicaltrials
except ImportError:
    pass
try:
    from sources import doaj
    _SOURCE_MODULES['doaj'] = doaj
except ImportError:
    pass

CURRENT_YEAR = 2026
MAX_RECENCY_YEARS = 20  # Cap for recency normalisation


def _recency_score(year: Optional[int]) -> float:
    """Linear decay from 1.0 (current year) → 0.0 (20+ years ago)."""
    if year is None:
        return 0.5   # unknown: neutral
    age = max(0, CURRENT_YEAR - year)
    return max(0.0, 1.0 - age / MAX_RECENCY_YEARS)


def _weighted_score(result: Result, semantic: float) -> float:
    """
    Compute weighted composite relevance score per Spec §3.3.
    semantic: cosine similarity from MiniLM (0.0–1.0)
    """
    tier_s   = TIER_SCORE.get(result.evidence_tier, 0.4)
    region_s = REGION_SCORE.get(result.region_tag, 0.4)
    recency_s = _recency_score(result.year)

    score = (
        0.40 * semantic
        + 0.25 * tier_s
        + 0.20 * region_s
        + 0.15 * recency_s
    )
    return min(1.0, max(0.0, score))


def _embed_query(embedder, query: str):
    """Encode query to a numpy vector."""
    try:
        return embedder.encode([query], convert_to_numpy=True)[0]
    except Exception:
        return None


def _cosine(a, b) -> float:
    """Cosine similarity between two numpy vectors."""
    try:
        import numpy as np
        norm_a = float(np.linalg.norm(a))
        norm_b = float(np.linalg.norm(b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
    except Exception:
        return 0.5


def _fetch_one(src_id: str, query: str, settings: dict,
               progress_cb: Optional[Callable] = None):
    """Fetch results from a single source module."""
    module = _SOURCE_MODULES.get(src_id)
    if module is None:
        return src_id, []
    try:
        t0 = time.time()
        results = module.fetch(query, settings=settings)
        elapsed = time.time() - t0
        if progress_cb:
            progress_cb(src_id, 'done', len(results))
        return src_id, results
    except Exception as e:
        print(f"[orchestrator] {src_id} error: {e}")
        if progress_cb:
            progress_cb(src_id, 'error', 0)
        return src_id, []


def fetch_all(
    query: str,
    settings: dict = None,
    embedder=None,
    max_total: int = 30,
    progress_cb: Optional[Callable] = None,
) -> list:
    """
    Fan out to all active (non-pubmed) sources in parallel.
    Score, deduplicate, and return a ranked list of Result objects.

    Args:
        query:       The search query (already region-augmented by views.py)
        settings:    User settings dict (active_sources, region, etc.)
        embedder:    sentence_transformers SentenceTransformer instance
        max_total:   Cap on total results returned
        progress_cb: Optional callback(src_id, status, count)

    Returns:
        List of Result objects sorted by composite relevance score (desc)
    """
    settings = settings or {}
    active_sources = settings.get('active_sources', list(_SOURCE_MODULES.keys()))

    # Only the non-pubmed sources handled here
    sources_to_fetch = [s for s in active_sources if s in _SOURCE_MODULES]

    if not sources_to_fetch:
        return []

    # Embed the query once for semantic scoring
    query_vec = _embed_query(embedder, query) if embedder else None

    # Parallel fetch with ThreadPoolExecutor
    all_results: list[Result] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(sources_to_fetch), 7)) as ex:
        futures = {
            ex.submit(_fetch_one, src_id, query, settings, progress_cb): src_id
            for src_id in sources_to_fetch
        }
        for future in concurrent.futures.as_completed(futures, timeout=25):
            try:
                src_id, results = future.result()
                all_results.extend(results)
            except Exception as e:
                print(f"[orchestrator] future error: {e}")

    # Embed abstracts and score
    if query_vec is not None and embedder and all_results:
        try:
            texts = [f"{r.title} {r.abstract[:400]}" for r in all_results]
            doc_vecs = embedder.encode(texts, convert_to_numpy=True, batch_size=32)
            for result, doc_vec in zip(all_results, doc_vecs):
                sem = _cosine(query_vec, doc_vec)
                result.relevance = _weighted_score(result, sem)
        except Exception as e:
            print(f"[orchestrator] embedding error: {e}")
            # Fallback: score without semantic
            for result in all_results:
                result.relevance = _weighted_score(result, 0.5)
    else:
        # No embedder: score on tier + region + recency alone
        for result in all_results:
            result.relevance = _weighted_score(result, 0.5)

    # Deduplicate by title similarity (simple lowercase match)
    seen_titles: set[str] = set()
    deduped: list[Result] = []
    for r in all_results:
        key = ''.join(r.title.lower().split())[:60]
        if key and key not in seen_titles:
            seen_titles.add(key)
            deduped.append(r)

    # Sort by composite relevance score descending
    deduped.sort(key=lambda r: r.relevance, reverse=True)

    return deduped[:max_total]


def assign_confidence(results: list) -> str:
    """
    Assign High/Moderate/Low confidence label based on top-N results.
    
    - High:     Top result relevance ≥ 0.72 OR ≥ 2 regional/rct/sr results
    - Moderate: Top result ≥ 0.50 OR ≥ 1 regional result  
    - Low:      Otherwise
    """
    if not results:
        return "Low"

    top = results[0].relevance
    high_quality = [
        r for r in results[:5]
        if r.evidence_tier in ('systematic_review', 'guideline', 'rct')
        or r.region_tag in ('regional', 'adjacent')
    ]

    if top >= 0.72 or len(high_quality) >= 2:
        return "High"
    if top >= 0.50 or len(high_quality) >= 1:
        return "Moderate"
    return "Low"
