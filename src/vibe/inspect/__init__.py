"""Deterministic repository inspection primitives."""

from vibe.inspect.git import GitState, inspect_git
from vibe.inspect.repository import inspect_repository
from vibe.inspect.stack import inspect_stack

__all__ = ["GitState", "inspect_git", "inspect_repository", "inspect_stack"]
