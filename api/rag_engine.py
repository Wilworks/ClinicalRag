

# PubMed fetch → chunk → embed → FAISS index → retrieve → Groq answer → follow-ups

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from groq import Groq
from django.conf import settings

from .prompts import (
    SYSTEM_PROMPT,
    CONVERSE_SYSTEM,
    ANSWER_PROMPT,
    SOURCES_PROMPT,
    FOLLOWUP_PROMPT,
    INTENT_PROMPT,
    REWRITE_PROMPT,
)
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


# ── Anaphoric reaction patterns ───────────────────────────────
# Messages that are clearly reactions to the previous assistant turn,
# not new clinical questions. Pre-checked before any Groq call.
# Saves one LLM round-trip and prevents misclassification.

ANAPHORIC_EXACT = {
    "really", "really?", "nothing?", "nothing at all", "nothing at all?",
    "seriously?", "that's it", "that's it?", "thats it", "thats it?",
    "is that all", "is that all?", "are you sure", "are you sure?",
    "what do you mean", "what do you mean?", "why not", "why not?",
    "hmm", "hm", "i see", "right", "fair enough", "noted", "interesting",
    "makes sense", "ok", "okay", "got it", "understood", "cool", "alright",
    "and?", "so?", "then?", "now what", "now what?",
}

ANAPHORIC_STARTS = (
    "so you found",
    "so nothing",
    "so there's nothing",
    "so there is nothing",
    "you found nothing",
    "you couldn't find",
    "you can't find",
    "couldn't you find",
    "can't you find",
    "what do you mean by",
    "why didn't you",
    "why couldn't you",
    "why can't you",
    "are you saying",
    "so what you're saying",
    "so what you are saying",
    "is that",
    "does that mean",
)

# ── Obvious greeting patterns ─────────────────────────────────
# Ultra-fast bypass — no Groq call needed at all.

OBVIOUS_GREETINGS = {
    "hi", "hello", "hey", "heyy", "heyyy", "yo", "yoo", "yooo",
    "sup", "what's up", "whats up", "wassup", "howdy",
    "thanks", "thank you", "thank u", "thx", "ty",
    "ok", "okay", "k", "kk",
    "bye", "goodbye", "see you", "see ya", "later",
    "good morning", "good afternoon", "good evening", "good night",
    "morning", "afternoon", "evening",
}

PERSONAL_QUESTIONS = {
    "who are you", "what are you", "what can you do",
    "what is evidance", "what is this", "how do you work",
    "tell me about yourself", "introduce yourself",
}


class ClinicalRAGEngine:

    # Loaded once when Django starts — not on every request.
    # SentenceTransformer downloads ~80MB the first time, then caches locally.
    def __init__(self):
        self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
        self.groq = Groq(api_key=settings.GROQ_API_KEY)


    # ── Core pipeline methods ─────────────────────────────────

    def _build_index(self, chunks):
        # Embed all chunks, normalise so inner product = cosine similarity,
        # load into a fresh FAISS index. Rebuilt per request — no stale context.
        embeddings = self.embedder.encode(chunks, convert_to_numpy=True)
        faiss.normalize_L2(embeddings)
        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings)
        return index, embeddings


    def _retrieve(self, index, chunks, question, k=3):
        # Embed question in the same vector space as chunks.
        q_vec = self.embedder.encode([question], convert_to_numpy=True)
        faiss.normalize_L2(q_vec)
        distances, indices = index.search(q_vec, k)
        retrieved = [chunks[i] for i in indices[0] if i < len(chunks)]
        return retrieved, distances


    def _call_groq(self, messages, max_tokens=600):
        # Single reusable Groq call. temperature=0.2 keeps answers factual.
        response = self.groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content


    # ── Intent classification ─────────────────────────────────

    def _fast_intent(self, q_lower):
        """
        Checks obvious cases without a Groq call.
        Returns 'CONVERSE', 'SEARCH', or None (meaning: needs Groq classifier).

        Priority order:
        1. Obvious greetings / personal questions → CONVERSE
        2. Anaphoric reactions (exact match) → CONVERSE
        3. Anaphoric reactions (prefix match) → CONVERSE
        4. Anything else → None (delegate to Groq)
        """
        if q_lower in OBVIOUS_GREETINGS:
            return "CONVERSE"

        if q_lower in PERSONAL_QUESTIONS:
            return "CONVERSE"

        if q_lower in ANAPHORIC_EXACT:
            return "CONVERSE"

        if any(q_lower.startswith(prefix) for prefix in ANAPHORIC_STARTS):
            return "CONVERSE"

        return None


    def _classify_intent(self, question, history=None):
        """
        Classifies intent into CONVERSE / SEARCH / SOURCE_REQUEST.

        Fast-path checks run first (no Groq cost).
        Only ambiguous cases reach the LLM classifier.

        Returns one of: 'CONVERSE', 'SEARCH', 'SOURCE_REQUEST'
        """
        q_lower = question.strip().lower().rstrip("!?. ")

        # Fast path — no LLM needed
        fast = self._fast_intent(q_lower)
        if fast:
            return fast

        # Build history context block for the classifier prompt
        history_context = ""
        if history:
            last = history[-1]
            history_context = (
                f"\nPrevious exchange:\n"
                f"  User asked: {last.get('question', '')}\n"
                f"  System answered: {last.get('answer', '')[:300]}...\n"
            )

        prompt = INTENT_PROMPT.format(
            history_context=history_context,
            question=question,
        )

        try:
            result = self._call_groq(
                [{"role": "user", "content": prompt}],
                max_tokens=10,
            ).strip().upper()

            if "SOURCE" in result:
                return "SOURCE_REQUEST"
            elif "CONVERSE" in result:
                return "CONVERSE"
            else:
                return "SEARCH"  # safe default for a clinical tool

        except Exception:
            return "SEARCH"


    # ── Query rewriting ───────────────────────────────────────

    def _rewrite_query(self, question, history=None):
        """
        Converts a natural language question into tight PubMed keywords.
        Returns 2-4 space-separated terms.
        Falls back to the raw question if the model misbehaves.
        """
        history_block = ""
        if history:
            lines = []
            for turn in history[-3:]:
                lines.append(f"User: {turn.get('question', '')}")
                lines.append(f"Assistant: {turn.get('answer', '')[:200]}")
            history_block = "Conversation History:\n" + "\n".join(lines) + "\n\n"

        prompt = REWRITE_PROMPT.format(
            history_block=history_block,
            question=question,
        )

        try:
            raw = self._call_groq(
                [{"role": "user", "content": prompt}],
                max_tokens=30,
            ).strip().strip('"\'')

            # Model signals no clinical content → fall back to raw question
            if not raw or raw.upper() == "NONE":
                return question

            # Reject if model returned a sentence (contains common filler words)
            filler_signals = (
                "what is", "what are", "how to", "tell me", "explain",
                "effects of", "treatment for", "recommended", "the ", " and the",
            )
            if any(f in raw.lower() for f in filler_signals):
                # Strip filler words manually as a last resort
                words = [
                    w for w in raw.split()
                    if w.lower() not in {
                        "what", "is", "are", "the", "a", "an", "of", "for",
                        "in", "on", "with", "to", "and", "or", "how", "tell",
                        "me", "about", "effects", "treatment", "recommended",
                        "explain", "patients", "this", "that",
                    }
                ]
                raw = " ".join(words[:4])

            print(f"DEBUG REWRITER: '{question}' -> '{raw}'")
            return raw or question

        except Exception:
            return question


    def _rewrite_query_fallback(self, query, history=None):
        """
        Broadens a failed query by simple truncation — no LLM call.
        'malaria Ghana' → 'malaria'
        'hydroxyurea HbSS sickle cell' → 'hydroxyurea HbSS'
        Never hallucinates unrelated terms.
        """
        words = query.strip().split()
        # Keep first 2 words (the most specific clinical terms)
        simplified = " ".join(words[:2]) if len(words) > 2 else words[0] if words else query
        print(f"DEBUG FALLBACK REWRITER: '{query}' -> '{simplified}'")
        return simplified


    # ── Answer generation ─────────────────────────────────────

    def _generate_answer_direct(self, question, history=None):
        """
        Conversational response — no RAG, no PubMed.
        Uses CONVERSE_SYSTEM prompt. Max 120 tokens keeps it brief.
        """
        messages = [{"role": "system", "content": CONVERSE_SYSTEM}]
        if history:
            for turn in history[-3:]:
                messages.append({"role": "user", "content": turn.get("question", "")})
                messages.append({"role": "assistant", "content": turn.get("answer", "")})
        messages.append({"role": "user", "content": question})
        return self._call_groq(messages, max_tokens=120)


    def _generate_answer(self, context, question, history=None, guideline=None, system_adjust=None):
        """
        Main RAG answer generation.
        Optionally injects Ghana guideline context and Wikipedia fallback notes.
        """
        filled_prompt = ANSWER_PROMPT.format(context=context, question=question)

        system_content = SYSTEM_PROMPT
        if system_adjust:
            system_content += system_adjust
        if guideline:
            system_content += (
                f"\n\nLocal Ghana Guideline Context:\n"
                f"You MUST compare and cross-reference your answer with the following "
                f"official local standard of care from the {guideline['title']}:\n"
                f"{guideline['guideline']}\n\n"
                f"Outline what the local Standard Treatment Guidelines recommend, note "
                f"any resource-aware clinical adjustments, and discuss NHIS coverage "
                f"where applicable."
            )

        messages = [{"role": "system", "content": system_content}]
        if history:
            for turn in history[-5:]:
                messages.append({"role": "user", "content": turn.get("question", "")})
                messages.append({"role": "assistant", "content": turn.get("answer", "")})
        messages.append({"role": "user", "content": filled_prompt})
        return self._call_groq(messages, max_tokens=600)


    def _generate_sources_answer(self, context, question, query_question, history=None):
        """
        Source verification answer — uses SOURCES_PROMPT to prevent
        hallucinated citations. Only called for SOURCE_REQUEST intent.
        """
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
        return self._call_groq(messages, max_tokens=600)


    def _generate_followups(self, question, answer):
        """
        Second Groq call — generates 3 follow-up questions.
        Separate call so the model focuses purely on question generation.
        """
        filled_prompt = FOLLOWUP_PROMPT.format(question=question, answer=answer)
        raw = self._call_groq(
            [{"role": "user", "content": filled_prompt}],
            max_tokens=200,
        )
        followups = [q.strip() for q in raw.strip().split("\n") if q.strip()]
        return followups[:3]


    # ── Supporting helpers ────────────────────────────────────

    def _extract_topic_from_history(self, history):
        """
        Extracts the core medical topic from the last conversation turn.
        Used when SOURCE_REQUEST references a prior answer.
        """
        if not history:
            return None
        last = history[-1]
        prompt = (
            "Extract only the core medical topic or condition from this text as "
            "2-4 keywords for a PubMed search query. Output ONLY the keywords, no other text.\n\n"
            f"Prior Question: {last.get('question', '')}\n"
            f"Prior Answer: {last.get('answer', '')[:400]}\n\n"
            "Keywords:"
        )
        try:
            result = self._call_groq(
                [{"role": "user", "content": prompt}],
                max_tokens=30,
            )
            return result.strip().strip('"\'') or last.get("question", "")
        except Exception:
            return last.get("question", "")


    def _get_matching_guideline(self, question):
        """Matches question against Ghana Standard Treatment Guidelines."""
        q_lower = question.lower()
        for key, data in GHANA_GUIDELINES.items():
            if key in q_lower:
                return data
        return None


    def _build_system_adjust(self, wikipedia_mode, is_fallback_wiki):
        """Returns system prompt addendum for Wikipedia-sourced answers."""
        if wikipedia_mode:
            return (
                "\n\nNote: You are answering using structured encyclopedic content "
                "retrieved from Wikipedia. Formulate your response in a highly "
                "professional, clinical context."
            )
        if is_fallback_wiki:
            return (
                "\n\nNote: No direct matching medical literature was found on PubMed. "
                "The following high-quality general medical overview from Wikipedia is "
                "provided instead. Begin your answer with a bold 'Evidence Alert:' note "
                "indicating that PubMed returned zero direct results and Wikipedia was "
                "used as an automatic fallback."
            )
        return None


    # ── Public interface ──────────────────────────────────────

    def run(self, question, west_africa_filter=False, wikipedia_mode=False, history=None):
        """
        Single public method called by views.py.
        Returns a dict the view serialises directly into JSON.
        """
        intent = self._classify_intent(question, history)
        print(f"DEBUG INTENT: '{question[:60]}' → {intent}")

        # ── Branch 1: CONVERSE ────────────────────────────────
        if intent == "CONVERSE":
            answer = self._generate_answer_direct(question, history)
            return {
                "answer": answer,
                "sources": [],
                "confidence": 100.0,
                "followups": [],
                "papers": [],
                "drugs": [],
                "bypassed": True,
            }

        # ── Shared setup for SEARCH + SOURCE_REQUEST ──────────
        guideline = self._get_matching_guideline(question)
        drugs = guideline.get("drugs", []) if guideline else []
        evidence_seeking = (intent == "SOURCE_REQUEST")

        if evidence_seeking and history:
            query_question = self._extract_topic_from_history(history) or self._rewrite_query(question, history)
            print(f"DEBUG SOURCE_REQUEST: topic='{query_question}'")
        else:
            query_question = self._rewrite_query(question, history)

        # ── Branch 2: Wikipedia-only mode ────────────────────
        abstracts = ""
        papers = []
        pmids = []
        is_fallback_wiki = False

        if wikipedia_mode:
            abstracts, papers = search_wikipedia(query_question)
        else:
            # ── Branch 3: PubMed (primary) ────────────────────
            query = bias_west_africa(query_question) if west_africa_filter else query_question
            abstracts, pmids = search_pubmed(query)

            if not abstracts:
                # Fallback 1: broaden the query (no LLM — simple truncation)
                fallback_query_str = self._rewrite_query_fallback(query_question)
                fallback_query = bias_west_africa(fallback_query_str) if west_africa_filter else fallback_query_str
                abstracts, pmids = search_pubmed(fallback_query)

            if not abstracts:
                # Fallback 2: try the raw original question without bias terms
                abstracts, pmids = search_pubmed(question)

            if abstracts:
                papers = fetch_summaries(pmids)
            else:
                # Fallback 3: Wikipedia as last resort
                print(f"DEBUG: PubMed exhausted. Trying Wikipedia for: '{query_question}'")
                abstracts, papers = search_wikipedia(query_question)
                if abstracts:
                    is_fallback_wiki = True

        if not abstracts:
            return {
                "answer": (
                    "No relevant PubMed or Wikipedia articles were found for this question. "
                    "Try rephrasing with specific drug names, conditions, or interventions."
                ),
                "sources": [],
                "confidence": 0,
                "followups": [
                    "Can you rephrase the question with a specific drug or condition?",
                    "Would you like me to search Wikipedia for a general overview?",
                ],
                "papers": [],
                "drugs": drugs,
            }

        # ── RAG core ──────────────────────────────────────────
        chunks = chunk_text(abstracts)
        index, _ = self._build_index(chunks)
        retrieved_chunks, distances = self._retrieve(index, chunks, question)
        context = "\n\n".join(retrieved_chunks)
        confidence = score_confidence(distances)
        system_adjust = self._build_system_adjust(wikipedia_mode, is_fallback_wiki)

        # ── Answer generation ─────────────────────────────────
        if evidence_seeking:
            answer = self._generate_sources_answer(context, question, query_question, history)
        else:
            answer = self._generate_answer(context, question, history, guideline, system_adjust)

        followups = self._generate_followups(question, answer)

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