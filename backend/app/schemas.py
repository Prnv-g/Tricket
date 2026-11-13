from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import EVENT

EventId = Annotated[str, Field(pattern=r"^(neon-nights|demo-[a-f0-9]{32})$")]
TokenId = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
Key = Annotated[str, Field(min_length=8, max_length=96, pattern=r"^[a-zA-Z0-9._-]+$")]
SeatId = Annotated[int, Field(ge=1, le=5200, strict=True)]
Tier = Literal["Front Row", "Lower Bowl", "Upper Bowl"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Behavior(Input):
    intervals: list[Annotated[int, Field(ge=0, le=60000)]] = Field(default_factory=list, max_length=32)
    moves: int = Field(default=0, ge=0, le=4000)
    clicks: int = Field(default=0, ge=0, le=200)
    elapsed_ms: int = Field(default=0, ge=0, le=3600000)


class Join(Input):
    event_id: EventId = EVENT
    behavior: Behavior = Field(default_factory=Behavior)
    challenge_answer: str | None = Field(default=None, max_length=8)
    turnstile_token: str | None = Field(default=None, max_length=2048)


class HoldRequest(Input):
    event_id: EventId = EVENT
    seat_ids: list[SeatId] = Field(min_length=1, max_length=6)
    idempotency_key: Key


class PaymentRequest(Input):
    event_id: EventId = EVENT
    reservation_id: TokenId
    idempotency_key: Key
    mode: Literal["success", "decline", "timeout"] = "success"


class Recommend(Input):
    event_id: EventId = EVENT
    count: int = Field(ge=1, le=6)
    tier: Tier | None = None
    max_price: int | None = Field(default=None, ge=1, le=100000)
    preference: Literal["center", "aisle"] = "center"
