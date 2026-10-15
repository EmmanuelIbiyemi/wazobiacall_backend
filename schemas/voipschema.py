from pydantic import BaseModel , validator

class CallBody(BaseModel):
    callee: str


    @validator("callee")
    def normalize_callee(cls, value: str) -> str:
        # Remove leading '+'
        if value.startswith("+"):
            value = value[1:]
        # Replace leading '0' with '234'
        if value.startswith("0"):
            value = "234" + value[1:]
        # Validate length
        if len(value) < 10:
            raise ValueError("Invalid phone number")
        return value

class AcceptBody(BaseModel):
    identity: str