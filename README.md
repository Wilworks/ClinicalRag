
```markdown
# Evidance
### Evidence · Guidance

> The name is deliberate — Evidence + Guidance,  
> built for West African clinical healthcare contexts.

---

## What this is

Evidance is a PubMed-grounded clinical evidence API and web application
built for healthcare contexts where access to synthesised, cited clinical
information matters most — particularly across West Africa.

Ask a clinical question. Evidance searches real PubMed literature in
real time, retrieves the most relevant evidence using vector similarity
search, and returns a grounded answer with confidence scoring, cited
sources, and suggested follow-up questions — all within seconds.

It is not a chatbot. It does not hallucinate references.
Every claim it makes is traceable to a real PubMed abstract.

---

## The problem it solves

Clinical decision-making in resource-limited settings frequently happens
without access to synthesised evidence. Guidelines written for
high-income contexts do not always translate. West African disease
burden — sickle cell disease, malaria, eclampsia, tuberculosis — is
underrepresented in the tools clinicians actually use.

Evidance was built to close that gap, even partially.
A clinician in Accra or Lagos should be able to ask a question in plain
language and get a cited, grounded answer in under 20 seconds —
for free, with no account required.

---

## How it works

```
User question
    │
    ▼
West Africa filter (optional)
Appends regional bias terms to the PubMed query
    │
    ▼
PubMed E-utilities (free, no API key)
Fetches up to 8 relevant abstracts via esearch + efetch
    │
    ▼
Chunking
Abstract text split into overlapping 1500-character chunks
200-character overlap preserves sentence boundary context
    │
    ▼
Embedding
all-MiniLM-L6-v2 (80MB, runs on CPU, no GPU required)
Converts chunks into 384-dimension dense vectors
    │
    ▼
FAISS IndexFlatIP
Vectors normalised → inner product = cosine similarity
Fresh index built per request — no stale context between questions
    │
    ▼
Retrieval
Top-3 chunks by cosine similarity returned
Confidence score derived from average similarity distance
    │
    ▼
Groq LLM (llama3-8b-8192, free tier)
Context + question sent with strict grounding instructions
Answer generated at temperature 0.2 for factual consistency
    │
    ▼
Follow-up generation
Second Groq call generates 3 suggested follow-up questions
    │
    ▼
Response
answer · confidence % · PubMed source URLs · follow-ups
```

The entire pipeline runs on free infrastructure.
No GPU. No paid APIs beyond the free Groq tier.
No database. No user accounts.

---

## Stack

| Layer | Technology | Why |
|---|---|---|
| Backend framework | Django 4.2 + DRF | Mature, well-documented, free deployment on HF Spaces |
| Vector search | FAISS (faiss-cpu) | Reliable, no external service, no threading issues |
| Embeddings | sentence-transformers (MiniLM-L6-v2) | 80MB, fast on CPU, no API key |
| LLM | Groq (llama3-8b-8192) | Free tier, fast inference, function calling support |
| Literature | PubMed E-utilities | Free, no key, 30M+ papers |
| PDF generation | ReportLab | Pure Python, no binaries |
| Frontend | Vanilla HTML/CSS/JS | No build step, no framework overhead, ships as a Django template |
| Deployment | Hugging Face Spaces (Docker) | Free, persistent, public URL |

---

## Project structure

```
evidance/
├── manage.py
├── config/
│   ├── settings.py          # environment config, installed apps
│   ├── urls.py              # root router — / and /api/
│   └── wsgi.py
├── api/
│   ├── prompts.py           # all prompt templates — edit here to improve answers
│   ├── tools.py             # PubMed fetch, chunking, confidence scoring, bias
│   ├── rag_engine.py        # core pipeline — embed, index, retrieve, generate
│   ├── views.py             # REST endpoint, SSE stream endpoint, PDF endpoint, health check
│   ├── serializers.py       # request validation
│   ├── pdf_export.py        # ReportLab PDF builder
│   └── urls.py              # /api/ask/ · /api/ask/stream/ · /api/pdf/ · /api/health/
├── templates/
│   └── index.html           # full frontend — dark UI, served by Django
├── requirements.txt
├── Dockerfile               # HF Spaces deployment
├── .env                     # never committed
└── .gitignore
```

---

## API reference

### POST `/api/ask/`
Standard REST endpoint. Waits for the full pipeline then returns JSON.

**Request**
```json
{
  "question": "What is the recommended hydroxyurea dose for adults with HbSS sickle cell disease?",
  "west_africa_filter": true
}
```

**Response**
```json
{
  "answer": "The recommended starting dose of hydroxyurea...",
  "sources": [
    "https://pubmed.ncbi.nlm.nih.gov/34821612/",
    "https://pubmed.ncbi.nlm.nih.gov/31776128/"
  ],
  "confidence": 87.0,
  "followups": [
    "How do you monitor for hydroxyurea toxicity in sickle cell patients?",
    "Is hydroxyurea safe during pregnancy in women with HbSS?",
    "What are alternatives if hydroxyurea is unavailable in resource-limited settings?"
  ]
}
```

---

### POST `/api/ask/stream/`
Server-Sent Events endpoint. Emits progress events as each pipeline
stage completes. Powers the live progress UI.

**Request body** — same as `/api/ask/`

**Events emitted**
```
searching   → PubMed query sent
found       → abstracts retrieved, count included
embedding   → chunks embedded, count included  
retrieving  → top chunks retrieved, confidence included
generating  → LLM call in progress
answering   → follow-up generation in progress
done        → full result payload, same shape as /api/ask/
error       → pipeline failed, message included
```

---

### POST `/api/pdf/`
Generates a formatted clinical PDF report and streams it as a download.

**Request**
```json
{
  "question":   "...",
  "answer":     "...",
  "sources":    ["https://pubmed.ncbi.nlm.nih.gov/..."],
  "confidence": 87.0,
  "followups":  ["...", "...", "..."],
  "name":       "Dr. Kwame Mensah"
}
```

**Response** — `application/pdf` binary stream

---

### GET `/api/health/`
Returns engine status. Used by Hugging Face Spaces to verify the
application is alive.

**Response**
```json
{
  "status":   "ok",
  "engine":   "loaded",
  "embedder": "all-MiniLM-L6-v2"
}
```

---

## Running locally

```bash
git clone https://github.com/Wilworks/evidance
cd evidance

python -m venv venv
source venv/bin/activate

pip install -r requirements.txt

# create .env at the root
echo "GROQ_API_KEY=your_key_here" > .env
echo "DEBUG=True" >> .env
echo "SECRET_KEY=any-long-random-string" >> .env
echo "ALLOWED_HOSTS=localhost,127.0.0.1" >> .env

python manage.py migrate
python manage.py runserver
```

Visit `http://localhost:8000`

Get a free Groq API key at `console.groq.com` — no credit card required.

---

## Deploying to Hugging Face Spaces

```bash
# create a new Docker Space at huggingface.co/spaces
git remote add hf https://huggingface.co/spaces/Wilworks/evidance
git push hf main

# add GROQ_API_KEY under Space Settings → Repository Secrets
# add SECRET_KEY under Space Settings → Repository Secrets
```

Live at: `https://wilworks-evidance.hf.space`

---

## Prompt engineering

All prompt templates live in `api/prompts.py`.
This is the single file to edit when improving answer quality.

**System prompt** controls the LLM's personality and rules —
grounding strictness, disclaimer requirement, West Africa awareness.

**Answer prompt** structures how context and question are presented
to the LLM per request.

**Follow-up prompt** generates the three suggested questions shown
below each answer.

**West Africa bias terms** are appended to PubMed queries when the
West Africa filter is enabled, biasing retrieval toward relevant
population evidence.

---

## What makes this different

**It is grounded.** Every answer cites real PubMed abstracts.
The LLM is instructed to use only the retrieved context — not its
training knowledge.

**It is West Africa aware.** The disease focus filter and query
bias terms push retrieval toward evidence relevant to the populations
that need it most. Sickle cell disease, malaria, eclampsia,
tuberculosis — not as edge cases, but as primary use cases.

**It flags population gaps.** The system prompt instructs the model
to note when evidence comes from non-African populations and may not
generalise directly to West African clinical contexts.

**It runs entirely on free infrastructure.** The full pipeline —
literature retrieval, embedding, vector search, LLM inference —
costs nothing to run. Designed for contexts where infrastructure
budgets are limited.

---

## Roadmap

The following tools are planned for future versions:

```
check_who_eml()           WHO Essential Medicines List lookup
check_openfda()           FDA adverse event data per drug
fetch_cochrane()          Cochrane systematic review retrieval
check_ghana_std()         Ghana Standard Treatment Guidelines
fetch_who_guidelines()    WHO clinical guideline PDFs
detect_drug_names()       NLP extraction of drug names from questions
```

The evaluation harness (benchmarking LLM performance on West African
clinical questions) is maintained as a separate project and feeds
back into prompt improvement for this system.

---

## Built by

**Wilfred Asumboya**  
AI Engineer · University of Ghana · Accra, Ghana · 2026  

`wilfredasumboya@gmail.com`  
`github.com/Wilworks`  
`asumboya-folio.lovable.app`

---

*Evidance is a research tool. It does not constitute clinical advice.
Always consult a qualified healthcare professional before making
clinical decisions.*
```

---

That README tells three stories simultaneously:

For a **hiring manager** skimming it — they see a real problem, a working system, thoughtful engineering decisions, and a West Africa angle nobody else has.

For an **engineer reviewing the repo** — they get a full architecture diagram, API reference, and enough detail to run it locally in under five minutes.

For **you six months from now** — it's a complete record of every decision made and why, written while the context is fresh.