"""
Retrieval app views.
POST /api/retrieval/query/  — submit a query, returns SSE stream with new step schema
POST /api/retrieval/rerun/  — rerun last query excluding a specified source
"""
import json
import concurrent.futures
from django.http import StreamingHttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from api.rag_engine import rag_engine
from api.tools import (
    search_pubmed, bias_west_africa, chunk_text,
    score_confidence, format_sources, fetch_summaries,
)
from api.prompts import SYSTEM_PROMPT, ANSWER_PROMPT, SOURCES_PROMPT, FOLLOWUP_PROMPT
from retrieval.orchestrator import fetch_all, assign_confidence
from settings_profile.models import EvidanceSettings
from canvas.models import CanvasSession


def _get_settings(request):
    """Get active settings for the session, or return defaults."""
    if not request.session.session_key:
        request.session.create()
    try:
        obj = EvidanceSettings.objects.get(session_key=request.session.session_key)
        return obj.to_dict()
    except EvidanceSettings.DoesNotExist:
        return {"active_sources": ["pubmed", "europepmc", "semanticscholar", "openalex"]}


def _get_canvas(request):
    """Get canvas state for the session."""
    if not request.session.session_key:
        return {}
    try:
        canvas = CanvasSession.objects.filter(
            session_key=request.session.session_key
        ).order_by("-updated_at").first()
        return canvas.to_dict() if canvas else {}
    except Exception:
        return {}


def _sse_event(step, payload):
    data = json.dumps({"step": step, **payload})
    return f"data: {data}\n\n"


class RetrievalQueryView(APIView):
    """
    POST /api/retrieval/query/
    Accepts: { question, history, canvas_context }
    Returns SSE stream with spec-compliant step events.
    """

    def post(self, request):
        question = request.data.get("question", "").strip()
        history = request.data.get("history", [])
        exclude_source = request.data.get("exclude_source", None)

        if not question:
            return Response({"error": "question is required"}, status=400)

        settings = _get_settings(request)
        canvas = request.data.get("canvas_context") or _get_canvas(request)

        # Exclude a source for re-run without modifying settings
        if exclude_source:
            active = [s for s in settings.get("active_sources", []) if s != exclude_source]
            settings = {**settings, "active_sources": active}

        response = StreamingHttpResponse(
            self._stream(question, history, settings, canvas),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    def _stream(self, question, history, settings, canvas):
        try:
            # ── Intent classification ──────────────────────────────────
            q_lower = question.strip().lower().rstrip("!?. ")
            intent = rag_engine._classify_intent(question, history)

            # ── CONVERSE branch — natural conversation, own knowledge ──
            if intent == "CONVERSE":
                yield _sse_event("synthesizing", {
                    "source": None, "query": None, "count": None,
                    "note": "using_knowledge"
                })
                answer = rag_engine._generate_answer_direct(question, history)
                yield _sse_event("done", {
                    "answer": answer,
                    "sources": [],
                    "confidence": "High",
                    "papers_matched": 0,
                    "evidence_year": None,
                    "region_summary": "N/A",
                    "canvas_update": {},
                    "followup_chips": ["How can I help you further?"],
                    "disambiguation": None,
                    "using_own_knowledge": True,
                })
                return

            # ── Rewrite query ──────────────────────────────────────────
            evidence_seeking = (intent == "SOURCE_REQUEST")
            if evidence_seeking and history:
                query_question = rag_engine._extract_topic_from_history(history) or rag_engine._rewrite_query(question, history)
            else:
                query_question = rag_engine._rewrite_query(question, history)

            # Inject region into query from settings
            region = settings.get("region", "west_africa")
            region_label = {
                "west_africa": "West Africa",
                "subsaharan": "sub-Saharan Africa",
                "pan_africa": "Africa",
                "global": "",
            }.get(region, "West Africa")
            if region_label:
                augmented_query = f"{query_question} {region_label}"
            else:
                augmented_query = query_question

            # ── Fan out to sources ────────────────────────────────────
            active_sources = settings.get("active_sources", ["pubmed", "europepmc", "semanticscholar", "openalex"])

            # Emit searching events per source
            for src in active_sources:
                if src != "pubmed":  # pubmed handled separately below
                    yield _sse_event("searching", {
                        "source": src, "query": augmented_query, "count": None
                    })

            # Always run PubMed via existing engine
            pubmed_abstracts, pubmed_pmids = "", []
            pubmed_papers = []
            if "pubmed" in active_sources:
                yield _sse_event("searching", {
                    "source": "pubmed", "query": augmented_query, "count": None
                })
                pubmed_abstracts, pubmed_pmids = search_pubmed(augmented_query)
                if pubmed_abstracts:
                    pubmed_papers = fetch_summaries(pubmed_pmids)
                yield _sse_event("retrieving", {
                    "source": "pubmed", "query": None, "count": len(pubmed_papers)
                })

            # Run new orchestrator sources in parallel
            new_sources_settings = {**settings, "active_sources": [s for s in active_sources if s != "pubmed"]}
            orchestrator_results = []

            if new_sources_settings["active_sources"]:
                source_counts = {}

                def progress_cb(src_name, status_val, count):
                    source_counts[src_name] = count

                orchestrator_results = fetch_all(
                    augmented_query,
                    settings=new_sources_settings,
                    embedder=rag_engine.embedder,
                    progress_cb=progress_cb,
                )

                for src_name, count in source_counts.items():
                    yield _sse_event("retrieving", {
                        "source": src_name, "query": None, "count": count
                    })

            # ── Merge results ─────────────────────────────────────────
            all_papers = pubmed_papers[:]
            all_abstracts = pubmed_abstracts or ""

            for r in orchestrator_results[:10]:
                all_papers.append({
                    "title": r.title,
                    "authors": ", ".join(r.authors),
                    "year": r.year,
                    "journal": r.journal,
                    "url": r.url,
                    "relevance": r.relevance,
                    "region_tag": r.region_tag,
                    "evidence_tier": r.evidence_tier,
                    "source": r.source,
                })
                if r.abstract:
                    all_abstracts += f"\n\n{r.title}\n{r.abstract}"

            total_papers = len(all_papers)
            evidence_year = max(
                (p.get("year") or 0 for p in all_papers if p.get("year")),
                default=None,
            )

            yield _sse_event("filtering", {
                "source": None, "query": None, "count": total_papers
            })

            # ── FAISS chunk + embed + retrieve ────────────────────────
            if not all_abstracts.strip():
                yield _sse_event("done", {
                    "answer": "No relevant evidence found for this question. Try rephrasing with specific drug names or conditions.",
                    "sources": [],
                    "confidence": "Low",
                    "papers_matched": 0,
                    "evidence_year": None,
                    "region_summary": "N/A",
                    "canvas_update": {},
                    "followup_chips": ["Can you rephrase the question?"],
                    "disambiguation": None,
                    "using_own_knowledge": False,
                })
                return

            chunks = chunk_text(all_abstracts)
            index, _ = rag_engine._build_index(chunks)
            retrieved_chunks, distances = rag_engine._retrieve(index, chunks, question)
            context = "\n\n".join(retrieved_chunks)
            confidence_pct = score_confidence(distances)

            # Map confidence % to High/Moderate/Low tier
            if orchestrator_results:
                confidence_label = assign_confidence(orchestrator_results)
            else:
                if confidence_pct >= 75:
                    confidence_label = "High"
                elif confidence_pct >= 50:
                    confidence_label = "Moderate"
                else:
                    confidence_label = "Low"

            # Region summary for ambient badge
            regional_count = sum(1 for r in orchestrator_results if r.region_tag == "regional")
            if regional_count >= 2:
                region_summary = "Regional"
            elif any(r.region_tag == "regional" for r in orchestrator_results):
                region_summary = "Partly Regional"
            else:
                region_summary = "Extrapolated"

            yield _sse_event("synthesizing", {
                "source": None, "query": None, "count": len(chunks)
            })

            # ── Generate answer ────────────────────────────────────────
            guideline = rag_engine._get_matching_guideline(question)
            canvas_context_str = ""
            if canvas:
                patient = canvas.get("patient", {})
                if patient:
                    canvas_context_str = (
                        f"\n\nCurrent patient context from Researcher Canvas:\n"
                        f"Age: {patient.get('age','unknown')}, "
                        f"Weight: {patient.get('weight','unknown')}, "
                        f"Condition: {patient.get('condition','unknown')}"
                    )

            if evidence_seeking:
                filled_prompt = SOURCES_PROMPT.format(
                    topic=query_question, context=context, question=question
                )
                messages = [{"role": "system", "content": SYSTEM_PROMPT + canvas_context_str}]
                for turn in (history or [])[-5:]:
                    messages.append({"role": "user", "content": turn.get("question", "")})
                    messages.append({"role": "assistant", "content": turn.get("answer", "")})
                messages.append({"role": "user", "content": filled_prompt})
                answer = rag_engine._call_groq(messages, max_tokens=700)
            else:
                system_content = SYSTEM_PROMPT + canvas_context_str
                if guideline:
                    system_content += (
                        f"\n\nLocal Ghana Guideline Context:\n"
                        f"You MUST compare and cross-reference your answer with the following "
                        f"official local standard of care from the {guideline['title']}:\n"
                        f"{guideline['guideline']}\n\n"
                        f"Outline what the local Standard Treatment Guidelines recommend, "
                        f"note any resource-aware clinical adjustments, and discuss NHIS coverage where applicable."
                    )

                filled_prompt = ANSWER_PROMPT.format(context=context, question=question)
                messages = [{"role": "system", "content": system_content}]
                for turn in (history or [])[-5:]:
                    messages.append({"role": "user", "content": turn.get("question", "")})
                    messages.append({"role": "assistant", "content": turn.get("answer", "")})
                messages.append({"role": "user", "content": filled_prompt})
                answer = rag_engine._call_groq(messages, max_tokens=700)

            # ── Follow-up chips ────────────────────────────────────────
            followups = rag_engine._generate_followups(question, answer)

            # ── Build sources list (indexed citations) ─────────────────
            sources_list = []
            idx = 1
            for p in all_papers[:8]:
                sources_list.append({
                    "index": idx,
                    "title": p.get("title", ""),
                    "authors": p.get("authors", ""),
                    "year": p.get("year"),
                    "journal": p.get("journal"),
                    "url": p.get("url", ""),
                    "relevance": p.get("relevance", 0.0),
                    "region_tag": p.get("region_tag", "extrapolated"),
                    "evidence_tier": p.get("evidence_tier", "other"),
                    "source": p.get("source", "pubmed"),
                })
                idx += 1

            # ── Canvas update ──────────────────────────────────────────
            drugs_mentioned = guideline.get("drugs", []) if guideline else []
            canvas_update = {}
            if drugs_mentioned:
                canvas_update["drugs"] = drugs_mentioned

            yield _sse_event("done", {
                "answer": answer,
                "citations": list(range(1, min(len(sources_list) + 1, 4))),
                "sources": sources_list,
                "confidence": confidence_label,
                "papers_matched": total_papers,
                "evidence_year": evidence_year,
                "region_summary": region_summary,
                "canvas_update": canvas_update,
                "followup_chips": followups[:3],
                "disambiguation": None,
                "using_own_knowledge": False,
            })

        except Exception as e:
            import traceback
            yield _sse_event("error", {"message": str(e) + " || " + traceback.format_exc()[-500:]})


class RetrievalRerunView(APIView):
    """
    POST /api/retrieval/rerun/
    Rerun the last query excluding a specified source.
    """

    def post(self, request):
        question = request.data.get("question", "").strip()
        history = request.data.get("history", [])
        exclude_source = request.data.get("exclude_source", "")

        if not question or not exclude_source:
            return Response({"error": "question and exclude_source are required"}, status=400)

        settings = _get_settings(request)
        canvas = _get_canvas(request)
        active = [s for s in settings.get("active_sources", []) if s != exclude_source]
        settings = {**settings, "active_sources": active}

        response = StreamingHttpResponse(
            RetrievalQueryView()._stream(question, history, settings, canvas),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
