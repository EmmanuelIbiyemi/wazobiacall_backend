from pydantic import BaseModel

class CallBody(BaseModel):
    callee: str


class AcceptBody(BaseModel):
    identity: str