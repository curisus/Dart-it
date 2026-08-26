from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class StrictExcelArguments(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
    )
