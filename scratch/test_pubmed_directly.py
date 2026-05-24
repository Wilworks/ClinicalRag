import requests
from api.tools import search_pubmed, fetch_summaries

print("1. Searching with full natural language query:")
q1 = 'What is the recommended drug treatment for severe malaria in Ghana? AND ("West Africa" OR "Ghana" OR "resource-limited")'
res1, pmids1 = search_pubmed(q1)
print(f"Results length: {len(res1)}, PMIDs: {pmids1}")

print("\n2. Searching with simplified keyword query:")
q2 = 'severe malaria treatment Ghana'
res2, pmids2 = search_pubmed(q2)
print(f"Results length: {len(res2)}, PMIDs: {pmids2}")

print("\n3. Fetching summaries for simplified query:")
papers = fetch_summaries(pmids2)
print(f"Papers found: {len(papers)}")
for p in papers:
    print(f"- {p['title']} ({p['year']})")
