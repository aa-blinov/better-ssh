from __future__ import annotations

import uuid
from datetime import datetime

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
    certificate_path: str | None = None
    favorite: bool = False
    use_count: int = 0
    last_used_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None

    def display(self) -> str:
        """Return formatted server display string."""
        if self.certificate_path:
            auth = "cert"
        elif self.key_path:
            auth = "key"
        elif self.password:
            auth = "pwd"
        else:
            auth = "auto"
        prefix = "[pin] " if self.favorite else ""
        return f"{prefix}{self.name}  [{self.username}@{self.host}:{self.port} | {auth}]"
