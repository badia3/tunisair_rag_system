import logging
import re
import unicodedata
from datetime import date
from typing import Literal
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, START, END
from app.core.config import get_settings
from app.rag.state import AgentState, RouteDecision, EvidenceGrade
from app.rag.vectorstore import get_retriever
from app.services.tunisair import build_booking_url

logger = logging.getLogger(__name__)
settings = get_settings()

_llm = None

def llm():
    global _llm
    if _llm is None:
        _llm = ChatOllama(
            model=settings.ollama_chat_model,
            base_url=settings.ollama_base_url,
            temperature=0,
        )
    return _llm

def add_trace(state: AgentState, message: str):
    return [*state.get("trace", []), message]


_LOCATION_ALIASES = {
    "tunis": "TUN",
    "tunis carthage": "TUN",
    "djerba": "DJE",
    "monastir": "MIR",
    "paris": "PAR",
    "lyon": "LYS",
    "marseille": "MRS",
    "barcelone": "BCN",
    "barcelona": "BCN",
    "montreal": "YUL",
}
_LOCATION_NAMES = {
    "TUN": "Tunis",
    "DJE": "Djerba",
    "MIR": "Monastir",
    "PAR": "Paris",
    "LYS": "Lyon",
    "MRS": "Marseille",
    "BCN": "Barcelone",
    "YUL": "Montréal",
}
_MONTH_NUMBERS = {
    "janvier": 1, "janv": 1, "january": 1,
    "fevrier": 2, "fevr": 2, "february": 2, "feb": 2,
    "mars": 3, "march": 3, "mar": 3,
    "avril": 4, "avr": 4, "april": 4, "apr": 4,
    "mai": 5, "may": 5,
    "juin": 6, "june": 6, "jun": 6,
    "juillet": 7, "juil": 7, "july": 7, "jul": 7,
    "aout": 8, "august": 8, "aug": 8,
    "septembre": 9, "sept": 9, "september": 9,
    "octobre": 10, "oct": 10, "october": 10,
    "novembre": 11, "nov": 11, "november": 11,
    "decembre": 12, "dec": 12, "december": 12,
}


def _normalize_text(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )


def _extract_flight_search(question: str) -> dict[str, str | None]:
    normalized = _normalize_text(question)
    locations: list[tuple[int, str]] = []
    aliases = {**_LOCATION_ALIASES, **{code.casefold(): code for code in _LOCATION_ALIASES.values()}}
    for alias, code in aliases.items():
        for match in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized):
            locations.append((match.start(), code))
    known_codes = set(_LOCATION_ALIASES.values())
    for match in re.finditer(r"(?<!\w)[A-Z]{3}(?!\w)", question):
        code = match.group().upper()
        if code in known_codes:
            locations.append((match.start(), code))
    locations.sort()
    route_codes = []
    for _, code in locations:
        if not route_codes or route_codes[-1] != code:
            route_codes.append(code)

    date_matches: list[tuple[int, str]] = []
    date_patterns = (
        (re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
        (re.compile(r"(?<!\d)(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?!\d)"), "numeric"),
        (re.compile(r"(?<!\w)(\d{1,2})(?:er)?\s+([a-z]+)\s+(\d{4})(?!\d)"), "month"),
    )
    for pattern, kind in date_patterns:
        for match in pattern.finditer(normalized):
            try:
                if kind == "iso":
                    parsed_date = date(int(match[1]), int(match[2]), int(match[3]))
                elif kind == "numeric":
                    parsed_date = date(int(match[3]), int(match[2]), int(match[1]))
                else:
                    month = _MONTH_NUMBERS.get(match[2])
                    if month is None:
                        continue
                    parsed_date = date(int(match[3]), month, int(match[1]))
            except ValueError:
                continue
            date_matches.append((match.start(), parsed_date.isoformat()))
    date_matches.sort()
    dates = [value for _, value in date_matches]
    return {
        "origin_code": route_codes[0] if route_codes else None,
        "destination_code": route_codes[1] if len(route_codes) > 1 else None,
        "departure_date": dates[0] if dates else None,
        "return_date": dates[1] if len(dates) > 1 else None,
    }


def _is_flight_search_request(question: str) -> bool:
    normalized = _normalize_text(question)
    fare_request = re.search(r"\b(prix|tarif|tarifs|cout|couts|combien|price|prices|fare|fares|cost)\b", normalized)
    flight_topic = re.search(r"\b(vol|vols|billet|billets|avion|flight|flights|itineraire)\b", normalized)
    booking_action = re.search(r"\b(reserver|reservation|recherche|disponibilite|horaire|horaires)\b", normalized)
    return bool(flight_topic and (fare_request or booking_action))


def _is_french_question(question: str) -> bool:
    normalized = _normalize_text(question)
    return bool(re.search(r"\b(quel|quelle|quels|quelles|prix|tarif|vol|billet|combien|depart|retour|voyage)\b", normalized))


def route_question(state: AgentState):
    question = state["question"]
    if _is_flight_search_request(question):
        flight_search = _extract_flight_search(question)
        return {
            "source_used": "booking",
            "flight_search": flight_search,
            "trace": add_trace(state, "Router → BOOKING (flight search request)"),
        }

    router = llm().with_structured_output(RouteDecision, method="function_calling")
    decision = router.invoke(f"""
You route messages for an assistant limited to two official Tunisair pages:
https://www.tunisair.com/fr and https://flights.tunisair.com/fr.
Use kb for Tunisair company information covered by those indexed landing pages.
Use booking only when the user requests a timetable, dates, fares, or availability search.
For booking, extract origin_code and destination_code only when the user explicitly gives
three-letter location codes, and extract departure_date and return_date as YYYY-MM-DD only
when both dates are explicitly stated. Never guess codes or dates. The booking URL is only
provided as a link for the user to open; never fetch the booking website.
Use direct only for greetings or casual chat.
Question: {question}
Return a valid route of kb, booking, or direct.
""")
    extracted = _extract_flight_search(question)
    return {
        "source_used": decision.route,
        "flight_search": {
            "origin_code": extracted["origin_code"] or decision.origin_code,
            "destination_code": extracted["destination_code"] or decision.destination_code,
            "departure_date": extracted["departure_date"],
            "return_date": extracted["return_date"],
        },
        "trace": add_trace(state, f"Router → {decision.route.upper()}"),
    }

def route_after_router(state: AgentState) -> Literal["retrieve_kb", "create_booking_link", "direct_answer"]:
    if state["source_used"] == "booking":
        return "create_booking_link"
    return "retrieve_kb" if state["source_used"] == "kb" else "direct_answer"

def retrieve_kb(state: AgentState):
    docs = get_retriever().invoke(state["current_query"])
    return {"kb_docs": docs, "trace": add_trace(state, f"Private KB retrieval → {len(docs)} chunks")}

def grade_kb(state: AgentState):
    grader = llm().with_structured_output(EvidenceGrade, method="function_calling")
    context = "\n\n".join(
        f"Source: {d.metadata.get('source_url', d.metadata.get('source', 'unknown'))}\n{d.page_content}"
        for d in state["kb_docs"]
    )
    grade = grader.invoke(f"""
You grade evidence for a Tunisair information assistant.
Question: {state['question']}
Evidence from the two approved Tunisair pages:\n{context}
Return good only if the evidence is sufficient to answer confidently and specifically.
Otherwise return weak. JSON: {{"grade":"good"}} or {{"grade":"weak"}}.
""")
    return {"kb_grade": grade.grade, "trace": add_trace(state, f"KB evidence grade → {grade.grade.upper()}")}

def after_kb(state: AgentState) -> Literal["generate_from_kb", "rewrite_query", "insufficient"]:
    if state["kb_grade"] == "good":
        return "generate_from_kb"
    if state["retry_count"] < settings.max_retries:
        return "rewrite_query"
    return "insufficient"

def rewrite_query(state: AgentState):
    rewritten = llm().invoke(f"""
Rewrite this Tunisair company-information question for better retrieval from the two
approved official landing pages. Preserve intent, do not add unsupported facts, return
only the rewritten query.
Question: {state['question']}
""").content.strip()
    return {
        "current_query": rewritten,
        "retry_count": state["retry_count"] + 1,
        "trace": add_trace(state, f"Query rewrite → {rewritten}"),
    }

def generate_from_kb(state: AgentState):
    context = "\n\n".join(
        f"[Source: {d.metadata.get('source_url', d.metadata.get('source', 'unknown'))}]\n{d.page_content}"
        for d in state["kb_docs"]
    )
    answer = llm().invoke(f"""
You answer questions about Tunisair. Answer only from the evidence below, in the user's
language. Do not invent company information, current fares, or flight availability. If
the evidence does not answer the question, clearly say so.
Question: {state['question']}\n\nApproved Tunisair page evidence:\n{context}
""").content
    citations = []
    seen = set()
    for d in state["kb_docs"]:
        src = d.metadata.get("source_url", d.metadata.get("source", "Tunisair website"))
        title = d.metadata.get("title") or src
        if src not in seen:
            seen.add(src)
            citations.append({"title": title, "url": src, "type": "website"})
    return {
        "answer": answer,
        "source_used": "tunisair_website",
        "citations": citations,
        "trace": add_trace(state, "Answer generation → TUNISAIR WEBSITE"),
    }


def create_booking_link(state: AgentState):
    search = state["flight_search"]
    origin_code = search.get("origin_code")
    destination_code = search.get("destination_code")
    departure_date = search.get("departure_date")
    return_date = search.get("return_date")
    if not origin_code or not destination_code or not departure_date or not return_date:
        route = "–".join(
            _LOCATION_NAMES.get(code, code)
            for code in (origin_code, destination_code)
            if code
        )
        if _is_french_question(state["question"]):
            route_text = f" pour le trajet {route}" if route else ""
            missing = []
            if not origin_code or not destination_code:
                missing.append("les villes de départ et de destination")
            if not departure_date:
                missing.append("la date aller")
            if not return_date:
                missing.append("la date retour")
            details = " et ".join(missing)
            answer = (
                f"Le prix{route_text} dépend des dates et des disponibilités ; aucun tarif fixe "
                "ne peut être confirmé ici. Consultez la page officielle « Planifiez votre "
                "prochain vol » pour voir les prix actuels. "
                f"Pour que je prépare une recherche aller-retour, indiquez {details}."
            )
        else:
            route_text = f" for {route}" if route else ""
            missing = []
            if not origin_code or not destination_code:
                missing.append("your origin and destination")
            if not departure_date:
                missing.append("your departure date")
            if not return_date:
                missing.append("your return date")
            details = " and ".join(missing)
            answer = (
                f"The fare{route_text} depends on travel dates and availability, so I can't "
                "confirm a fixed price here. Check current prices on the official “Planifiez "
                "votre prochain vol” page. To prepare a round-trip search link, provide "
                f"{details}."
            )
        return {
            "answer": answer,
            "source_used": "tunisair_booking",
            "citations": [{
                "title": "Planifiez votre prochain vol",
                "url": "https://www.tunisair.com/fr",
                "type": "website",
            }],
            "trace": add_trace(state, "Booking link → waiting for route codes and dates"),
        }

    try:
        url = build_booking_url(origin_code, destination_code, departure_date, return_date)
    except ValueError as exc:
        answer = llm().invoke(f"""
In the same language as the user's question, briefly ask them to correct the Tunisair
round-trip details. Explain this validation issue without adding flight information:
{exc}
Question: {state['question']}
""").content
        return {
            "answer": answer,
            "source_used": "tunisair_booking",
            "trace": add_trace(state, "Booking link → requested valid route codes and dates"),
        }

    answer = llm().invoke(f"""
In the same language as the user's question, say the official Tunisair round-trip search
link is ready for {origin_code} to {destination_code}, departing {departure_date} and returning
{return_date}. Tell the user to open the link to check current timetable and availability.
Do not claim that a flight, seat, or fare is available.
Question: {state['question']}
""").content
    return {
        "answer": answer,
        "source_used": "tunisair_booking_link",
        "citations": [{"title": "Open flight search", "url": url, "type": "website"}],
        "trace": add_trace(state, "Booking link → generated from validated dates; booking site not fetched"),
    }

def direct_answer(state: AgentState):
    answer = llm().invoke(f"Respond briefly and naturally to: {state['question']}").content
    return {"answer": answer, "source_used": "direct", "trace": add_trace(state, "Direct response → no retrieval")}

def insufficient(state: AgentState):
    return {
        "answer": "I couldn't find enough information on the approved Tunisair pages to answer confidently. Please check Tunisair's official website or contact Tunisair.",
        "source_used": "insufficient_evidence",
        "trace": add_trace(state, "Stopped → insufficient reliable evidence"),
    }

def build_graph():
    graph = StateGraph(AgentState)
    for name, fn in {
        "route_question": route_question,
        "retrieve_kb": retrieve_kb,
        "grade_kb": grade_kb,
        "rewrite_query": rewrite_query,
        "generate_from_kb": generate_from_kb,
        "create_booking_link": create_booking_link,
        "direct_answer": direct_answer,
        "insufficient": insufficient,
    }.items():
        graph.add_node(name, fn)

    graph.add_edge(START, "route_question")
    graph.add_conditional_edges("route_question", route_after_router, {
        "retrieve_kb": "retrieve_kb",
        "create_booking_link": "create_booking_link",
        "direct_answer": "direct_answer",
    })
    graph.add_edge("retrieve_kb", "grade_kb")
    graph.add_conditional_edges("grade_kb", after_kb, {
        "generate_from_kb": "generate_from_kb",
        "rewrite_query": "rewrite_query",
        "insufficient": "insufficient",
    })
    graph.add_edge("rewrite_query", "retrieve_kb")
    graph.add_edge("generate_from_kb", END)
    graph.add_edge("create_booking_link", END)
    graph.add_edge("direct_answer", END)
    graph.add_edge("insufficient", END)
    return graph.compile()

agent_graph = build_graph()

def ask(question: str):
    initial: AgentState = {
        "question": question,
        "current_query": question,
        "kb_docs": [],
        "flight_search": {},
        "kb_grade": "",
        "answer": "",
        "source_used": "",
        "retry_count": 0,
        "trace": [],
        "citations": [],
    }
    return agent_graph.invoke(initial)
