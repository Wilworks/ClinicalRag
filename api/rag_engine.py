
# PubMed fetch → chunk → embed → FAISS index → retrieve → Groq answer → follow-ups

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from groq import Groq
from django.conf import settings

from .prompts import SYSTEM_PROMPT, ANSWER_PROMPT, SOURCES_PROMPT, FOLLOWUP_PROMPT
from .tools import (
    search_pubmed,
    bias_west_africa,
    chunk_text,
    score_confidence,
    format_sources,
    fetch_summaries,
    search_wikipedia,
)
from .guidelines_data import GHANA_GUIDELINES


# Phrases that signal the user is asking for sources/citations from a prior answer.
# These ALWAYS trigger a real PubMed search — never conversational bypass.
# Pattern is intentionally broad so short follow-ups like "cite that" are caught.
# NOTE: This list is kept as a fast-path pre-check for very obvious cases only.
# The primary detection is handled by the dynamic Groq intent classifier below.
EVIDENCE_SEEKING_PHRASES = [
    "source", "sources", "reference", "references", "citation", "citations",
    "cite", "back this up", "back that up", "evidence for", "evidence on",
    "studies on", "studies about", "papers on", "papers about", "research on",
    "where did you get", "prove it", "prove this", "show me", "pubmed",
    "what study", "which study", "which paper", "which journal",
    "can you cite", "do you have a source", "do you have sources",
    "any sources", "any references", "any evidence", "any studies",
    "can you reference", "can you reference", "where does this come from",
]


class ClinicalRAGEngine:

    # Loaded once when Django starts — not on every request.
    # SentenceTransformer downloads ~80MB the first time, then caches it locally.
    def __init__(self):
        self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
        self.groq = Groq(api_key=settings.GROQ_API_KEY)


    def _build_index(self, chunks):
        # Embed all chunks into vectors, normalise them so inner product
        # equals cosine similarity, then load into a fresh FAISS index.
        # We rebuild the index fresh per request — no stale abstracts
        # bleeding between different users' questions.
        embeddings = self.embedder.encode(chunks, convert_to_numpy=True)
        faiss.normalize_L2(embeddings)

        # IndexFlatIP = exact inner product search, no approximation.
        # Fine for small chunk counts (< 100) which is all we ever have here.
        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings)
        return index, embeddings


    def _retrieve(self, index, chunks, question, k=3):
        # Embed the question using the same model as the chunks —
        # they must live in the same vector space for similarity to mean anything.
        q_vec = self.embedder.encode([question], convert_to_numpy=True)
        faiss.normalize_L2(q_vec)

        # Search returns distances (similarity scores) and indices into chunks list.
        distances, indices = index.search(q_vec, k)

        # Pull the actual chunk text using the returned indices.
        retrieved = [chunks[i] for i in indices[0] if i < len(chunks)]
        return retrieved, distances


    def _call_groq(self, messages, max_tokens=600):
        # Single reusable method for all Groq calls.
        # temperature=0.2 keeps answers factual and consistent —
        # higher temperature would make it more creative but less reliable
        # for clinical content.
        response = self.groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content


    def _rewrite_query(self, question, history=None):
        # Conversational query expansion & PubMed optimization:
        # Use Groq to rewrite the question (and history if present) into a standalone,
        # concise, keyword-based search query suitable for PubMed.
        
        history_str = ""
        if history:
            for turn in history[-3:]:  # Keep last 3 turns for query context
                history_str += f"Clinician: {turn.get('question', '')}\nEvidance: {turn.get('answer', '')}\n\n"

        prompt = f"""You are a medical search query engineer. Convert the user's input (and conversation history, if any) into a clean, concise, keyword-based PubMed search query.
- Extract only core medical conditions, drugs, interventions, and population demographics.
- Do NOT use natural language filler words (e.g., "what is the", "effects of", "recommended", "treatment for", "in patients with").
- Keep it to 3 to 6 key terms max.
- Output ONLY the final raw search keywords. Do NOT add any preamble, conversational text, quotes, or markdown.

{"Conversation History:\n" + history_str if history else ""}
User Input: {question}

Concise Keywords Search Query:"""

        messages = [
            {"role": "user", "content": prompt}
        ]

        try:
            rewritten = self._call_groq(messages, max_tokens=60).strip()
            # Strip quotes if the LLM returned them
            if rewritten.startswith('"') and rewritten.endswith('"'):
                rewritten = rewritten[1:-1]
            if rewritten.startswith("'") and rewritten.endswith("'"):
                rewritten = rewritten[1:-1]
            print(f"DEBUG REWRITER: '{question}' -> '{rewritten}'")
            return rewritten
        except Exception:
            return question


    def _rewrite_query_fallback(self, question, history=None):
        # Generates a broader fallback query focusing purely on primary interventions/drugs
        # and physiological mechanisms, omitting specific patient demographics or niche co-morbidities.
        prompt = f"""You are a medical search query engineer. The previous specific search query returned zero results on PubMed.
Please generate a broader, fallback keyword search query that focuses ONLY on the active drug/intervention and its primary mechanism of action or physiological effects, omitting any specific patient populations or niche co-morbidities.
- Extract only the active drug/intervention (e.g., SGLT2 inhibitors) and the key mechanism/outcome (e.g., kidney function, intraglomerular pressure).
- Do NOT include specific patient populations (like "sickle cell disease" or "pediatric").
- Output ONLY the final raw search keywords. Do NOT add any preamble, conversational text, quotes, or markdown.

User Input: {question}

Broader Keywords Search Query:"""

        messages = [
            {"role": "user", "content": prompt}
        ]

        try:
            rewritten = self._call_groq(messages, max_tokens=60).strip()
            if rewritten.startswith('"') and rewritten.endswith('"'):
                rewritten = rewritten[1:-1]
            if rewritten.startswith("'") and rewritten.endswith("'"):
                rewritten = rewritten[1:-1]
            print(f"DEBUG FALLBACK REWRITER: '{question}' -> '{rewritten}'")
            return rewritten
        except Exception:
            return question


    def _classify_intent(self, question, history=None):
        """
        Dynamically classifies the user's intent into one of three modes
        using a fast Groq call. This replaces all hard-coded phrase matching.

        Returns:
            'CONVERSE'       - greeting, thanks, chitchat → simple bubble, no RAG
            'SEARCH'         - new clinical/research question → full evidence card
            'SOURCE_REQUEST' - asking for citations/references/proof → source
                               verification card using prior history topic
        """
        history_context = ""
        if history:
            last = history[-1]
            history_context = f"""
Previous exchange:
  Clinician asked: {last.get('question', '')}
  System answered: {last.get('answer', '')[:300]}..."""

        prompt = f"""You are an intent classifier for a clinical evidence assistant.
Classify the user's latest message into EXACTLY one of these three categories:

SEARCH
  The user is asking a new clinical, scientific, or research question that needs
  real medical literature to answer. Includes questions about diseases, drugs,
  treatments, dosages, mechanisms, complications, epidemiology, or general medical
  knowledge — even phrased casually like "what does the evidence say about X?",
  "tell me about Y", or "what's the latest on Z?".

SOURCE_REQUEST
  The user wants citations, references, or proof for a previous answer.
  Includes any message whose intent is to verify, validate, or attribute the prior
  response — even if phrased indirectly, e.g. "where did that come from?",
  "I need the papers for my essay", "back that up", "prove it", "any studies?",
  "can you reference that?", "what are the PMIDs?", "do you have sources?".

CONVERSE
  The user is greeting, thanking, acknowledging, or making small talk.
  No scientific literature is needed. E.g. "hello", "thanks", "that makes sense",
  "ok", "good morning", "how are you", "that was helpful".
{history_context}

User message: {question}

Intent (output ONLY one word — SEARCH, SOURCE_REQUEST, or CONVERSE):"""

        try:
            result = self._call_groq(
                [{"role": "user", "content": prompt}],
                max_tokens=10
            ).strip().upper()
            if "SOURCE" in result:
                return "SOURCE_REQUEST"
            elif "CONVERSE" in result:
                return "CONVERSE"
            else:
                return "SEARCH"  # safe default for clinical tool
        except Exception:
            return "SEARCH"


    def _is_evidence_seeking(self, question, history=None):
        """Kept for backward compatibility — delegates to _classify_intent."""
        return self._classify_intent(question, history) == "SOURCE_REQUEST"


    def _extract_topic_from_history(self, history):
        """Extracts the most recent medical topic from conversation history
        to use as the rewrite seed when the user asks for sources."""
        if not history:
            return None
        last_answer = history[-1].get("answer", "")
        last_question = history[-1].get("question", "")
        # Ask Groq to extract the core medical topic from the prior turn
        prompt = f"""Extract only the core medical topic or condition from this text as 3-5 keywords for a PubMed search query. Output ONLY the keywords, no other text.

Prior Question: {last_question}
Prior Answer: {last_answer[:400]}

Keywords:"""
        try:
            result = self._call_groq([{"role": "user", "content": prompt}], max_tokens=40)
            return result.strip()
        except Exception:
            return last_question  # fallback to the raw prior question


    def _should_search_pubmed(self, question, history=None):
        """
        Returns True if the question should trigger a PubMed/Wikipedia search.
        Delegates intent classification to _classify_intent for all non-trivial cases.
        """
        # Ultra-fast bypass for very obvious greetings (saves one Groq call)
        q_lower = question.strip().lower().rstrip("!?.")
        obvious_greetings = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay"}
        if q_lower in obvious_greetings:
            return False

        # For everything else, use the dynamic classifier
        intent = self._classify_intent(question, history)
        return intent != "CONVERSE"



    def _generate_answer_direct(self, question, history=None):
        # Generates a quick conversational response based directly on prior history
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\nYou are in a conversation. Respond directly to the user's greeting, thanks, or clarification request. Do not perform any literature searches. Keep your response helpful, warm, and concise."},
        ]

        if history:
            for turn in history[-5:]:
                messages.append({"role": "user", "content": turn.get("question", "")})
                messages.append({"role": "assistant", "content": turn.get("answer", "")})

        messages.append({"role": "user", "content": question})
        return self._call_groq(messages, max_tokens=400)


    def _get_matching_guideline(self, question):
        # Scan question for focus conditions to anchor regional guidance
        q_lower = question.lower()
        for key, data in GHANA_GUIDELINES.items():
            if key in q_lower:
                return data
        return None


    def _generate_answer(self, context, question, history=None, guideline=None):
        # Fills in the ANSWER_PROMPT template and sends it to Groq.
        # The system prompt sets the rules, the user message carries
        # the evidence and the question.
        filled_prompt = ANSWER_PROMPT.format(
            context=context,
            question=question,
        )

        system_content = SYSTEM_PROMPT
        if guideline:
            system_content += (
                f"\n\nLocal Ghana Guideline Context:\n"
                f"You MUST compare and cross-reference your answer with the following official local standard of care from the {guideline['title']}:\n"
                f"{guideline['guideline']}\n\n"
                f"Outline what the local Standard Treatment Guidelines recommend, note any resource-aware clinical adjustments, and discuss NHIS coverage where applicable."
            )

        messages = [
            {"role": "system", "content": system_content},
        ]

        # Inject conversational context
        if history:
            for turn in history[-5:]:  # Keep last 5 turns to stay under token limits
                messages.append({"role": "user", "content": turn.get("question", "")})
                messages.append({"role": "assistant", "content": turn.get("answer", "")})

        messages.append({"role": "user", "content": filled_prompt})
        return self._call_groq(messages, max_tokens=600)


    def _generate_followups(self, question, answer):
        # Second Groq call — separate from the answer call so the model
        # focuses purely on generating questions, not continuing the answer.
        filled_prompt = FOLLOWUP_PROMPT.format(
            question=question,
            answer=answer,
        )
        messages = [
            {"role": "user", "content": filled_prompt},
        ]
        raw = self._call_groq(messages, max_tokens=200)

        # The model returns 3 questions as newline-separated text.
        # We split, strip whitespace, and drop any empty lines.
        followups = [q.strip() for q in raw.strip().split("\n") if q.strip()]
        return followups[:3]  # hard cap at 3


    def run(self, question, west_africa_filter=False, wikipedia_mode=False, history=None):
        # The single public method views.py calls.
        # Returns a dict the view serialises directly into JSON.

        # One Groq call to classify intent: CONVERSE / SEARCH / SOURCE_REQUEST
        # This single call drives all three routing branches below.
        q_lower = question.strip().lower().rstrip("!?.")
        obvious_greetings = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay"}
        if q_lower in obvious_greetings:
            intent = "CONVERSE"
        else:
            intent = self._classify_intent(question, history)

        print(f"DEBUG INTENT: '{question[:60]}' → {intent}")

        # CONVERSE → simple chat bubble, no PubMed
        if intent == "CONVERSE":
            answer = self._generate_answer_direct(question, history)
            return {
                "answer": answer,
                "sources": [],
                "confidence": 100.0,
                "followups": ["How else can I assist you with your research?"],
                "papers": [],
                "drugs": [],
                "bypassed": True,
            }

        # Look up standard local guidelines (STGs)
        guideline = self._get_matching_guideline(question)
        drugs = guideline.get("drugs", []) if guideline else []

        # SOURCE_REQUEST → search for prior topic, use SOURCES_PROMPT
        # SEARCH → normal query rewriting
        evidence_seeking = (intent == "SOURCE_REQUEST")
        if evidence_seeking and history:
            topic = self._extract_topic_from_history(history)
            query_question = topic or self._rewrite_query(question, history)
            print(f"DEBUG SOURCE_REQUEST: topic='{query_question}'")
        else:
            query_question = self._rewrite_query(question, history)

        
        abstracts = ""
        papers = []
        is_fallback_wiki = False

        if wikipedia_mode:
            # Query Wikipedia directly
            abstracts, papers = search_wikipedia(query_question)
        else:
            # Query PubMed
            query = bias_west_africa(query_question) if west_africa_filter else query_question
            abstracts, pmids = search_pubmed(query)

            if not abstracts:
                # PubMed primary failed, try broader mechanism fallback
                fallback_question = self._rewrite_query_fallback(query_question, history)
                fallback_query = bias_west_africa(fallback_question) if west_africa_filter else fallback_question
                abstracts, pmids = search_pubmed(fallback_query)

            if abstracts:
                papers = fetch_summaries(pmids)
            else:
                # Both PubMed attempts failed. Trigger automatic Wikipedia fallback!
                print(f"DEBUG FALLBACK: PubMed returned no results. Trying Wikipedia fallback for: '{query_question}'")
                abstracts, papers = search_wikipedia(query_question)
                if abstracts:
                    is_fallback_wiki = True

        if not abstracts:
            return {
                "answer": "No relevant PubMed or Wikipedia articles found for this question.",
                "sources": [],
                "confidence": 0,
                "followups": [],
                "papers": [],
                "drugs": drugs,
            }

        # Embed, index, and retrieve matching chunks
        chunks = chunk_text(abstracts)
        index, _ = self._build_index(chunks)
        retrieved_chunks, distances = self._retrieve(index, chunks, question)

        # Join the top-3 chunks into one block of context for the prompt.
        context = "\n\n".join(retrieved_chunks)

        # Adjust system context based on Wikipedia fallback or explicit search
        system_adjust = None
        if wikipedia_mode:
            system_adjust = "\n\nNote: You are answering using structured encyclopedic content retrieved from Wikipedia. Formulate your response in a highly professional, clinical context."
        elif is_fallback_wiki:
            system_adjust = "\n\nNote: No direct matching medical literature was found on PubMed, so the following high-quality general medical overview from Wikipedia is provided instead. Please begin your answer by warning the user with a bold 'Comparison Alert:' note indicating that PubMed search yielded zero direct trial results and Wikipedia was used as an auto-fallback search."

        # Generate answer
        if evidence_seeking:
            # Use SOURCES_PROMPT so the model presents ONLY real retrieved papers,
            # never fabricated citations. topic is the extracted medical subject.
            topic = query_question
            filled_prompt = SOURCES_PROMPT.format(
                topic=topic,
                context=context,
                question=question,
            )
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            if history:
                for turn in history[-5:]:
                    messages.append({"role": "user", "content": turn.get("question", "")})
                    messages.append({"role": "assistant", "content": turn.get("answer", "")})
            messages.append({"role": "user", "content": filled_prompt})
            answer = self._call_groq(messages, max_tokens=600)
        else:
            answer = self._generate_answer(
                context,
                question,
                history,
                guideline=guideline
            )
        
        if system_adjust and not evidence_seeking:
            # Re-generate answer with custom instructions injected into the system prompt
            filled_prompt = ANSWER_PROMPT.format(
                context=context,
                question=question,
            )
            system_content = SYSTEM_PROMPT + system_adjust
            if guideline:
                system_content += (
                    f"\n\nLocal Ghana Guideline Context:\n"
                    f"You MUST compare and cross-reference your answer with the following official local standard of care from the {guideline['title']}:\n"
                    f"{guideline['guideline']}\n\n"
                    f"Outline what the local Standard Treatment Guidelines recommend, note any resource-aware clinical adjustments, and discuss NHIS coverage where applicable."
                )

            messages = [
                {"role": "system", "content": system_content},
            ]
            if history:
                for turn in history[-5:]:
                    messages.append({"role": "user", "content": turn.get("question", "")})
                    messages.append({"role": "assistant", "content": turn.get("answer", "")})
            messages.append({"role": "user", "content": filled_prompt})
            answer = self._call_groq(messages, max_tokens=600)

        followups = self._generate_followups(question, answer)
        confidence = score_confidence(distances)
        
        # Sources formatting
        if wikipedia_mode or is_fallback_wiki:
            sources = [p["url"] for p in papers]
        else:
            sources = format_sources(pmids)

        return {
            "answer": answer,
            "sources": sources,
            "confidence": confidence,
            "followups": followups,
            "papers": papers,
            "drugs": drugs,
            "wikipedia_searched": wikipedia_mode or is_fallback_wiki,
            "evidence_seeking": evidence_seeking,
        }


# Module-level singleton — Django imports this once at startup.
# Every request shares the same loaded embedder and Groq client.
rag_engine = ClinicalRAGEngine()