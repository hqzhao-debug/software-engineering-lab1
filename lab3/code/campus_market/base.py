"""Transactional access, authentication, idempotency, and safe audit logging."""

import hashlib
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import db
from .models import DomainError, json_text, required


class BaseService:
    """Shared infrastructure for the UML application service modules."""

    def __init__(
        self,
        db_path,
        email_domain="campus.example",
        clock=time.time,
        mail_mode="local",
        outbox=None,
    ):
        self.db_path = Path(db_path)
        self.email_domain = email_domain.strip().lower().lstrip("@")
        self.clock = clock
        self.mail_mode = mail_mode
        self.outbox = Path(outbox) if outbox else self.db_path.parent / "outbox"
        if mail_mode not in ("local", "smtp"):
            raise ValueError("mail_mode must be local or smtp")
        if not self.email_domain or "." not in self.email_domain:
            raise ValueError("email_domain must be an explicit domain")
        db.initialize(self.db_path)

    def _now(self):
        return float(self.clock())

    @staticmethod
    def _new_id():
        return uuid.uuid4().hex

    def _connect(self):
        return db.connect(self.db_path)

    @staticmethod
    def _token_hash(token):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _one(connection, table, identifier):
        # Table names are internal constants, never accepted from a CLI flag.
        allowed = {
            "accounts",
            "products",
            "submitted_versions",
            "review_submissions",
            "reservations",
            "violations",
            "bans",
            "images",
            "audit_logs",
        }
        if table not in allowed:
            raise ValueError("Unsupported internal table")
        row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (identifier,)).fetchone()
        if row is None:
            raise DomainError("NOT_FOUND", "记录不存在或不可访问")
        return dict(row)

    def _authenticate(self, connection, token, role=None, active=True):
        if not isinstance(token, str) or not token:
            raise DomainError("AUTH", "请先登录")
        digest = self._token_hash(token)
        session = connection.execute(
            "SELECT * FROM sessions WHERE token_hash = ?", (digest,)
        ).fetchone()
        if session is None or session["revoked_at"] is not None:
            raise DomainError("AUTH", "会话无效，请重新登录")
        if self._now() - session["last_activity"] >= 1800:
            raise DomainError("SESSION_EXPIRED", "会话闲置已满 30 分钟，请重新登录")
        account = self._one(connection, "accounts", session["account_id"])
        if account["status"] != "NORMAL" or not account["verified"]:
            raise DomainError("ACCOUNT_RESTRICTED", "账号当前不能执行操作")
        if role is not None and account["role"] != role:
            raise DomainError("FORBIDDEN", "当前角色没有此操作权限")
        if active:
            connection.execute(
                "UPDATE sessions SET last_activity = ? WHERE token_hash = ?",
                (self._now(), digest),
            )
        return account

    def _identify(self, connection, token):
        """Identify a failed caller without granting any authorization."""
        if not isinstance(token, str) or not token:
            return None
        row = connection.execute(
            "SELECT a.* FROM accounts a JOIN sessions s ON a.id=s.account_id WHERE s.token_hash=?",
            (self._token_hash(token),),
        ).fetchone()
        return dict(row) if row else None

    def _audit(
        self,
        connection,
        actor,
        operation,
        object_id=None,
        before=None,
        after=None,
        result="SUCCESS",
        reason="",
        details=None,
        private_owner=None,
    ):
        safe_details = details or {}
        prohibited = {"password", "password_hash", "token", "verification_token"}
        if prohibited.intersection(safe_details):
            raise ValueError("Sensitive fields cannot be audited")
        connection.execute(
            "INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self._new_id(),
                actor["id"] if actor else None,
                actor["role"] if actor else None,
                operation,
                object_id,
                before,
                after,
                result,
                reason,
                json_text(safe_details),
                private_owner,
                self._now(),
            ),
        )

    def _failure(self, token, operation, object_id, error):
        """Best-effort failure log after rollback; never modify target business data."""
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            actor = self._identify(connection, token)
            self._audit(
                connection, actor, operation, object_id, result="FAILURE", reason=error.message
            )
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
        finally:
            connection.close()

    @contextmanager
    def _atomic(self, token, operation, object_id=None, role=None):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            actor = self._authenticate(connection, token, role)
            yield connection, actor
            connection.commit()
        except DomainError as error:
            connection.rollback()
            self._failure(token, operation, object_id, error)
            raise
        except sqlite3.Error as error:
            connection.rollback()
            safe = DomainError("STORAGE", "数据未保存，请刷新状态后重试")
            self._failure(token, operation, object_id, safe)
            raise safe from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def _read(self, token, role=None, active=True):
        # Active reads update this session only. The same lock makes auth current.
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            actor = self._authenticate(connection, token, role, active)
            yield connection, actor
            connection.commit()
        except DomainError as error:
            connection.rollback()
            self._failure(token, "read", None, error)
            raise
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _digest(payload):
        return hashlib.sha256(json_text(payload).encode("utf-8")).hexdigest()

    def _idempotent(self, connection, actor, operation, key, payload):
        key = required(key, "请求键")
        row = connection.execute(
            "SELECT * FROM idempotency WHERE actor_id=? AND operation=? AND request_key=?",
            (actor["id"], operation, key),
        ).fetchone()
        if row is None:
            return None
        if row["digest"] != self._digest(payload):
            raise DomainError("KEY_CONFLICT", "同一请求键不能用于不同内容，请使用新请求键")
        self._audit(connection, actor, operation, row["resource_id"], result="REPLAY")
        return row["resource_id"]

    def _remember(self, connection, actor, operation, key, payload, resource_id):
        connection.execute(
            "INSERT INTO idempotency VALUES (?,?,?,?,?,?)",
            (actor["id"], operation, key.strip(), self._digest(payload), resource_id, self._now()),
        )
