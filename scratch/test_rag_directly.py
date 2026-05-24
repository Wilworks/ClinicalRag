import os
import django
import json

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from api.rag_engine import rag_engine

print("=========================================")
print("1. RUNNING DIABETES/SICKLE CELL QUERY")
print("=========================================")
q = "What are the potential long-term effects of SGLT2 inhibitors on kidney function and intraglomerular pressure in patients with sickle cell disease?"
res = rag_engine.run(q, west_africa_filter=False)
print("Answer:\n", res["answer"])
print("Papers retrieved:")
for p in res.get("papers", []):
    print(f"- {p['title']} ({p['year']})")

print("\n=========================================")
print("2. RUNNING MALARIA QUERY WITH GHANA FILTER")
print("=========================================")
q2 = "What is the recommended drug treatment for severe malaria in Ghana?"
res2 = rag_engine.run(q2, west_africa_filter=True)
print("Answer:\n", res2["answer"][:500] + "...")
print("Papers retrieved:")
for p in res2.get("papers", []):
    print(f"- {p['title']} ({p['year']})")
