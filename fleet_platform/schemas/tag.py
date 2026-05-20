from pydantic import BaseModel


class TagCreate(BaseModel):
    key: str
    value: str


class TagResponse(BaseModel):
    key: str
    value: str
    source: str = "user"

    model_config = {"from_attributes": True}
