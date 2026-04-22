from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Forward(BaseModel):
    """Port-forwarding spec, mapped to OpenSSH -L / -R / -D.

    - type="local"  => ssh -L [bind:]local_port:remote_host:remote_port
    - type="remote" => ssh -R [bind:]local_port:remote_host:remote_port
    - type="dynamic" => ssh -D [bind:]local_port  (SOCKS)
    """

    type: Literal["local", "remote", "dynamic"]
    bind_host: str | None = None
    local_port: int
    remote_host: str | None = None
    remote_port: int | None = None

    def to_ssh_spec(self) -> str:
        """Render the `-L`/`-R`/`-D` argument string for OpenSSH."""
        prefix = f"{self.bind_host}:" if self.bind_host else ""
        if self.type == "dynamic":
            return f"{prefix}{self.local_port}"
        return f"{prefix}{self.local_port}:{self.remote_host}:{self.remote_port}"

    def display(self) -> str:
        """Short human-readable representation for tables and panels.

        Kept to ASCII so Rich can render it on legacy Windows terminals
        (cp1251 / cp866) without raising UnicodeEncodeError.
        """
        letter = {"local": "L", "remote": "R", "dynamic": "D"}[self.type]
        bind = f"{self.bind_host}:" if self.bind_host else ""
        if self.type == "dynamic":
            return f"{letter} {bind}{self.local_port}"
        return f"{letter} {bind}{self.local_port} -> {self.remote_host}:{self.remote_port}"


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
    jump_host: str | None = None  # name of another saved server to use as ProxyJump
    keep_alive_interval: int | None = None  # seconds; None disables ServerAliveInterval
    forwards: list[Forward] = Field(default_factory=list)

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
        via = f" via {self.jump_host}" if self.jump_host else ""
        return f"{prefix}{self.name}  [{self.username}@{self.host}:{self.port} | {auth}]{via}"
