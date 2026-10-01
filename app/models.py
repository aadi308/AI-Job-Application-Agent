from typing import Literal

from pydantic import BaseModel


class ScrapeRequest(BaseModel):
    source: Literal["greenhouse", "lever"]
    board: str


class ScrapeResult(BaseModel):
    source: str
    board: str
    fetched: int
    inserted: int
