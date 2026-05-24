# Three views — one for each endpoint registered in api/urls.py.
# Views are thin — they validate, call the engine, and return.


import json
from django.shortcuts import render
from django.http import StreamingHttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .rag_engine import rag_engine
from .serializers import QuestionSerializer
from django.http import HttpResponse
from .pdf_export import generate_pdf

# ── /api/ask/ ─────────────────────────────────────────────────
# Standard REST endpoint — waits for the full pipeline to finish
# then returns everything as one JSON response.
# Engineers use this with curl or Postman.

class ClinicalRAGView(APIView):

    def post(self, request):
        serializer = QuestionSerializer(data=request.data)

        # If validation fails, DRF automatically returns 400
        # with the error messages we defined in serializers.py.
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        question = serializer.validated_data["question"]
        west_africa_filter = serializer.validated_data["west_africa_filter"]
        wikipedia_mode = serializer.validated_data.get("wikipedia_mode", False)
        history = serializer.validated_data.get("history", [])

        result = rag_engine.run(
            question=question,
            west_africa_filter=west_africa_filter,
            wikipedia_mode=wikipedia_mode,
            history=history,
        )

        return Response(result, status=status.HTTP_200_OK)


# ── /api/ask/stream/ ──────────────────────────────────────────
# SSE endpoint — emits progress events as each pipeline stage completes.
# The frontend listens with EventSource and renders each event
# as it arrives, giving the Perplexity-style live feed effect.

class ClinicalRAGStreamView(APIView):

    def post(self, request):
        serializer = QuestionSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        question = serializer.validated_data["question"]
        west_africa_filter = serializer.validated_data["west_africa_filter"]
        wikipedia_mode = serializer.validated_data.get("wikipedia_mode", False)
        history = serializer.validated_data.get("history", [])

        # SSE requires a streaming response with this specific content type.
        # The browser's EventSource API expects this exact format.
        response = StreamingHttpResponse(
            self._stream(question, west_africa_filter, wikipedia_mode, history),
            content_type="text/event-stream",
        )

        # These headers prevent proxies and browsers from buffering the stream —
        # without them the client would wait for the full response before rendering.
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


    def _stream(self, question, west_africa_filter, wikipedia_mode, history):
        # Generator function — each yield sends one SSE event to the browser.
        # SSE format is strict: "data: <payload>\n\n"
        # The double newline signals the end of one event to the client.

        def event(stage, payload):
            # Wraps any dict into the SSE wire format.
            data = json.dumps({"stage": stage, **payload})
            return f"data: {data}\n\n"

        try:
            from .tools import search_pubmed, bias_west_africa, chunk_text, score_confidence, format_sources, fetch_summaries, search_wikipedia
            from .prompts import SYSTEM_PROMPT, ANSWER_PROMPT, SOURCES_PROMPT, FOLLOWUP_PROMPT

            # One Groq call to classify intent — drives all routing below.
            q_lower = question.strip().lower().rstrip("!?.")
            obvious_greetings = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay"}
            if q_lower in obvious_greetings:
                intent = "CONVERSE"
            else:
                intent = rag_engine._classify_intent(question, history)

            print(f"DEBUG SSE INTENT: '{question[:60]}' → {intent}")

            # CONVERSE → simple chat bubble, no PubMed
            if intent == "CONVERSE":
                yield event("generating", {"message": "Responding...", "bypassed": True})
                answer = rag_engine._generate_answer_direct(question, history)
                yield event("done", {
                    "answer": answer,
                    "sources": [],
                    "confidence": 100.0,
                    "followups": ["How else can I assist you with your research?"],
                    "papers": [],
                    "drugs": [],
                    "bypassed": True,
                })
                return

            # SOURCE_REQUEST → extract prior topic for PubMed search
            # SEARCH → normal query rewriting
            evidence_seeking = (intent == "SOURCE_REQUEST")
            if evidence_seeking and history:
                query_question = rag_engine._extract_topic_from_history(history) or rag_engine._rewrite_query(question, history)
                print(f"DEBUG SSE SOURCE_REQUEST: topic='{query_question}'")
            else:
                query_question = rag_engine._rewrite_query(question, history)

            # Lookup standard local guidelines (STGs)
            guideline = rag_engine._get_matching_guideline(question)
            drugs = guideline.get("drugs", []) if guideline else []

            abstracts = ""
            papers = []
            is_fallback_wiki = False
            pmids = []

            # Always search PubMed first
            query = bias_west_africa(query_question) if west_africa_filter else query_question
            yield event("searching", {"message": f'Searching PubMed for "{query_question}"'})
            abstracts, pmids = search_pubmed(query)

            if not abstracts:
                # Broad fallback search
                fallback_question = rag_engine._rewrite_query_fallback(query_question, history)
                fallback_query = bias_west_africa(fallback_question) if west_africa_filter else fallback_question
                yield event("searching", {"message": f'No results. Trying PubMed fallback for "{fallback_question}"'})
                abstracts, pmids = search_pubmed(fallback_query)

            if abstracts:
                papers = fetch_summaries(pmids)

            # If Wikipedia mode is ON, augment with Wikipedia results
            if wikipedia_mode:
                wiki_query = query_question
                yield event("searching", {"message": f'Augmenting with Wikipedia for "{wiki_query}"'})
                wiki_abstracts, wiki_papers = search_wikipedia(wiki_query)
                if wiki_abstracts:
                    abstracts = abstracts + ("\n\n" if abstracts else "") + wiki_abstracts
                    papers = papers + wiki_papers
                    is_fallback_wiki = not bool(pmids)  # True only if PubMed returned nothing

            # If still nothing, try Wikipedia as last resort
            if not abstracts:
                yield event("searching", {"message": "No PubMed results. Searching Wikipedia overview..."})
                abstracts, papers = search_wikipedia(query_question)
                if abstracts:
                    is_fallback_wiki = True
                else:
                    yield event("error", {"message": "No PubMed or Wikipedia articles found for this question."})
                    return

            yield event("found", {
                "message": f"Found abstracts · chunking and embedding",
                "count": len(papers),
                "papers": papers,
            })


            chunks = chunk_text(abstracts)

            yield event("embedding", {
                "message": f"Embedded {len(chunks)} chunks · retrieving top matches",
            })

            # Build FAISS index and retrieve — reusing engine private methods
            index, _ = rag_engine._build_index(chunks)
            retrieved_chunks, distances = rag_engine._retrieve(index, chunks, question)
            context = "\n\n".join(retrieved_chunks)
            confidence = score_confidence(distances)

            yield event("retrieving", {
                "message": f"Retrieved top 3 chunks · confidence {confidence}%",
                "confidence": confidence,
            })

            yield event("generating", {"message": "Verifying sources..." if evidence_seeking else "Generating answer..."})

            if evidence_seeking:
                # Use SOURCES_PROMPT to prevent hallucinated citations
                filled_prompt = SOURCES_PROMPT.format(
                    topic=query_question,
                    context=context,
                    question=question,
                )
                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                if history:
                    for turn in history[-5:]:
                        messages.append({"role": "user", "content": turn.get("question", "")})
                        messages.append({"role": "assistant", "content": turn.get("answer", "")})
                messages.append({"role": "user", "content": filled_prompt})
                answer = rag_engine._call_groq(messages, max_tokens=600)
            else:
                # Adjust system context based on Wikipedia fallback or explicit search
                system_adjust = None
                if wikipedia_mode:
                    system_adjust = "\n\nNote: You are answering using structured encyclopedic content retrieved from Wikipedia. Formulate your response in a highly professional, clinical context."
                elif is_fallback_wiki:
                    system_adjust = "\n\nNote: No direct matching medical literature was found on PubMed, so the following high-quality general medical overview from Wikipedia is provided instead. Please begin your answer by warning the user with a bold 'Comparison Alert:' note indicating that PubMed search yielded zero direct trial results and Wikipedia was used as an auto-fallback search."

                system_content = SYSTEM_PROMPT
                if system_adjust:
                    system_content += system_adjust
                if guideline:
                    system_content += (
                        f"\n\nLocal Ghana Guideline Context:\n"
                        f"You MUST compare and cross-reference your answer with the following official local standard of care from the {guideline['title']}:\n"
                        f"{guideline['guideline']}\n\n"
                        f"Outline what the local Standard Treatment Guidelines recommend, note any resource-aware clinical adjustments, and discuss NHIS coverage where applicable."
                    )

                messages = [{"role": "system", "content": system_content}]
                if history:
                    for turn in history[-5:]:
                        messages.append({"role": "user", "content": turn.get("question", "")})
                        messages.append({"role": "assistant", "content": turn.get("answer", "")})

                filled_prompt = ANSWER_PROMPT.format(context=context, question=question)
                messages.append({"role": "user", "content": filled_prompt})
                answer = rag_engine._call_groq(messages, max_tokens=600)

            yield event("answering", {"message": "Generating follow-up questions..."})

            followups = rag_engine._generate_followups(question, answer)
            sources = [p["url"] for p in papers] if (wikipedia_mode or is_fallback_wiki) else format_sources(pmids)
            print(f"Sources: {sources}")
            # Final event carries the complete result —
            # the frontend uses this to render the answer card.
            yield event("done", {
                "answer": answer,
                "sources": sources,
                "confidence": confidence,
                "followups": followups,
                "papers": papers,
                "drugs": drugs,
                "wikipedia_searched": wikipedia_mode or is_fallback_wiki,
                "evidence_seeking": evidence_seeking,
            })



        except Exception as e:
            # Always catch and stream errors — an unhandled exception here
            # silently kills the stream and the frontend hangs forever.
        
            import traceback
            yield event("error", {"message": str(e) + " || " + traceback.format_exc()[-400:]})


# ── /api/health/ ──────────────────────────────────────────────
# Simple GET endpoint HF Spaces uses to verify the app is alive.
# Also confirms the RAG engine initialised without errors at startup.

class HealthCheckView(APIView):

    def get(self, request):
        return Response({
            "status": "ok",
            "engine": "loaded",
            "model": "llama-3.1-8b-instant",
            "embedder": "all-MiniLM-L6-v2",
        }, status=status.HTTP_200_OK)
    


    # ── /api/pdf/ ─────────────────────────────────────────────────
# Receives the full answer payload + user name,
# generates a PDF and streams it as a file download.

class PDFExportView(APIView):

    def post(self, request):
        # Support full history if sent by modern UI, fallback to single turn for backward compatibility
        history = request.data.get("history", [])
        name = request.data.get("name", "Anonymous").strip() or "Anonymous"

        if not history:
            question   = request.data.get("question", "")
            answer     = request.data.get("answer", "")
            sources    = request.data.get("sources", [])
            confidence = request.data.get("confidence", 0)
            followups  = request.data.get("followups", [])

            if question and answer:
                history = [{
                    "question": question,
                    "answer": answer,
                    "sources": sources,
                    "confidence": confidence,
                    "followups": followups,
                }]

        if not history:
            return Response(
                {"error": "Conversation history or question/answer are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pdf_bytes = generate_pdf(
            history=history,
            name=name,
        )

        # Build a clean filename from the first question in the session
        first_q = history[0].get("question", "report")
        safe_name = first_q[:40].strip().replace(" ", "_").lower()
        filename  = f"clinicalrag_{safe_name}.pdf"

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response