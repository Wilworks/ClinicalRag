# Standalone utility functions the RAG engine calls.
# Each function does one thing only — easy to test individually,
# easy to add new ones later without touching anything else.

import requests
import numpy as np
from .prompts import WEST_AFRICA_TERMS


# ── PubMed search ─────────────────────────────────────────────
# Calls the free PubMed E-utilities API — no key needed.
# Returns the raw abstract text and the list of PMIDs found.
# max_results controls how many abstracts we fetch per question.

import time

def robust_get(url, params=None, timeout=20, max_retries=3):
    for i in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 200:
                return resp
        except (requests.exceptions.RequestException, KeyError):
            pass
        if i < max_retries - 1:
            time.sleep(1)
    return None

def search_pubmed(query, max_results=8):
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    #get the IDs of matching papers
    search_resp = robust_get(
        f"{base}esearch.fcgi",
        params={
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
            "sort": "relevance",
        },
        timeout=20,
    )
    if not search_resp:
        return "", []
        
    try:
        pmids = search_resp.json()["esearchresult"]["idlist"]
    except Exception:
        return "", []

    if not pmids:
        return "", []

    #fetch the actual abstracts for those IDs
    fetch_resp = robust_get(
        f"{base}efetch.fcgi",
        params={
            "db": "pubmed",
            "id": ",".join(pmids),
            "rettype": "abstract",
            "retmode": "text",
        },
        timeout=20,
    )
    if not fetch_resp:
        return "", []

    return fetch_resp.text, pmids


# ── West Africa bias ──────────────────────────────────────────
# When the user toggles "West Africa filter" ON in the UI,
# this function appends regional terms to their query before
# it hits PubMed — biasing results toward relevant populations.
# Example: "hydroxyurea dosing" becomes
# "hydroxyurea dosing AND (West Africa OR Ghana OR resource-limited)"

def bias_west_africa(query):
    # Build an OR clause from our terms list in prompts.py
    region_clause = " OR ".join(f'"{t}"' for t in WEST_AFRICA_TERMS)
    return f"{query} AND ({region_clause})"


# ── Chunk text ────────────────────────────────────────────────
# PubMed returns one big wall of text for all abstracts combined.
# We split it into overlapping chunks so no sentence gets cut off
# at a boundary and loses its meaning.
# chunk_size = max characters per chunk
# overlap = how many characters the next chunk walks back
#           so context carries over between chunks

def chunk_text(text, chunk_size=1500, overlap=200):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap   # walk back by overlap before next chunk
    return [c for c in chunks if c.strip()]  # drop empty chunks


# ── Confidence score ──────────────────────────────────────────
# FAISS returns raw distance scores for each retrieved chunk.
# This converts them into a human-readable confidence percentage
# shown in the UI confidence bar.
# We take the average of the top chunk scores and normalise to 0-100.
# Higher score = retrieved chunks were more similar to the question.

def score_confidence(faiss_distances):
    if faiss_distances is None or len(faiss_distances) == 0:
        return 0
    # FAISS inner product scores — higher is better
    # Clip to 0-1 range in case of floating point overshoot
    scores = np.clip(faiss_distances[0], 0, 1)
    avg = float(np.mean(scores))
    return round(avg * 100, 1)


# ── Format sources ────────────────────────────────────────────
# Converts a list of raw PMIDs into full PubMed URLs
# that the frontend renders as clickable source chips.

def format_sources(pmids):
    return [
        f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        for pmid in pmids[:4]   # cap at 4 sources in the UI
    ]


# ── Fetch Paper Summaries ──────────────────────────────────────
# Calls PubMed's esummary.fcgi API to fetch paper titles, journals,
# first authors, and publication dates for a list of PMIDs.

def fetch_summaries(pmids):
    if not pmids:
        return []

    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    try:
        resp = robust_get(
            f"{base}esummary.fcgi",
            params={
                "db": "pubmed",
                "id": ",".join(str(p) for p in pmids[:4]),  # Cap at top 4 papers
                "retmode": "json",
            },
            timeout=20,
        )
        if not resp or resp.status_code != 200:
            return []

        result = resp.json().get("result", {})
        papers = []
        for pmid in pmids[:4]:
            pmid_str = str(pmid)
            if pmid_str in result:
                meta = result[pmid_str]
                title = meta.get("title", "No title available").strip()
                # Clean trailing period from title
                if title.endswith("."):
                    title = title[:-1]
                
                authors_list = meta.get("authors", [])
                if authors_list:
                    first_author = authors_list[0].get("name", "")
                    if len(authors_list) > 1:
                        authors = f"{first_author} et al."
                    else:
                        authors = first_author
                else:
                    authors = "Unknown author"

                journal = meta.get("source", "PubMed")
                pubdate = meta.get("pubdate", "")
                year = pubdate.split(" ")[0] if pubdate else "Unknown Year"

                papers.append({
                    "uid": pmid_str,
                    "title": title,
                    "authors": authors,
                    "journal": journal,
                    "year": year,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid_str}/"
                })
        return papers
    except Exception:
        return []



# ── Wikipedia Search and Summaries ───────────────────────────
# Searches Wikipedia using the action=query API with prop=extracts
# so we get article text in a single call (not two).
# Returns (abstracts_text, papers_list) matching the PubMed format.

def search_wikipedia(query):
    import re
    import urllib.parse

    base = "https://en.wikipedia.org/w/api.php"

    # Step 1 — search for matching article titles
    search_resp = robust_get(
        base,
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "utf8": 1,
            "format": "json",
            "srlimit": 3,
            "srnamespace": 0,
        },
        timeout=15,
    )
    if not search_resp:
        return "", []

    try:
        search_results = search_resp.json().get("query", {}).get("search", [])
    except Exception:
        return "", []

    if not search_results:
        return "", []

    # Collect top page IDs and titles
    page_ids = [str(item["pageid"]) for item in search_results if "pageid" in item]
    if not page_ids:
        return "", []

    # Step 2 — fetch extracts for all matching pages in ONE call
    extract_resp = robust_get(
        base,
        params={
            "action": "query",
            "pageids": "|".join(page_ids),
            "prop": "extracts|info",
            "exintro": 1,         # intro section only (concise)
            "explaintext": 1,     # plain text, no HTML
            "inprop": "url",
            "format": "json",
        },
        timeout=15,
    )
    if not extract_resp:
        return "", []

    try:
        pages = extract_resp.json().get("query", {}).get("pages", {})
    except Exception:
        return "", []

    abstracts = []
    papers = []

    for pid, data in pages.items():
        title = data.get("title", "")
        extract = data.get("extract", "").strip()
        page_url = data.get("fullurl", f"https://en.wikipedia.org/?curid={pid}")

        if not extract or len(extract) < 100:
            continue

        # Trim very long extracts to ~1200 chars to stay within token budget
        if len(extract) > 1200:
            extract = extract[:1200].rsplit(" ", 1)[0] + "…"

        abstracts.append(f"Source: Wikipedia – '{title}'.\n{extract}")
        papers.append({
            "uid": f"wiki_{pid}",
            "title": title,
            "authors": "Wikipedia Contributors",
            "journal": "Wikipedia",
            "year": "Last Updated",
            "url": page_url,
        })

    combined = "\n\n".join(abstracts)
    return combined, papers
