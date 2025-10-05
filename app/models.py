from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class Server(BaseModel):
    """SSH server configuration model."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    host: str
    port: int = 22
    username: str
    password: str | None = None
    key_path: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None

    def display(self) -> str:
        """Return formatted server display string."""
        auth = "key" if self.key_path else ("pwd" if self.password else "auto")
        return f"{self.name}  [{self.username}@{self.host}:{self.port} | {auth}]"
