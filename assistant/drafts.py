"""The assistant-owned draft queue, audit trail and one-attempt outbox."""

import json
import logging
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from assistant.eam import connect
from assistant.eam_contract import (
    EAM,
    PartQuantity,
    PartRequest,
    PartRequestLine,
    WorkOrder,
)

STALE_AFTER_DAYS = 7
SENDING_TIMEOUT = 60
MAX_ATTEMPTS = 3
logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('work_order', 'part_request')),
    payload TEXT NOT NULL,
    evidence TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('draft', 'approved', 'sending', 'sent', 'rejected', 'stale', 'send_failed')
    ),
    dedupe_key TEXT NOT NULL,
    external_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sending_since TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_draft
    ON drafts(dedupe_key) WHERE status = 'draft';
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    draft_id TEXT NOT NULL REFERENCES drafts(id),
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    at TEXT NOT NULL
);
"""


def draft_path_for(eam_path: Path) -> Path:
    name = (
        "assistant.sqlite"
        if eam_path.name == "eam.sqlite"
        else f"{eam_path.stem}.assistant.sqlite"
    )
    return eam_path.with_name(name)


def build_draft_db(path: Path) -> None:
    with TemporaryDirectory(dir=path.parent) as directory:
        fresh = Path(directory) / path.name
        with closing(connect(fresh)) as conn:
            conn.executescript(SCHEMA)
        fresh.replace(path)


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _audit(conn, draft_id: str, action: str, actor: str, at: str) -> None:
    conn.execute(
        "INSERT INTO audit (draft_id, action, actor, at) VALUES (?, ?, ?, ?)",
        (draft_id, action, actor, at),
    )


def _refresh_statuses(conn, now: datetime) -> None:
    at = _timestamp(now)
    stale_before = _timestamp(now - timedelta(days=STALE_AFTER_DAYS))
    stuck_before = _timestamp(now - timedelta(seconds=SENDING_TIMEOUT))
    stale = conn.execute(
        """UPDATE drafts SET status = 'stale', updated_at = ?
           WHERE status = 'draft' AND created_at < ? RETURNING id""",
        (at, stale_before),
    ).fetchall()
    recovered = conn.execute(
        """UPDATE drafts SET status = 'approved', sending_since = NULL, updated_at = ?
           WHERE status = 'sending' AND sending_since < ? RETURNING id""",
        (at, stuck_before),
    ).fetchall()
    for (draft_id,) in stale:
        _audit(conn, draft_id, "stale", "system", at)
    for (draft_id,) in recovered:
        _audit(conn, draft_id, "recovered", "system", at)


def _decode(row) -> dict:
    draft = dict(row)
    draft["payload"] = json.loads(draft["payload"])
    draft["evidence"] = json.loads(draft["evidence"])
    return draft


class DraftStore:
    def __init__(self, path: Path):
        self.path = path

    def save(
        self, payload: WorkOrder | PartRequest, problem_or_part: str, evidence: dict
    ) -> str:
        if isinstance(payload, WorkOrder):
            kind, prefix, id_field = "work_order", "WO", "wo_id"
        else:
            kind, prefix, id_field = "part_request", "PR", "request_id"
        key = json.dumps([payload.site, payload.asset_id, kind, problem_or_part])
        record = asdict(payload)
        with closing(connect(self.path)) as conn, conn:
            # Direct tool callers, including the eval runner, may seed only the EAM.
            conn.executescript(SCHEMA)
            now = _now()
            at = _timestamp(now)
            _refresh_statuses(conn, now)
            existing = conn.execute(
                "SELECT id FROM drafts WHERE dedupe_key = ? AND status = 'draft'",
                (key,),
            ).fetchone()
            draft_id = existing["id"] if existing else f"{prefix}-{uuid4().hex}"
            record[id_field] = draft_id
            conn.execute(
                """INSERT INTO drafts
                   (id, kind, payload, evidence, status, dedupe_key, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET payload = excluded.payload,
                   evidence = excluded.evidence, updated_at = excluded.updated_at""",
                (draft_id, kind, json.dumps(record), json.dumps(evidence), key, at, at),
            )
            _audit(
                conn, draft_id, "updated" if existing else "drafted", "assistant", at
            )
        return draft_id

    def review_queue(self) -> list[dict]:
        with closing(connect(self.path)) as conn, conn:
            _refresh_statuses(conn, _now())
            rows = conn.execute(
                "SELECT * FROM drafts WHERE status NOT IN ('sent', 'rejected') ORDER BY created_at, id"
            ).fetchall()
        drafts = [_decode(row) for row in rows]

        def priority(draft):
            evidence = draft["evidence"]
            rul = evidence["rul"]
            out_of_stock = any(
                sum(stores.values()) == 0 for stores in evidence["stock"].values()
            )
            return rul is None, rul or 0, not out_of_stock

        return sorted(drafts, key=priority)

    def get(self, draft_id: str) -> dict:
        with closing(connect(self.path)) as conn, conn:
            _refresh_statuses(conn, _now())
            row = conn.execute(
                "SELECT * FROM drafts WHERE id = ?", (draft_id,)
            ).fetchone()
        if row is None:
            raise KeyError(draft_id)
        return _decode(row)

    def reject(self, draft_id: str, actor: str) -> str:
        with closing(connect(self.path)) as conn, conn:
            now = _now()
            at = _timestamp(now)
            _refresh_statuses(conn, now)
            rejected = conn.execute(
                """UPDATE drafts SET status = 'rejected', updated_at = ?
                   WHERE id = ? AND status = 'draft'""",
                (at, draft_id),
            ).rowcount
            error = None
            if rejected:
                _audit(conn, draft_id, "rejected", actor, at)
            else:
                error = _decision_error(conn, draft_id, "no longer a draft")
        if error is not None:
            raise error
        return "rejected"

    def send(self, draft_id: str, actor: str, eam: EAM, *, retry: bool = False) -> str:
        with closing(connect(self.path)) as conn, conn:
            now = _now()
            at = _timestamp(now)
            _refresh_statuses(conn, now)
            error = None
            if not retry:
                approved = conn.execute(
                    """UPDATE drafts SET status = 'approved', updated_at = ?
                       WHERE id = ? AND status = 'draft'""",
                    (at, draft_id),
                ).rowcount
                if approved:
                    _audit(conn, draft_id, "approved", actor, at)
                else:
                    error = _decision_error(conn, draft_id, "no longer a draft")
            if error is None:
                claimed = conn.execute(
                    """UPDATE drafts SET status = 'sending', sending_since = ?, updated_at = ?
                       WHERE id = ? AND status IN ('approved', 'send_failed') RETURNING *""",
                    (at, at, draft_id),
                ).fetchone()
                if claimed is None:
                    error = _decision_error(conn, draft_id, "not ready to retry")
                else:
                    _audit(conn, draft_id, "sending", actor, at)
        if error is not None:
            raise error

        draft = _decode(claimed)
        external_id = None
        try:
            if retry:
                external_id = eam.find_by_reference(draft_id)
            if external_id is None:
                external_id = _submit(eam, draft)
            if not external_id:
                raise ValueError("EAM did not return a record ID")
        except Exception:
            external_id = None
            logger.exception("EAM send failed for draft %s", draft_id)

        sent = bool(external_id)
        attempts = draft["attempts"] + (not sent)
        status = (
            "sent"
            if sent
            else ("send_failed" if attempts >= MAX_ATTEMPTS else "approved")
        )
        with closing(connect(self.path)) as conn, conn:
            finished_at = _timestamp(_now())
            # A slow send may finish after recovery and a newer attempt has taken over.
            saved = conn.execute(
                """UPDATE drafts SET status = ?, external_id = ?, attempts = ?,
                   updated_at = ?, sending_since = NULL
                   WHERE id = ? AND status = 'sending' AND sending_since = ?""",
                (status, external_id or None, attempts, finished_at, draft_id, at),
            ).rowcount
            if not saved:
                return conn.execute(
                    "SELECT status FROM drafts WHERE id = ?", (draft_id,)
                ).fetchone()["status"]
            action = "attempt_failed" if status == "approved" else status
            _audit(conn, draft_id, action, "system", finished_at)
        return status


def _decision_error(conn, draft_id: str, message: str) -> KeyError | ValueError:
    if (
        conn.execute("SELECT 1 FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        is None
    ):
        return KeyError(draft_id)
    return ValueError(f"{draft_id} is {message}.")


def _submit(eam: EAM, draft: dict) -> str:
    payload = draft["payload"]
    if draft["kind"] == "work_order":
        order = WorkOrder(
            **{**payload, "parts": [PartQuantity(**line) for line in payload["parts"]]}
        )
        return eam.submit_work_request(order, draft["id"])
    request = PartRequest(
        **{**payload, "lines": [PartRequestLine(**line) for line in payload["lines"]]}
    )
    return eam.submit_part_request(request, draft["id"])
