"""New Playground authorization identity; historical experiment approvals are unrelated."""

import hashlib
import json
import stat
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[4]
MODEL = "deepseek-flash"
MODEL_REVISION = "DeepSeek-V4.1-Flash-1017"
INPUT_BOUND = 1_048_576
PRICE_SOURCE = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"


class PlaygroundRejected(ValueError):
    pass


def source_fingerprint():
    files = []
    for directory in ["backend/src", "backend/migrations", "frontend/src", "fixtures/policies"]:
        files.extend(
            p
            for p in (ROOT / directory).rglob("*")
            if p.is_file() and p.suffix in {".py", ".ts", ".tsx", ".css", ".json"}
        )
    files.extend(
        ROOT / p
        for p in [
            "backend/uv.lock",
            "frontend/package-lock.json",
            "backend/pyproject.toml",
            "scripts/ci/Playground.Dockerfile",
            "compose.ci.yaml",
            "frontend/vite.config.ts",
            "evals/data/embedding_manifest.json",
        ]
    )
    files.extend(p for p in (ROOT / "scripts").glob("playground*.py"))
    files.extend(ROOT.glob("compose.playground*.yaml"))
    data = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class PlaygroundPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool = False
    evidence_mode: Literal["LIVE_DEEPSEEK", "MOCK_TRANSPORT"] = "LIVE_DEEPSEEK"
    session_id: UUID
    environment_id: UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_id: Literal["deepseek-flash"] = MODEL
    price_checked_at: datetime
    price_source: Literal["https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"] = PRICE_SOURCE
    input_cny_per_million: Decimal = Field(default=Decimal("2"), ge=2, le=2)
    output_cny_per_million: Decimal = Field(default=Decimal("8"), ge=8, le=8)
    max_model_calls: int = Field(default=30, ge=1, le=100, strict=True)
    max_cost_cny: Decimal = Field(default=Decimal("5"), gt=0, le=5)
    max_wall_seconds: int = Field(default=1200, ge=1, le=1200, strict=True)
    max_input_tokens: int = Field(default=4_194_304, ge=1, le=12_582_912, strict=True)
    max_output_tokens: int = Field(default=24000, ge=1, le=120000, strict=True)

    @property
    def binding(self):
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def validate_current(self):
        if not self.enabled:
            raise PlaygroundRejected("LIVE_DISABLED")
        if self.price_checked_at.tzinfo is None:
            raise PlaygroundRejected("PRICE_EXPIRED")
        age = (datetime.now(UTC) - self.price_checked_at).total_seconds()
        if not 0 <= age <= 86400:
            raise PlaygroundRejected("PRICE_EXPIRED")
        if self.source_sha256 != source_fingerprint():
            raise PlaygroundRejected("SOURCE_MISMATCH")


def validate_approval(policy, path):
    policy.validate_current()
    if policy.evidence_mode != "LIVE_DEEPSEEK":
        raise PlaygroundRejected("MOCK_IS_NOT_LIVE_AUTHORIZATION")
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise PlaygroundRejected("APPROVAL_REQUIRED")
    try:
        if stat.S_IMODE(path.stat().st_mode) & 0o077 or path.stat().st_size > 4096:
            raise ValueError()
        data = json.loads(path.read_text())
        expected = {"purpose", "approved", "session_id", "policy_sha256", "approval_reference"}
        if (
            set(data) != expected
            or data["purpose"] != "agentmall-live-playground-v1"
            or data["approved"] is not True
            or data["session_id"] != str(policy.session_id)
            or data["policy_sha256"] != policy.binding
        ):
            raise ValueError()
        ref = data["approval_reference"]
        if (
            not isinstance(ref, str)
            or len(ref) < 12
            or len(ref) > 500
            or any(x in ref.lower() for x in ["placeholder", "example", "待批准", "t12-", "填写"])
        ):
            raise ValueError()
    except (ValueError, TypeError, KeyError, OSError):
        raise PlaygroundRejected("APPROVAL_REQUIRED") from None
    return hashlib.sha256(path.read_bytes()).hexdigest()
