from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Short = Annotated[str, Field(min_length=1, max_length=256)]


class SignatoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Short
    role: Short
    organisation: Short
    order: Annotated[int, Field(ge=1)]
    sealRequired: bool = False


class MouCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    programmeId: Short
    reference: Short
    ampRecordId: Short | None = None
    signatories: Annotated[list[SignatoryIn], Field(min_length=1, max_length=20)]


class UgpassEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: Short
    outcome: Literal["APPROVED", "DECLINED", "EXPIRED"]
    certificateRef: str | None = Field(default=None, max_length=256)
    signedAt: datetime | None = None
