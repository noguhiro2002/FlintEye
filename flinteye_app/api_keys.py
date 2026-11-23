"""Per-profile credentials for external REST clients."""
from contextlib import closing
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints


PREFIX = "fe_api_"
ApiKeyScope = Literal["read", "monitor"]
READ_ROUTES = frozenset({
    "/api/v1/status/monitoring", "/api/v1/viewer/cameras",
    "/api/v1/multiview/views", "/api/v1/multiview/status",
    "/api/v1/recordings/streams", "/api/v1/recordings",
})
CONTROL_ROUTES = frozenset(
    f"/api/v1/control/{action}" for action in ("start", "stop", "restart")
)


class NewApiKey(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    scope: ApiKeyScope


class ApiKeyStore:
    def __init__(self, root: Path):
        self.path = root / "api-keys.sqlite3"

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self):
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, scope TEXT NOT NULL,
                created_at INTEGER NOT NULL, revoked_at INTEGER,
                digest TEXT UNIQUE NOT NULL
            )""")

    def list(self) -> list[dict]:
        if not self.path.exists():
            return []
        self._initialize()
        with closing(self._connect()) as db:
            return [dict(row) for row in db.execute(
                "SELECT id, name, scope, created_at, revoked_at FROM api_keys ORDER BY created_at DESC, id"
            )]

    def create(self, payload: NewApiKey) -> dict:
        self._initialize()
        token = PREFIX + secrets.token_urlsafe(32)
        item = {
            "id": secrets.token_hex(16), "name": payload.name,
            "scope": payload.scope, "created_at": int(time.time()), "revoked_at": None,
        }
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO api_keys VALUES (:id, :name, :scope, :created_at, :revoked_at, :digest)",
                {**item, "digest": hashlib.sha256(token.encode("ascii")).hexdigest()},
            )
        return {**item, "token": token}

    def revoke(self, key_id: str) -> bool:
        if not self.path.exists():
            return False
        self._initialize()
        with closing(self._connect()) as db, db:
            return bool(db.execute(
                "UPDATE api_keys SET revoked_at = COALESCE(revoked_at, ?) WHERE id = ?",
                (int(time.time()), key_id),
            ).rowcount)

    def scope(self, token: str) -> ApiKeyScope | None:
        if not re.fullmatch(r"fe_api_[A-Za-z0-9_-]{43}", token) or not self.path.exists():
            return None
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT scope FROM api_keys WHERE digest = ? AND revoked_at IS NULL",
                (hashlib.sha256(token.encode("ascii")).hexdigest(),),
            ).fetchone()
        return row["scope"] if row else None
