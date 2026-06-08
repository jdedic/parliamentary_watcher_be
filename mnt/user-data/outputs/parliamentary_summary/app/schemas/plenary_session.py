from datetime import datetime
from pydantic import BaseModel


class PlenarySessionDocumentSchema(BaseModel):
    """Schema for a session document."""

    id: int
    session_id: str
    document_id: str
    file_path: str | None
    downloaded_at: datetime

    model_config = {"from_attributes": True}


class PlenarySessionSchema(BaseModel):
    """Schema for a plenary session returned to the client."""

    id: str
    soort: str | None
    titel: str | None
    zaal: str | None
    vergaderjaar: str | None
    vergadering_nummer: int | None
    datum: datetime | None
    aanvangstijd: datetime | None
    sluiting: datetime | None
    kamer: str | None
    gewijzigd_op: datetime | None
    api_gewijzigd_op: datetime | None
    verwijderd: bool
    created_at: datetime
    documents: list[PlenarySessionDocumentSchema] = []

    model_config = {"from_attributes": True}


class SessionListResponse(BaseModel):
    """Paginated list of plenary sessions."""

    total: int
    sessions: list[PlenarySessionSchema]
