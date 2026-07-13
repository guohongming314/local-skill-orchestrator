from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict


class VersionedModel(BaseModel):
    """Strict project-owned model with an explicit migration boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    CURRENT_SCHEMA_VERSION: ClassVar[str] = "1"
    schema_version: str = CURRENT_SCHEMA_VERSION

    def model_post_init(self, __context: Any) -> None:
        if self.schema_version != self.CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {self.schema_version!r}; "
                f"expected {self.CURRENT_SCHEMA_VERSION!r}"
            )

    @classmethod
    def migrate(cls, data: dict[str, Any]) -> Self:
        """Validate current data; future versions can transform older payloads here."""
        return cls.model_validate(data)

