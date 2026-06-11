from pydantic import BaseModel


class ChatAuthRequest(BaseModel):
    password: str
