"""Loopback-only browser interface backed by the existing application services."""

from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import inspect
import json
import secrets
import sqlite3
import tempfile
import threading
import time
import webbrowser
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from .models import CATEGORIES, CONDITIONS, DomainError
from .service import Market

MAX_BODY_BYTES = 7 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
SERVICE_ACTIONS = {
    "me": "whoami",
    "accounts": "list_accounts",
    "create-admin": "create_admin",
    "products": "list_products",
    "product": "get_product",
    "save-draft": "save_draft",
    "delete-draft": "delete_draft",
    "submit": "submit_product",
    "withdraw": "withdraw_product",
    "off-shelf": "off_shelf",
    "history": "product_history",
    "reserve": "reserve",
    "reservations": "list_reservations",
    "reservation": "get_reservation",
    "confirm": "confirm",
    "reject": "reject",
    "cancel": "cancel",
    "complete": "complete",
    "review": "review",
    "violation": "mark_violation",
    "ban": "ban_account",
    "unban": "unban_account",
    "statistics": "statistics",
    "logs": "list_logs",
}


class MarketHTTPServer(ThreadingHTTPServer):
    """Isolated GUI adapter; the business layer remains the authorization boundary."""

    daemon_threads = True

    def __init__(self, address, market, demo_credentials=None):
        if address[0] != "127.0.0.1":
            raise ValueError("The coursework GUI binds only to 127.0.0.1")
        self.market = market
        self.demo_credentials = demo_credentials
        self.csrf = secrets.token_urlsafe(32)
        self.pending_verifications = {}
        self.verification_lock = threading.Lock()
        super().__init__(address, MarketHandler)
        self.base_url = f"http://127.0.0.1:{self.server_port}"
        self.expected_host = f"127.0.0.1:{self.server_port}"
        self.session_cookie = f"campus_session_{self.server_port}"
        self.verification_cookie = f"campus_verify_{self.server_port}"


class MarketHandler(BaseHTTPRequestHandler):
    """Explicit routes only, with Host, Origin, CSRF, and input-size protection."""

    server: MarketHTTPServer
    server_version = "CampusMarket/1.1"
    sys_version = ""

    def log_message(self, format, *args):
        # Request payloads and query strings may contain private input. UI errors
        # are rendered to the caller; business audits are handled by Market.
        return

    def _headers(self, status, mime, length, cookies=()):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'",
        )
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _json(self, status, payload, cookies=()):
        content = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(content), cookies)
        self.wfile.write(content)

    def _success(self, data, cookies=()):
        self._json(HTTPStatus.OK, {"ok": True, "data": data}, cookies)

    def _error(self, error, status=None):
        if status is None:
            if error.code in {"AUTH", "SESSION_EXPIRED", "CREDENTIALS", "UNVERIFIED"}:
                status = HTTPStatus.UNAUTHORIZED
            elif error.code in {"FORBIDDEN", "ORIGIN", "CSRF", "HOST"}:
                status = HTTPStatus.FORBIDDEN
            elif error.code == "NOT_FOUND":
                status = HTTPStatus.NOT_FOUND
            elif error.code in {"STALE", "STALE_VERSION", "KEY_CONFLICT", "DUPLICATE"}:
                status = HTTPStatus.CONFLICT
            else:
                status = HTTPStatus.BAD_REQUEST
        self._json(status, {"ok": False, "error": {"code": error.code, "message": error.message}})

    def _check_host(self):
        if self.headers.get("Host") != self.server.expected_host:
            raise DomainError("HOST", "仅允许从本机应用地址访问")

    def _check_mutation(self):
        self._check_host()
        if self.headers.get("Origin") != self.server.base_url:
            raise DomainError("ORIGIN", "请求来源不正确，请从应用页面重新操作")
        supplied = self.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(supplied.encode("utf-8"), self.server.csrf.encode("utf-8")):
            raise DomainError("CSRF", "页面已失效，请刷新后重试")

    def _cookies(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return SimpleCookie()
        return cookie

    def _token(self):
        item = self._cookies().get(self.server.session_cookie)
        return item.value if item else None

    @staticmethod
    def _cookie(name, value, remove=False):
        cookie = SimpleCookie()
        cookie[name] = value
        cookie[name]["path"] = "/"
        cookie[name]["httponly"] = True
        cookie[name]["samesite"] = "Strict"
        if remove:
            cookie[name]["max-age"] = 0
        return cookie[name].OutputString()

    def _body(self):
        if self.headers.get_content_type() != "application/json":
            raise DomainError("CONTENT_TYPE", "请求须使用 JSON 格式")
        if self.headers.get("Transfer-Encoding"):
            raise DomainError("VALIDATION", "不支持分块请求")
        try:
            size = int(self.headers.get("Content-Length", "-1"))
        except ValueError as error:
            raise DomainError("VALIDATION", "请求长度无效") from error
        if size < 0 or size > MAX_BODY_BYTES:
            raise DomainError("SIZE", "请求过大或长度无效")
        try:
            data = json.loads(
                self.rfile.read(size).decode("utf-8"),
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite")),
            )
        except (UnicodeError, ValueError) as error:
            raise DomainError("VALIDATION", "请求内容不是有效 JSON") from error
        if not isinstance(data, dict):
            raise DomainError("VALIDATION", "请求内容须为 JSON 对象")
        return data

    @staticmethod
    def _invoke(method, data, **injected):
        if any(key in data for key in ("token", "role", "active")):
            raise DomainError("VALIDATION", "请求包含不允许的字段")
        values = dict(data, **injected)
        try:
            inspect.signature(method).bind(**values)
        except TypeError as error:
            raise DomainError("VALIDATION", "请检查必填字段和参数名称") from error
        return method(**values)

    def do_GET(self):
        """Read the application shell, current identity, or an authorized image."""
        try:
            self._check_host()
            path = urlsplit(self.path).path
            if path == "/api/context":
                account = None
                cookies = []
                token = self._token()
                if token:
                    try:
                        account = self.server.market.whoami(token, active=False)
                    except DomainError:
                        cookies.append(self._cookie(self.server.session_cookie, "", True))
                self._success(
                    {
                        "account": account,
                        "demo": self.server.demo_credentials is not None,
                        "csrf": self.server.csrf,
                        "categories": list(CATEGORIES),
                        "conditions": list(CONDITIONS),
                        "email_domain": self.server.market.email_domain,
                    },
                    cookies,
                )
            elif path in STATIC_FILES:
                name, mime = STATIC_FILES[path]
                content = files("campus_market").joinpath("web", name).read_bytes()
                self._headers(HTTPStatus.OK, mime, len(content))
                self.wfile.write(content)
            elif path.startswith("/api/image/"):
                image_id = path.removeprefix("/api/image/")
                image = self.server.market.read_image(image_id, self._token())
                self._headers(HTTPStatus.OK, image["mime"], len(image["data"]))
                self.wfile.write(image["data"])
            else:
                raise DomainError("NOT_FOUND", "页面不存在")
        except DomainError as error:
            self._error(error)
        except (OSError, sqlite3.Error, ValueError):
            self._error(DomainError("SERVER", "页面暂时不可用，请稍后重试"), 500)

    def _register(self, data):
        result = self._invoke(self.server.market.register, data)
        cookies = []
        if self.server.demo_credentials is not None:
            challenge = secrets.token_urlsafe(32)
            with self.server.verification_lock:
                # Keep only recent challenges; never persist this browser grant.
                self.server.pending_verifications = {
                    key: value
                    for key, value in self.server.pending_verifications.items()
                    if time.monotonic() - value[1] < 900
                }
                self.server.pending_verifications[challenge] = (
                    result["account"]["id"],
                    time.monotonic(),
                )
            cookies.append(self._cookie(self.server.verification_cookie, challenge))
        return result, cookies

    def _demo_verify(self, data):
        if self.server.demo_credentials is None:
            raise DomainError("FORBIDDEN", "当前不是演示环境，请输入邮箱验证码")
        if set(data) != {"account_id"}:
            raise DomainError("VALIDATION", "请提供待验证账号")
        challenge = self._cookies().get(self.server.verification_cookie)
        with self.server.verification_lock:
            grant = self.server.pending_verifications.get(challenge.value) if challenge else None
        if not grant or grant[0] != data["account_id"] or time.monotonic() - grant[1] >= 900:
            raise DomainError("FORBIDDEN", "仅能验证当前浏览器刚注册的演示账号")
        message = json.loads(
            (self.server.market.outbox / f"{grant[0]}.json").read_text(encoding="utf-8")
        )
        account = self.server.market.verify_email(message["verification_token"])
        with self.server.verification_lock:
            self.server.pending_verifications.pop(challenge.value, None)
        return account, [self._cookie(self.server.verification_cookie, "", True)]

    def _upload(self, data):
        if set(data) != {"name", "content_base64"}:
            raise DomainError("VALIDATION", "请选择要上传的图片")
        if not isinstance(data["content_base64"], str):
            raise DomainError("VALIDATION", "图片内容格式无效")
        try:
            content = base64.b64decode(data["content_base64"], validate=True)
        except (ValueError, binascii.Error) as error:
            raise DomainError("VALIDATION", "图片内容格式无效") from error
        if not content or len(content) > MAX_IMAGE_BYTES:
            raise DomainError("SIZE", "单张图片须在 5 MB 以内")
        with tempfile.TemporaryDirectory(prefix="campus-upload-") as directory:
            path = Path(directory) / "upload"
            path.write_bytes(content)
            return self.server.market.upload_image(self._token(), path)

    def _action(self, action, data):
        market = self.server.market
        cookies = []
        if action == "login":
            result = self._invoke(market.login, data)
            cookies.append(self._cookie(self.server.session_cookie, result["token"]))
            return result["account"], cookies
        if action == "demo-login":
            credentials = self.server.demo_credentials
            if credentials is None:
                raise DomainError("FORBIDDEN", "演示身份切换只在演示环境提供")
            if (
                set(data) != {"profile"}
                or not isinstance(data["profile"], str)
                or data["profile"] not in credentials
            ):
                raise DomainError("VALIDATION", "请选择有效的演示角色")
            result = market.login(**credentials[data["profile"]])
            cookies.append(self._cookie(self.server.session_cookie, result["token"]))
            return result["account"], cookies
        if action == "logout":
            result = self._invoke(market.logout, data, token=self._token())
            cookies.append(self._cookie(self.server.session_cookie, "", True))
            return result, cookies
        if action == "register":
            return self._register(data)
        if action == "verify":
            return self._invoke(market.verify_email, data), cookies
        if action == "demo-verify":
            return self._demo_verify(data)
        if action == "upload-image":
            return self._upload(data), cookies
        method_name = SERVICE_ACTIONS.get(action)
        if method_name is None:
            raise DomainError("NOT_FOUND", "操作不存在")
        return self._invoke(getattr(market, method_name), data, token=self._token()), cookies

    def do_POST(self):
        """Execute one explicitly mapped service action and return safe JSON."""
        try:
            self._check_mutation()
            path = urlsplit(self.path).path
            if not path.startswith("/api/"):
                raise DomainError("NOT_FOUND", "操作不存在")
            data = self._body()
            result, cookies = self._action(path.removeprefix("/api/"), data)
            self._success(result, cookies)
        except DomainError as error:
            self._error(error)
        except (OSError, sqlite3.Error, ValueError, TypeError):
            self._error(DomainError("SERVER", "操作未能完成，请刷新后检查最新状态"), 500)


def main(argv=None):
    """Open a browser window with an isolated, persistent demo by default."""
    parser = argparse.ArgumentParser(description="校园循物图形界面（本机浏览器）")
    parser.add_argument("--demo", action="store_true", help="使用独立的虚构演示数据")
    parser.add_argument("--data-dir", type=Path, default=Path("data/gui-demo"))
    parser.add_argument("--port", type=int, default=0, help="默认自动选择可用本机端口")
    parser.add_argument("--no-browser", action="store_true", help="仅启动服务，不自动打开浏览器")
    parser.add_argument("--domain", default="campus.example")
    arguments = parser.parse_args(argv)
    if arguments.demo:
        from .web_seed import prepare_demo

        market, credentials = prepare_demo(arguments.data_dir)
    else:
        market = Market(arguments.data_dir / "market.sqlite3", email_domain=arguments.domain)
        credentials = None
    server = MarketHTTPServer(("127.0.0.1", arguments.port), market, credentials)
    print(f"校园循物图形界面已启动：{server.base_url}", flush=True)
    print("请保留此服务窗口；在窗口内按 Control-C 可停止。", flush=True)
    if not arguments.no_browser:
        webbrowser.open(server.base_url)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("\n校园循物已停止。", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
