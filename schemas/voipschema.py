from pydantic import BaseModel

class CallBody(BaseModel):
    callee: str
    if callee and callee.startswith("+"):
        callee = callee[1:]
    if callee and callee.startswith("0"):
        callee = "234" + callee[1:]
    if not callee or len(callee) < 10:
        raise ValueError("Invalid phone number")
    return callee

class AcceptBody(BaseModel):
    identity: str