"""Exercise real HTTP boundaries and browser workflows over isolated SQLite data."""

import base64
import http.client
import json
import threading
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from campus_market.webapp import MarketHTTPServer
from tests.helpers import PASSWORD, MarketCase, verification_token

PIXEL_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1sAAAAASUVORK5CYII="
)


class BrowserClient:
    """Small independent browser cookie jar with explicit CSRF and origin headers."""

    def __init__(self, server):
        self.server = server
        self.cookies = {}

    def request(self, method, path, payload=None, headers=None, raw_body=None):
        address = urlsplit(self.server.base_url)
        connection = http.client.HTTPConnection(address.hostname, address.port, timeout=10)
        request_headers = {}
        if self.cookies:
            request_headers["Cookie"] = "; ".join(
                f"{key}={value}" for key, value in self.cookies.items()
            )
        body = raw_body
        if method == "POST":
            request_headers.update(
                {
                    "Origin": self.server.base_url,
                    "X-CSRF-Token": self.server.csrf,
                    "Content-Type": "application/json",
                }
            )
            if body is None:
                body = json.dumps(payload if payload is not None else {}).encode("utf-8")
        for name, value in (headers or {}).items():
            if value is None:
                request_headers.pop(name, None)
            else:
                request_headers[name] = value
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            response_headers = response.getheaders()
            data = response.read()
            for name, value in response_headers:
                if name.lower() == "set-cookie":
                    cookie = SimpleCookie()
                    cookie.load(value)
                    for key, morsel in cookie.items():
                        if not morsel.value or morsel["max-age"] == "0":
                            self.cookies.pop(key, None)
                        else:
                            self.cookies[key] = morsel.value
            content_type = response.getheader("Content-Type", "")
            decoded = json.loads(data) if "application/json" in content_type else data
            return response.status, decoded, response_headers
        finally:
            connection.close()

    def action(self, action, payload=None, headers=None):
        return self.request("POST", f"/api/{action}", payload, headers)


class WebApplicationTests(MarketCase):
    def setUp(self):
        super().setUp()
        self.servers = []
        self.server = self.start_server()
        self.guest = BrowserClient(self.server)

    def tearDown(self):
        for server, worker in reversed(self.servers):
            server.shutdown()
            worker.join(timeout=3)
            server.server_close()
        super().tearDown()

    def start_server(self, demo=False):
        credentials = None
        if demo:
            credentials = {
                name: {"identifier": name, "password": PASSWORD}
                for name in ("seller", "buyer", "admin")
            }
        server = MarketHTTPServer(("127.0.0.1", 0), self.market, demo_credentials=credentials)
        worker = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        worker.start()
        self.servers.append((server, worker))
        return server

    def success(self, client, action, payload=None):
        status, response, _ = client.action(action, payload)
        self.assertLess(status, 300, response)
        self.assertTrue(response["ok"], response)
        return response["data"]

    def denied(self, client, action, payload=None, headers=None):
        status, response, _ = client.action(action, payload, headers)
        self.assertGreaterEqual(status, 400, response)
        self.assertLess(status, 500, response)
        self.assertFalse(response["ok"], response)
        self.assertIsInstance(response["error"]["message"], str)
        return response

    def logged_in(self, name, server=None):
        client = BrowserClient(server or self.server)
        account = self.success(client, "login", {"identifier": name, "password": PASSWORD})
        self.assertEqual(account["id"], self.accounts[name]["id"])
        return client

    def test_context_and_static_assets_bootstrap_without_secrets(self):
        status, envelope, _ = self.guest.request("GET", "/api/context")
        self.assertEqual(status, 200)
        context = envelope["data"]
        self.assertIsNone(context["account"])
        self.assertFalse(context["demo"])
        self.assertEqual(context["csrf"], self.server.csrf)
        self.assertIn("教材书籍", context["categories"])
        self.assertIn("九成新", context["conditions"])
        for route, expected_type in (
            ("/", "text/html"),
            ("/app.js", "javascript"),
            ("/styles.css", "text/css"),
        ):
            with self.subTest(route=route):
                status, data, headers = self.guest.request("GET", route)
                self.assertEqual(status, 200)
                self.assertGreater(len(data), 100)
                response_headers = {name.lower(): value for name, value in headers}
                self.assertIn(expected_type, response_headers["content-type"])
                self.assertNotIn(PASSWORD.encode(), data)

    def test_csrf_origin_and_host_checks_reject_cross_site_requests(self):
        before = self.business_snapshot()
        payload = {"identifier": "buyer", "password": PASSWORD}
        for headers in (
            {"X-CSRF-Token": None},
            {"X-CSRF-Token": "forged"},
            {"Origin": "https://attacker.invalid"},
            {"Origin": None},
            {"Host": "attacker.invalid"},
        ):
            with self.subTest(headers=headers):
                self.denied(self.guest, "login", payload, headers)
        status, _, _ = self.guest.request(
            "GET", "/api/context", headers={"Host": "attacker.invalid"}
        )
        self.assertGreaterEqual(status, 400)
        self.assertEqual(self.business_snapshot(), before)

    def test_login_uses_private_cookie_and_does_not_return_bearer_token(self):
        status, response, headers = self.guest.action(
            "login", {"identifier": "buyer", "password": PASSWORD}
        )
        self.assertEqual(status, 200)
        account = response["data"]
        self.assertEqual(account["username"], "buyer")
        rendered = json.dumps(response)
        self.assertNotIn(PASSWORD, rendered)
        self.assertNotIn("password_hash", rendered)
        self.assertNotIn('"token"', rendered)
        cookies = [value for name, value in headers if name.lower() == "set-cookie"]
        self.assertTrue(cookies)
        self.assertTrue(
            any("HttpOnly" in cookie and "SameSite=Strict" in cookie for cookie in cookies)
        )
        self.assertEqual(self.success(self.guest, "me")["id"], self.accounts["buyer"]["id"])
        _, context, _ = self.guest.request("GET", "/api/context")
        self.assertEqual(context["data"]["account"]["id"], self.accounts["buyer"]["id"])

    def test_logout_revokes_saved_cookie_on_server(self):
        buyer = self.logged_in("buyer")
        stolen_copy = dict(buyer.cookies)
        self.success(buyer, "logout")
        self.denied(buyer, "me")
        buyer.cookies = stolen_copy
        self.denied(buyer, "me")

    def test_demo_switching_is_explicit_and_disabled_for_regular_server(self):
        self.denied(self.guest, "demo-login", {"profile": "admin"})
        demo = BrowserClient(self.start_server(demo=True))
        _, context, _ = demo.request("GET", "/api/context")
        self.assertTrue(context["data"]["demo"])
        for name in ("buyer", "seller", "admin"):
            account = self.success(demo, "demo-login", {"profile": name})
            self.assertEqual(account["id"], self.accounts[name]["id"])
            self.assertNotIn("token", account)
        self.denied(demo, "demo-login", {"profile": "other"})

    def test_full_gui_workflow_preserves_service_authorization_and_statistics(self):
        seller = self.logged_in("seller")
        buyer = self.logged_in("buyer")
        admin = self.logged_in("admin")
        draft = self.success(seller, "save-draft", {"content": self.content(price="42.30")})
        self.denied(buyer, "product", {"product_id": draft["id"]})
        submission = self.success(
            seller,
            "submit",
            {
                "product_id": draft["id"],
                "expected_version": draft["row_version"],
                "request_key": "gui-submit",
            },
        )
        self.denied(
            buyer,
            "review",
            {"submission_id": submission["id"], "approve": True, "reason": "无权限审核"},
        )
        self.success(
            admin,
            "review",
            {"submission_id": submission["id"], "approve": True, "reason": "资料完整"},
        )
        market = self.success(self.guest, "products", {"keyword": "软件工程", "scope": "public"})
        self.assertEqual(market["total"], 1)
        public = market["items"][0]
        reservation = self.success(
            buyer,
            "reserve",
            {
                "product_id": public["id"],
                "content_version": public["content_version"],
                "message": "明天下午图书馆面交",
                "request_key": "gui-reserve",
            },
        )
        self.denied(
            admin,
            "confirm",
            {"reservation_id": reservation["id"], "request_key": "admin-confirm"},
        )
        self.success(
            seller,
            "confirm",
            {"reservation_id": reservation["id"], "request_key": "gui-confirm"},
        )
        self.denied(
            buyer,
            "cancel",
            {"reservation_id": reservation["id"], "request_key": "no-reason"},
        )
        completed = self.success(
            seller,
            "complete",
            {"reservation_id": reservation["id"], "request_key": "gui-complete"},
        )
        self.assertEqual(completed["state"], "COMPLETED")
        self.assertEqual(self.success(admin, "statistics")["amount_cents"], 4230)
        logs = self.success(seller, "logs", {"object_id": public["id"]})
        self.assertIn("complete", {entry["operation"] for entry in logs["items"]})

    def test_image_upload_and_image_route_follow_reference_visibility(self):
        seller = self.logged_in("seller")
        image = self.success(
            seller, "upload-image", {"name": "photo.png", "content_base64": PIXEL_BASE64}
        )
        status, data, _ = seller.request("GET", f"/api/image/{image['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(data, base64.b64decode(PIXEL_BASE64))
        status, _, _ = self.guest.request("GET", f"/api/image/{image['id']}")
        self.assertGreaterEqual(status, 400)
        self.published(images=[image["id"]])
        status, data, _ = self.guest.request("GET", f"/api/image/{image['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(data, base64.b64decode(PIXEL_BASE64))

    def test_invalid_image_input_is_rejected_without_creating_rows(self):
        seller = self.logged_in("seller")
        for payload in (
            {"name": "photo.png", "content_base64": "not-base64!"},
            {"name": "photo.png", "content_base64": base64.b64encode(b"not a PNG").decode()},
            {
                "name": "photo.png",
                "content_base64": base64.b64encode(b"x" * (5 * 1024 * 1024 + 1)).decode(),
            },
        ):
            with self.subTest(size=len(payload["content_base64"])):
                self.denied(seller, "upload-image", payload)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM images"), 0)

    def test_registration_keeps_verification_private_and_normal_verification_works(self):
        previous = set(self.outbox.glob("*.json"))
        response = self.success(
            self.guest,
            "register",
            {
                "username": "new_http_user",
                "email": "new@campus.example",
                "campus_id": "HTTP-NEW",
                "password": PASSWORD,
            },
        )
        self.assertNotIn("verification_token", json.dumps(response))
        self.denied(self.guest, "login", {"identifier": "new_http_user", "password": PASSWORD})
        code = verification_token(self.outbox, previous)
        verified = self.success(self.guest, "verify", {"verification_token": code})
        self.assertEqual(verified["verified"], 1)
        self.assertEqual(
            self.success(
                self.guest, "login", {"identifier": "new_http_user", "password": PASSWORD}
            )["id"],
            response["account"]["id"],
        )
        self.denied(self.guest, "demo-verify", {"account_id": response["account"]["id"]})

    def test_demo_verification_requires_registration_cookie_bound_to_same_account(self):
        server = self.start_server(demo=True)
        registrant = BrowserClient(server)
        outsider = BrowserClient(server)
        created = self.success(
            registrant,
            "register",
            {
                "username": "demo_new",
                "email": "demo_new@campus.example",
                "campus_id": "HTTP-DEMO",
                "password": PASSWORD,
            },
        )
        identifier = created["account"]["id"]
        self.denied(outsider, "demo-verify", {"account_id": identifier})
        self.assertEqual(self.scalar("SELECT verified FROM accounts WHERE id=?", (identifier,)), 0)
        self.denied(registrant, "demo-verify", {"account_id": self.accounts["other"]["id"]})
        verified = self.success(registrant, "demo-verify", {"account_id": identifier})
        self.assertEqual(verified["verified"], 1)
        self.success(registrant, "login", {"identifier": "demo_new", "password": PASSWORD})

    def test_unknown_paths_and_malformed_json_fail_without_tracebacks(self):
        for path in ("/../accounts.py", "/data/market.sqlite3", "/missing.js"):
            status, response, _ = self.guest.request("GET", path)
            self.assertGreaterEqual(status, 400)
            self.assertNotIn("password_hash", str(response))
        self.denied(self.guest, "unknown-action")
        for raw in (b"not-json", b"[]", b"null"):
            status, response, _ = self.guest.request("POST", "/api/login", raw_body=raw)
            self.assertGreaterEqual(status, 400)
            self.assertLess(status, 500)
            self.assertNotIn("Traceback", str(response))

    def test_session_expiry_is_enforced_for_http_actions(self):
        buyer = self.logged_in("buyer")
        self.clock.advance(1800)
        self.denied(buyer, "me")
        self.denied(buyer, "reservations")

    def test_context_poll_does_not_extend_idle_session(self):
        buyer = self.logged_in("buyer")
        self.clock.advance(1799)
        status, context, _ = buyer.request("GET", "/api/context")
        self.assertEqual(status, 200)
        self.assertEqual(context["data"]["account"]["id"], self.accounts["buyer"]["id"])
        self.clock.advance(1)
        status, context, _ = buyer.request("GET", "/api/context")
        self.assertEqual(status, 200)
        self.assertIsNone(context["data"]["account"])
        self.denied(buyer, "me")

    def test_client_supplied_role_or_token_cannot_override_cookie_authority(self):
        draft = self.draft()
        before = self.business_snapshot()
        self.denied(
            self.guest,
            "save-draft",
            {
                "token": self.tokens["seller"],
                "product_id": draft["id"],
                "expected_version": draft["row_version"],
                "content": self.content(title="未登录不得修改"),
            },
        )
        self.denied(
            self.guest,
            "register",
            {
                "username": "forged_admin",
                "email": "forged@campus.example",
                "campus_id": "FORGED-ADMIN",
                "password": PASSWORD,
                "role": "ADMIN",
            },
        )
        self.assertEqual(self.business_snapshot(), before)
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM accounts WHERE username='forged_admin'"), 0
        )
