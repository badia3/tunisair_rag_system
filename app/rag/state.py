from typing import List, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from langchain_core.documents import Document

class RouteDecision(BaseModel):
    route: Literal["kb", "booking", "direct"] = Field(
        description="kb for Tunisair company information, booking for a timetable/availability search, direct for greetings"
    )
    origin_code: str | None = Field(default=None, description="Explicit three-letter Tunisair origin location code")
    destination_code: str | None = Field(default=None, description="Explicit three-letter Tunisair destination location code")
    departure_date: str | None = Field(default=None, description="Explicit departure date in YYYY-MM-DD format")
    return_date: str | None = Field(default=None, description="Explicit return date in YYYY-MM-DD format")

class EvidenceGrade(BaseModel):
    grade: Literal["good", "weak"] = Field(description="Whether evidence is sufficient to answer")

class AgentState(TypedDict):
    question: str
    current_query: str
    kb_docs: List[Document]
    flight_search: dict[str, str | None]
    kb_grade: str
    answer: str
    source_used: str
    retry_count: int
    trace: List[str]
    citations: List[dict]
