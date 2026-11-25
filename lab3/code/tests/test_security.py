"""Registration, account lockout, session clocks, and authorization."""

import json

from tests.helpers import DOMAIN, PASSWORD, MarketCase, verification_token


class AccountSecurityTests(MarketCase):
    def test_registration_requires_verification_and_consumes_token_once(self):
        registered = self.market.register("newuser", f"newuser@{DOMAIN}", "NEW-ID", PASSWORD)
        self.assertEqual(registered["account"]["role"], "USER")
        self.assertNotIn("verification_token", registered)
        self.assert_denied(self.market.login, "newuser", PASSWORD)
        token = verification_token(self.outbox)
        self.market.verify_email(token)
        self.assertEqual(self.market.login("newuser", PASSWORD)["account"]["role"], "USER")
        self.assert_denied(self.market.verify_email, token)
        self.assert_denied(self.market.verify_email, "invalid-token")

    def test_username_email_and_campus_id_uniqueness(self):
        for username, email, campus_id in (
            ("seller", f"new@{DOMAIN}", "NEW-ID"),
            ("new", f"seller@{DOMAIN}", "NEW-ID"),
            ("new", f"new@{DOMAIN}", "ID-seller"),
        ):
            with self.subTest(username=username, email=email, campus_id=campus_id):
                self.assert_denied(self.market.register, username, email, campus_id, PASSWORD)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM accounts"), 4)

    def test_domain_restriction_and_required_fields(self):
        for username, email, campus_id, password in (
            ("new", "new@example.org", "NEW", PASSWORD),
            ("new", "invalid-email", "NEW", PASSWORD),
            (" ", f"new@{DOMAIN}", "NEW", PASSWORD),
            ("new", f"new@{DOMAIN}", " ", PASSWORD),
            ("new", f"new@{DOMAIN}", "NEW", ""),
        ):
            self.assert_denied(self.market.register, username, email, campus_id, password)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM accounts"), 4)

    def test_admin_creation_requires_admin_and_new_email_verification(self):
        self.assert_denied(
            self.market.create_admin,
            self.tokens["buyer"],
            "admin2",
            f"admin2@{DOMAIN}",
            "ADMIN-2",
            PASSWORD,
        )
        result = self.market.create_admin(
            self.tokens["admin"], "admin2", f"admin2@{DOMAIN}", "ADMIN-2", PASSWORD
        )
        self.assertEqual(result["account"]["role"], "ADMIN")
        self.assert_denied(self.market.login, "admin2", PASSWORD)
        self.market.verify_email(verification_token(self.outbox))
        self.assertEqual(self.market.login("admin2", PASSWORD)["account"]["role"], "ADMIN")
        self.assert_denied(
            self.market.bootstrap_admin, "root2", f"root2@{DOMAIN}", "ROOT-2", PASSWORD
        )

    def test_password_is_hashed_and_never_returned_or_logged(self):
        row = self.rows("SELECT password_hash FROM accounts WHERE username='seller'")[0]
        self.assertNotEqual(row["password_hash"], PASSWORD)
        logged_in = self.market.login("seller", PASSWORD)
        self.assert_denied(self.market.login, "seller", "Wrong-Secret-123")
        outputs = json.dumps(
            [
                logged_in["account"],
                self.market.list_accounts(self.tokens["admin"]),
                self.market.list_logs(self.tokens["admin"]),
            ]
        )
        for forbidden in (PASSWORD, "Wrong-Secret-123", row["password_hash"], "password_hash"):
            self.assertNotIn(forbidden, outputs)
        raw_logs = json.dumps(self.rows("SELECT * FROM audit_logs"))
        self.assertNotIn(PASSWORD, raw_logs)
        self.assertNotIn("Wrong-Secret-123", raw_logs)
        self.assertNotIn(row["password_hash"], raw_logs)

    def test_fifth_failure_locks_for_fixed_fifteen_minutes(self):
        for _ in range(4):
            self.assert_denied(self.market.login, "buyer", "incorrect")
        before = self.rows("SELECT * FROM accounts WHERE username='buyer'")[0]
        self.assertEqual(before["failed_count"], 4)
        self.assertFalse(before["locked_until"])
        self.assert_denied(self.market.login, "buyer", "incorrect")
        locked = self.rows("SELECT * FROM accounts WHERE username='buyer'")[0]
        self.assertEqual(locked["locked_until"], self.clock() + 900)
        self.clock.advance(600)
        self.assert_denied(self.market.login, "buyer", PASSWORD)
        self.assert_denied(self.market.login, "buyer", "incorrect")
        unchanged = self.rows("SELECT * FROM accounts WHERE username='buyer'")[0]
        self.assertEqual(unchanged["locked_until"], locked["locked_until"])
        self.assertEqual(unchanged["failed_count"], locked["failed_count"])
        self.clock.advance(300)
        self.assert_denied(self.market.login, "buyer", "incorrect")
        reset = self.rows("SELECT * FROM accounts WHERE username='buyer'")[0]
        self.assertEqual(reset["failed_count"], 1)
        self.market.login("buyer", PASSWORD)
        self.assertEqual(self.scalar("SELECT failed_count FROM accounts WHERE username='buyer'"), 0)

    def test_successful_login_clears_prior_failure_count(self):
        self.assert_denied(self.market.login, "seller", "incorrect")
        self.market.login("seller@campus.example", PASSWORD)
        self.assertEqual(
            self.scalar("SELECT failed_count FROM accounts WHERE username='seller'"), 0
        )

    def test_sessions_have_independent_idle_time_and_exact_timeout(self):
        session_a = self.tokens["buyer"]
        session_b = self.market.login("buyer", PASSWORD)["token"]
        self.clock.advance(1_000)
        self.market.whoami(session_a)
        self.clock.advance(800)
        self.assert_denied(self.market.whoami, session_b)
        self.assertEqual(self.market.whoami(session_a)["username"], "buyer")

    def test_background_read_does_not_extend_session(self):
        self.clock.advance(1_799)
        self.market.whoami(self.tokens["buyer"], active=False)
        self.clock.advance(1)
        self.assert_denied(self.market.whoami, self.tokens["buyer"], active=False)

    def test_logout_revokes_only_current_session(self):
        second = self.market.login("buyer", PASSWORD)["token"]
        self.market.logout(self.tokens["buyer"])
        self.assert_denied(self.market.whoami, self.tokens["buyer"])
        self.assertEqual(self.market.whoami(second)["username"], "buyer")

    def test_four_required_unauthorized_actions_leave_business_unchanged(self):
        product = self.published()
        reservation = self.reservation(product)
        draft = self.draft()
        submission = self.market.submit_product(
            self.tokens["seller"], draft["id"], draft["row_version"], "submit-other"
        )
        actions = (
            (
                self.market.reserve,
                (None, product["id"], product["content_version"], "面交", "guest"),
            ),
            (self.market.cancel, (self.tokens["other"], reservation["id"], "other-cancel")),
            (
                self.market.save_draft,
                (self.tokens["other"], self.content(), product["id"], product["row_version"]),
            ),
            (self.market.review, (self.tokens["buyer"], submission["id"], True, "越权审核")),
        )
        for operation, arguments in actions:
            with self.subTest(operation=operation.__name__):
                before = self.business_snapshot()
                log_count = self.scalar("SELECT COUNT(*) FROM audit_logs")
                self.assert_denied(operation, *arguments)
                self.assertEqual(self.business_snapshot(), before)
                self.assertGreater(self.scalar("SELECT COUNT(*) FROM audit_logs"), log_count)

    def test_other_users_logs_and_accounts_are_not_exposed(self):
        secret_product = self.draft(title="别人私人草稿")
        logs = self.market.list_logs(self.tokens["other"])
        self.assertNotIn(secret_product["id"], json.dumps(logs))
        self.assertEqual(logs["page_size"], 50)
        self.assert_denied(self.market.list_accounts, self.tokens["buyer"])
