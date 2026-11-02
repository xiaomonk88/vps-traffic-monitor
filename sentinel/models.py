from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(StrictModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)
    setup_token: str = ""


class NodeInput(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    group_name: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=500)


class Enrollment(StrictModel):
    token: str = Field(max_length=200)
    hostname: str = Field(max_length=120)


class Sample(StrictModel):
    seq: int = Field(ge=1, le=2**53-1)
    start: float
    end: float
    rx: int = Field(ge=0, le=2**63-1)
    tx: int = Field(ge=0, le=2**63-1)
    quality: str = Field(default="ok", pattern=r"^(ok|reboot|gap|counter_reset)$")


class AgentMeta(StrictModel):
    hostname: str = Field(default="", max_length=120)
    os: str = Field(default="", max_length=120)
    version: str = Field(default="", max_length=40)
    interface: str = Field(default="", max_length=120)
    interfaces: list[str] = Field(default_factory=list, max_length=100)
    boot_id: str = Field(default="", max_length=120)
    connection: str = Field(default="direct", pattern="^(direct|socks5)$")
    queue: int = Field(default=0, ge=0)
    error: str = Field(default="", max_length=300)
    data_gap: bool = False


class Report(StrictModel):
    epoch: str = Field(pattern=r"^[a-zA-Z0-9-]{8,80}$")
    samples: list[Sample] = Field(default_factory=list, max_length=500)
    meta: AgentMeta = Field(default_factory=AgentMeta)
    checkpoint: str | None = Field(default=None, max_length=80)
    checkpoint_seq: int | None = None


class Calibration(StrictModel):
    checkpoint_id: str
    remaining_bytes: int = Field(ge=0, le=10**17)
    note: str = Field(default="", max_length=300)
