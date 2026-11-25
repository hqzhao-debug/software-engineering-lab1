"""Account creation, email verification, password checks, and sessions."""

import hashlib
import hmac
import os
import re
import secrets
import smtplib
import sqlite3
from email.message import EmailMessage

from .models import DomainError, json_text, required


PASSWORD_ITERATIONS = 600_000


def password_hash(password):
    """Use a per-account random salt and PBKDF2-HMAC-SHA256."""
    required(password, "密码")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PASSWORD_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"


def check_password(password, encoded):
    """Compare derived values in constant time, with no plaintext persistence."""
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not isinstance(password, str):
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
        ).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def public_account(account):
    """Private account details are returned only to self or authorized admins."""
    fields = ("id", "username", "email", "campus_id", "role", "status", "verified", "created_at")
    return {key: account[key] for key in fields}


class AccountMixin:
    """Identity service; registration never accepts a client-selected role."""

    def _account_input(self, username, email, campus_id, password):
        username = required(username, "用户名")
        email = required(email, "校园邮箱").lower()
        campus_id = required(campus_id, "学号/工号")
        required(password, "密码")
        if "@" in username:
            raise DomainError("VALIDATION", "用户名不能包含 @，避免与邮箱登录混淆")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+", email):
            raise DomainError("VALIDATION", "邮箱格式不正确")
        if email.rsplit("@", 1)[1] != self.email_domain:
            raise DomainError("VALIDATION", f"请使用 @{self.email_domain} 校园邮箱")
        return username, email, campus_id

    def _new_account(self, connection, username, email, campus_id, password, role):
        username, email, campus_id = self._account_input(username, email, campus_id, password)
        identifier = self._new_id()
        try:
            connection.execute(
                "INSERT INTO accounts (id,username,email,campus_id,password_hash,role,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (identifier, username, email, campus_id, password_hash(password), role, self._now()),
            )
        except sqlite3.IntegrityError as error:
            raise DomainError("DUPLICATE", "用户名、邮箱或学号/工号已被使用") from error
        verification_token = secrets.token_urlsafe(32)
        connection.execute(
            "INSERT INTO verification_tokens VALUES (?,?,?,NULL)",
            (self._token_hash(verification_token), identifier, self._now()),
        )
        return self._one(connection, "accounts", identifier), verification_token

    def _deliver_verification(self, account, token):
        """Local outbox is an explicit development adapter, not proof of email ownership."""
        if self.mail_mode == "local":
            self.outbox.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.outbox.chmod(0o700)
            destination = self.outbox / f"{account['id']}.json"
            payload = {
                "account_id": account["id"], "email": account["email"],
                "verification_token": token, "created_at": self._now(),
                "mode": "local-development-only",
            }
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(json_text(payload))
            destination.chmod(0o600)
            return
        host = os.environ.get("CAMPUS_SMTP_HOST")
        sender = os.environ.get("CAMPUS_SMTP_FROM")
        if not host or not sender:
            raise DomainError("MAIL", "SMTP 未配置；账号尚未创建，请配置后重试")
        message = EmailMessage()
        message["From"] = sender
        message["To"] = account["email"]
        message["Subject"] = "校园循物：注册邮箱验证"
        message.set_content(f"请在校园循物程序中输入以下验证码：\n{token}\n请勿转发此验证码。")
        try:
            with smtplib.SMTP_SSL(host, int(os.environ.get("CAMPUS_SMTP_PORT", "465")),
                                  timeout=10) as smtp:
                username = os.environ.get("CAMPUS_SMTP_USER")
                if username:
                    smtp.login(username, os.environ.get("CAMPUS_SMTP_PASSWORD", ""))
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException, ValueError) as error:
            raise DomainError("MAIL", "验证邮件发送失败；账号尚未创建，请稍后重试") from error

    def bootstrap_admin(self, username, email, campus_id, password):
        """Create the first administrator only in an entirely empty database."""
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]:
                raise DomainError("FORBIDDEN", "仅空数据库允许初始化首个管理员")
            account, token = self._new_account(connection, username, email, campus_id, password, "ADMIN")
            self._audit(connection, None, "bootstrap_admin", account["id"], after="UNVERIFIED")
            self._deliver_verification(account, token)
            connection.commit()
            return {"account": public_account(account), "verification_token": token}
        except DomainError as error:
            connection.rollback()
            self._failure(None, "bootstrap_admin", None, error)
            raise
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def register(self, username, email, campus_id, password):
        """Create a regular account, awaiting explicit email verification."""
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            account, token = self._new_account(connection, username, email, campus_id, password, "USER")
            self._audit(connection, account, "register", account["id"], after="UNVERIFIED")
            self._deliver_verification(account, token)
            connection.commit()
            return {"account": public_account(account), "delivery": self.mail_mode}
        except DomainError as error:
            connection.rollback()
            self._failure(None, "register", None, error)
            raise
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_admin(self, token, username, email, campus_id, password):
        """An existing administrator may create, but never promote, an account."""
        with self._atomic(token, "create_admin", role="ADMIN") as (connection, actor):
            account, verification = self._new_account(
                connection, username, email, campus_id, password, "ADMIN"
            )
            self._audit(connection, actor, "create_admin", account["id"], after="UNVERIFIED")
            self._deliver_verification(account, verification)
            return {"account": public_account(account), "delivery": self.mail_mode}

    def verify_email(self, verification_token):
        """Consume a random token once; no undocumented expiry is assumed."""
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            verification_token = required(verification_token, "验证码")
            digest = self._token_hash(verification_token)
            record = connection.execute(
                "SELECT * FROM verification_tokens WHERE token_hash=?", (digest,)
            ).fetchone()
            if not record or record["used_at"] is not None:
                raise DomainError("VERIFICATION", "验证码无效或已经使用")
            account = self._one(connection, "accounts", record["account_id"])
            connection.execute("UPDATE accounts SET verified=1 WHERE id=?", (account["id"],))
            connection.execute("UPDATE verification_tokens SET used_at=? WHERE token_hash=?",
                               (self._now(), digest))
            self._audit(connection, account, "verify_email", account["id"],
                        before="UNVERIFIED", after="VERIFIED")
            connection.commit()
            account["verified"] = 1
            return public_account(account)
        except DomainError as error:
            connection.rollback()
            self._failure(None, "verify_email", None, error)
            raise
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def login(self, identifier, password):
        """Persist failed-password counters even when the login is rejected."""
        connection = self._connect()
        failure = None
        response = None
        try:
            connection.execute("BEGIN IMMEDIATE")
            identifier = required(identifier, "用户名或邮箱")
            row = connection.execute(
                "SELECT * FROM accounts WHERE username=? COLLATE NOCASE OR email=? COLLATE NOCASE",
                (identifier, identifier),
            ).fetchone()
            account = dict(row) if row else None
            if account is None:
                failure = DomainError("CREDENTIALS", "用户名或密码错误")
            elif account["status"] != "NORMAL":
                failure = DomainError("ACCOUNT_RESTRICTED", "账号已被封禁")
            elif account["locked_until"] and self._now() < account["locked_until"]:
                failure = DomainError("LOCKED", "连续密码错误，账号暂时锁定 15 分钟")
            else:
                if account["locked_until"]:
                    account["failed_count"] = 0
                    connection.execute(
                        "UPDATE accounts SET failed_count=0,locked_until=NULL WHERE id=?",
                        (account["id"],),
                    )
                if not check_password(password, account["password_hash"]):
                    failures = account["failed_count"] + 1
                    until = self._now() + 900 if failures >= 5 else None
                    connection.execute(
                        "UPDATE accounts SET failed_count=?,locked_until=? WHERE id=?",
                        (failures, until, account["id"]),
                    )
                    failure = DomainError("CREDENTIALS", "用户名或密码错误")
                elif not account["verified"]:
                    connection.execute("UPDATE accounts SET failed_count=0 WHERE id=?", (account["id"],))
                    failure = DomainError("UNVERIFIED", "请先完成校园邮箱验证")
                else:
                    connection.execute(
                        "UPDATE accounts SET failed_count=0,locked_until=NULL WHERE id=?",
                        (account["id"],),
                    )
                    token = secrets.token_urlsafe(32)
                    connection.execute("INSERT INTO sessions VALUES (?,?,?,?,NULL)",
                                       (self._token_hash(token), account["id"], self._now(), self._now()))
                    response = {"token": token, "account": public_account(account)}
            self._audit(connection, account, "login", account["id"] if account else None,
                        result="FAILURE" if failure else "SUCCESS",
                        reason=failure.message if failure else "")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        if failure:
            raise failure
        return response

    def logout(self, token):
        """Revoke the current session without affecting another device."""
        with self._atomic(token, "logout") as (connection, actor):
            connection.execute("UPDATE sessions SET revoked_at=? WHERE token_hash=?",
                               (self._now(), self._token_hash(token)))
            self._audit(connection, actor, "logout", actor["id"])
            return {"logged_out": True}

    def whoami(self, token, active=True):
        """Read self; background callers can explicitly avoid extending idle time."""
        with self._read(token, active=active) as (_, actor):
            return public_account(actor)

    def list_accounts(self, token):
        """Administrative account lookup excludes secrets and current drafts."""
        with self._read(token, role="ADMIN") as (connection, _):
            return [public_account(dict(row)) for row in connection.execute(
                "SELECT * FROM accounts ORDER BY created_at,id"
            )]
