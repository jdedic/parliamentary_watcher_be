from pydantic import BaseModel


class SpeakerSchema(BaseModel):
    id: int
    name: str
    function: str | None
    party_afkorting: str | None
    party_name_nl: str | None
    party_name_en: str | None
    image_url: str
    resolved: bool
