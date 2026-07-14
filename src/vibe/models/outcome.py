"""Low-sensitivity task outcome feedback."""

from pydantic import Field

from vibe.models.base import VersionedModel


class TaskOutcome(VersionedModel):
    """The deliberately small outcome schema safe for local calibration data."""

    task_type: str = Field(min_length=1)
    workflow: str = Field(min_length=1)
    capabilities_used: tuple[str, ...] = ()
    verification_passed: bool
    user_rework: bool
    unused_recommendations: tuple[str, ...] = ()
