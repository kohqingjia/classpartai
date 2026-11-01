"""Sessions, evidence runs, versioned drafts, recipients, approvals and deliveries.

Ported from Le Yong's participation/records.server.ts and assessments/records.server.ts,
on SQLite instead of Postgres. The rules are unchanged:
- every draft version is validated and re-audited; drafts are append-only
- editing a draft or a recipient invalidates every approval
- only the latest exact version can be approved, with an acknowledgement when issues remain
- nothing changes while a delivery is in flight
"""

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from classpartai.assessment import AssessmentInputs
from classpartai.evidence import AgentOutcome, EvidenceBundle
from classpartai.participation.schema import DraftContent, ModelAudit, Proposal
from classpartai.participation.validation import (
    EvidenceMap,
    Unprocessable,
    audit_draft,
    compose_draft,
    validate_proposal,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, course_title TEXT NOT NULL,
    inputs TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence_runs (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, question TEXT NOT NULL, status TEXT NOT NULL,
    stop_reason TEXT, progress TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS participation_runs (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, status TEXT NOT NULL, stop_reason TEXT,
    progress TEXT NOT NULL, manifest TEXT NOT NULL, deadline_at TEXT NOT NULL,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, version INTEGER NOT NULL, parent_id TEXT,
    origin TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE (session_id, version));
CREATE TABLE IF NOT EXISTS recipients (
    session_id TEXT NOT NULL, student_id TEXT NOT NULL, email TEXT NOT NULL,
    revision INTEGER NOT NULL, PRIMARY KEY (session_id, student_id));
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, approver TEXT NOT NULL, digest TEXT NOT NULL,
    acknowledgement TEXT NOT NULL, issue_ids TEXT NOT NULL, invalidated_at TEXT,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS deliveries (
    id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, approval_id TEXT NOT NULL,
    student_id TEXT NOT NULL, recipient TEXT NOT NULL, state TEXT NOT NULL,
    attempts INTEGER NOT NULL, updated_at TEXT NOT NULL, UNIQUE (draft_id, student_id));
CREATE TABLE IF NOT EXISTS delivery_attempts (
    id TEXT PRIMARY KEY, delivery_id TEXT NOT NULL, attempt INTEGER NOT NULL,
    state TEXT NOT NULL, reason TEXT, message_id TEXT, sent_to TEXT, started_at TEXT NOT NULL);
"""

EMAIL = re.compile(r"^[^@\s]{1,100}@[^@\s]{1,100}\.[^@\s]{2,}$")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return str(uuid.uuid4())


class Draft(BaseModel):
    id: str
    session_id: str
    version: int
    parent_id: str | None
    origin: str
    content: DraftContent
    created_at: str


class Records:
    def __init__(self, path: Path | str):
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.lock = threading.RLock()

    def tx(self):
        """A serialised write transaction (the original locked the session row)."""
        records = self

        class Tx:
            def __enter__(self):
                records.lock.acquire()
                records.db.execute("BEGIN IMMEDIATE")

            def __exit__(self, exc_type, *_):
                records.db.execute("ROLLBACK" if exc_type else "COMMIT")
                records.lock.release()

        return Tx()

    def _all(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def _one(self, sql, args=()):
        row = self.db.execute(sql, args).fetchone()
        return dict(row) if row else None

    # --- Sessions ---------------------------------------------------------------------------

    def create_session(self, inputs: AssessmentInputs) -> str:
        session_id = new_id()
        with self.tx():
            self.db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    inputs.sessionTitle,
                    inputs.courseTitle,
                    inputs.model_dump_json(),
                    now(),
                ),
            )
        return session_id

    def sessions(self) -> list[dict]:
        return self._all(
            "SELECT id, title, course_title, created_at FROM sessions ORDER BY created_at DESC"
        )

    def inputs(self, session_id: str) -> AssessmentInputs:
        row = self._one("SELECT inputs FROM sessions WHERE id = ?", (session_id,))
        if row is None:
            raise Unprocessable("Assessment session not found")
        return AssessmentInputs.model_validate_json(row["inputs"])

    # --- Evidence ---------------------------------------------------------------------------

    def save_evidence_run(self, session_id: str, question: str, outcome: AgentOutcome) -> str:
        run_id = new_id()
        progress = {
            **{k: v for k, v in vars(outcome.progress).items() if k != "bundle"},
            "bundle": outcome.progress.bundle.model_dump() if outcome.progress.bundle else None,
        }
        with self.tx():
            self.db.execute(
                "INSERT INTO evidence_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    session_id,
                    question,
                    outcome.status,
                    outcome.stopReason,
                    json.dumps(progress),
                    now(),
                ),
            )
        return run_id

    def evidence_runs(self, session_id: str) -> list[dict]:
        rows = self._all(
            "SELECT * FROM evidence_runs WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        )
        for r in rows:
            r["progress"] = json.loads(r["progress"])
        return rows

    def evidence_for(self, session_id: str) -> EvidenceMap:
        return [
            (r["id"], EvidenceBundle.model_validate(r["progress"]["bundle"]))
            for r in self.evidence_runs(session_id)
            if r["progress"]["bundle"] and r["status"] in ("completed", "needs_review")
        ]

    # --- Drafts -----------------------------------------------------------------------------

    def drafts(self, session_id: str, limit: int = 20) -> list[Draft]:
        rows = self._all(
            "SELECT * FROM drafts WHERE session_id = ? ORDER BY version DESC LIMIT ?",
            (session_id, limit),
        )
        return [
            Draft(**{**r, "content": DraftContent.model_validate_json(r["content"])}) for r in rows
        ]

    def latest_draft(self, session_id: str) -> Draft | None:
        drafts = self.drafts(session_id, 1)
        return drafts[0] if drafts else None

    def _refuse_sending(self, session_id: str) -> None:
        if self._one(
            "SELECT d.id FROM deliveries d JOIN drafts p ON p.id = d.draft_id"
            " WHERE p.session_id = ? AND d.state = 'sending' LIMIT 1",
            (session_id,),
        ):
            raise Unprocessable(
                "Wait for in-progress delivery to resolve before editing or approving"
            )

    def _invalidate(self, session_id: str) -> None:
        self.db.execute(
            "UPDATE approvals SET invalidated_at = ? WHERE invalidated_at IS NULL AND draft_id IN"
            " (SELECT id FROM drafts WHERE session_id = ?)",
            (now(), session_id),
        )

    def append_draft(
        self,
        session_id: str,
        proposal: Proposal,
        origin: str,
        note: str,
        expected_version: int | None = None,
        model_audit: ModelAudit | None = None,
    ) -> Draft:
        inputs = self.inputs(session_id)
        validate_proposal(proposal, inputs, self.evidence_for(session_id), session_id)
        with self.tx():
            self._refuse_sending(session_id)
            previous = self.latest_draft(session_id)
            if (
                expected_version is not None
                and (previous.version if previous else 0) != expected_version
            ):
                raise Unprocessable("Draft changed; reload before editing")
            self._invalidate(session_id)
            content = compose_draft(
                proposal, inputs, note, previous.content if previous else None, model_audit
            )
            draft_id = new_id()
            self.db.execute(
                "INSERT INTO drafts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    draft_id,
                    session_id,
                    (previous.version if previous else 0) + 1,
                    previous.id if previous else None,
                    origin,
                    content.model_dump_json(),
                    now(),
                ),
            )
        return self.latest_draft(session_id)

    @staticmethod
    def unassessed_proposal(inputs: AssessmentInputs) -> Proposal:
        return Proposal(
            findings=[
                {
                    "studentId": s.id,
                    "criterionId": c.id,
                    "status": "insufficient_evidence",
                    "score": None,
                    "turnIds": [],
                    "citations": [],
                    "justification": "Not yet assessed by the professor",
                    "limitations": ["Evidence review required"],
                }
                for s in inputs.roster
                for c in inputs.rubric.criteria
            ],
            feedback=[],
        )

    def create_professor_draft(self, session_id: str) -> Draft:
        if self.latest_draft(session_id):
            raise Unprocessable("A draft already exists; open the latest version")
        return self.append_draft(
            session_id,
            self.unassessed_proposal(self.inputs(session_id)),
            "professor",
            "Professor-created unassessed template, not a model assessment",
            0,
        )

    # --- Recipients and approval ------------------------------------------------------------

    def recipients(self, session_id: str) -> list[dict]:
        return self._all("SELECT * FROM recipients WHERE session_id = ?", (session_id,))

    def set_recipient(self, session_id: str, student_id: str, email: str) -> None:
        if not any(s.id == student_id for s in self.inputs(session_id).roster):
            raise Unprocessable("Unknown roster student")
        email = email.strip().lower()
        if not EMAIL.match(email):
            raise Unprocessable("Enter a valid email address")
        with self.tx():
            self._refuse_sending(session_id)
            current = self._one(
                "SELECT email FROM recipients WHERE session_id = ? AND student_id = ?",
                (session_id, student_id),
            )
            if current and current["email"] == email:
                return
            self.db.execute(
                "INSERT INTO recipients VALUES (?, ?, ?, 1) ON CONFLICT (session_id, student_id)"
                " DO UPDATE SET email = excluded.email, revision = revision + 1",
                (session_id, student_id, email),
            )
            self._invalidate(session_id)

    @staticmethod
    def approval_digest(content: DraftContent, recipients: list[dict]) -> str:
        pairs = sorted([r["student_id"], r["email"], r["revision"]] for r in recipients)
        canonical = json.dumps([content.model_dump(), pairs], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def approvals(self, session_id: str) -> list[dict]:
        rows = self._all(
            "SELECT a.* FROM approvals a JOIN drafts d ON d.id = a.draft_id WHERE d.session_id = ?"
            " ORDER BY a.created_at DESC",
            (session_id,),
        )
        for r in rows:
            r["issue_ids"] = json.loads(r["issue_ids"])
        return rows

    def active_approval(self, session_id: str) -> dict | None:
        latest = self.latest_draft(session_id)
        return next(
            (
                a
                for a in self.approvals(session_id)
                if latest and a["draft_id"] == latest.id and a["invalidated_at"] is None
            ),
            None,
        )

    def approve_draft(
        self, session_id: str, draft_id: str, acknowledge: bool, reason: str, approver: str
    ) -> dict:
        inputs = self.inputs(session_id)
        with self.tx():
            self._refuse_sending(session_id)
            draft = self.latest_draft(session_id)
            if draft is None or draft.id != draft_id:
                raise Unprocessable("Only the latest exact draft version can be approved")
            issues = [
                i
                for i in [*audit_draft(draft.content, inputs), *draft.content.audit.issues]
                if i.disposition == "open"
            ]
            if any(i.severity == "blocking" for i in issues):
                raise Unprocessable(
                    "Complete every roster student's findings and feedback before approval"
                )
            if issues and (not acknowledge or len(reason.strip()) < 10):
                raise Unprocessable(
                    "Explicit acknowledgement and a reason (10+ characters) are required for "
                    "unresolved issues"
                )
            recipients = self.recipients(session_id)
            if any(not any(r["student_id"] == s.id for r in recipients) for s in inputs.roster):
                raise Unprocessable("Set a recipient for every roster student before approval")
            digest = self.approval_digest(draft.content, recipients)
            current = self._one(
                "SELECT * FROM approvals WHERE draft_id = ? AND invalidated_at IS NULL", (draft.id,)
            )
            if current and current["digest"] == digest:
                return current
            self._invalidate(session_id)
            approval_id = new_id()
            self.db.execute(
                "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                (
                    approval_id,
                    draft.id,
                    approver,
                    digest,
                    reason,
                    json.dumps(sorted({i.id for i in issues})),
                    now(),
                ),
            )
        return self._one("SELECT * FROM approvals WHERE id = ?", (approval_id,))

    # --- Participation runs -----------------------------------------------------------------

    def start_run(self, session_id: str, manifest: dict, seconds: int) -> str:
        with self.tx():
            if self._one(
                "SELECT id FROM participation_runs WHERE session_id = ? AND status = 'running'",
                (session_id,),
            ):
                raise Unprocessable("A participation workflow is already active")
            run_id = new_id()
            deadline = (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(
                timespec="seconds"
            )
            self.db.execute(
                "INSERT INTO participation_runs VALUES (?, ?, 'running', NULL, '{}', ?, ?, ?)",
                (run_id, session_id, json.dumps(manifest), deadline, now()),
            )
        return run_id

    def update_run(
        self, run_id: str, progress: dict, status: str | None = None, stop_reason: str | None = None
    ) -> None:
        with self.lock:
            if status:
                self.db.execute(
                    "UPDATE participation_runs SET progress = ?, status = ?, stop_reason = ?"
                    " WHERE id = ? AND status = 'running'",
                    (json.dumps(progress), status, stop_reason, run_id),
                )
            else:
                self.db.execute(
                    "UPDATE participation_runs SET progress = ? WHERE id = ? AND status ="
                    " 'running'",
                    (json.dumps(progress), run_id),
                )

    def runs(self, session_id: str, limit: int = 10) -> list[dict]:
        rows = self._all(
            "SELECT * FROM participation_runs WHERE session_id = ? ORDER BY created_at DESC LIMIT"
            " ?",
            (session_id, limit),
        )
        for r in rows:
            r["progress"] = json.loads(r["progress"])
        return rows

    # --- Deliveries -------------------------------------------------------------------------

    def deliveries(self, session_id: str) -> list[dict]:
        return self._all(
            "SELECT d.* FROM deliveries d JOIN drafts p ON p.id = d.draft_id WHERE p.session_id = ?"
            " ORDER BY d.updated_at DESC",
            (session_id,),
        )

    def attempts(self, session_id: str) -> list[dict]:
        return self._all(
            "SELECT a.*, d.student_id FROM delivery_attempts a JOIN deliveries d ON d.id ="
            " a.delivery_id"
            " JOIN drafts p ON p.id = d.draft_id WHERE p.session_id = ? ORDER BY a.started_at DESC",
            (session_id,),
        )

    def review_state(self, session_id: str) -> None:
        """Resolve anything left hanging: a lost send is ambiguous (never blindly retried)."""
        cutoff = (datetime.now(UTC) - timedelta(seconds=30)).isoformat(timespec="seconds")
        with self.tx():
            stale = [
                r["id"]
                for r in self._all(
                    "SELECT d.id FROM deliveries d JOIN drafts p ON p.id = d.draft_id"
                    " WHERE p.session_id = ? AND d.state = 'sending' AND d.updated_at < ?",
                    (session_id, cutoff),
                )
            ]
            for delivery_id in stale:
                self.db.execute(
                    "UPDATE deliveries SET state = 'ambiguous', updated_at = ? WHERE id = ?",
                    (now(), delivery_id),
                )
                self.db.execute(
                    "UPDATE delivery_attempts SET state = 'ambiguous', reason = ? WHERE"
                    " delivery_id = ?"
                    " AND state = 'sending'",
                    (
                        "Request interrupted; acceptance unknown; automatic retry prohibited",
                        delivery_id,
                    ),
                )
            self.db.execute(
                "UPDATE participation_runs SET status = 'failed', stop_reason ="
                " 'interrupted_or_deadline'"
                " WHERE session_id = ? AND status = 'running' AND deadline_at <= ?",
                (session_id, now()),
            )
