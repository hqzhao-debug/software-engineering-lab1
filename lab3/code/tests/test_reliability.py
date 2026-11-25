"""Cross-connection contention, atomic rollback, database constraints and restart."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from campus_market.models import DomainError
from tests.helpers import MarketCase


def attempt(call):
    """Return a tagged result while preserving unexpected errors as failures."""
    try:
        return {"ok": True, "result": call()}
    except DomainError as error:
        return {"ok": False, "error": error.code}


class ReliabilityTests(MarketCase):
    def race(self, calls):
        barrier = threading.Barrier(len(calls))

        def run(call):
            barrier.wait(timeout=10)
            return attempt(call)

        with ThreadPoolExecutor(max_workers=len(calls)) as executor:
            futures = [executor.submit(run, call) for call in calls]
            return [future.result(timeout=20) for future in futures]

    def test_two_buyers_race_for_one_item_ten_rounds(self):
        services = [self.new_market(), self.new_market()]
        for round_number in range(10):
            with self.subTest(round_number=round_number):
                product = self.published(title=f"并发预约测试商品 {round_number}")
                names = ("buyer", "other")
                calls = [
                    lambda service=service,
                    name=name,
                    product=product,
                    round_number=round_number: service.reserve(
                        self.tokens[name],
                        product["id"],
                        product["content_version"],
                        "图书馆面交",
                        f"race-{round_number}",
                    )
                    for service, name in zip(services, names, strict=True)
                ]
                results = self.race(calls)
                winners = [index for index, result in enumerate(results) if result["ok"]]
                self.assertEqual(len(winners), 1)
                winner_index = winners[0]
                winner = results[winner_index]["result"]
                for _ in range(5):
                    replay_results = self.race(calls)
                    self.assertTrue(replay_results[winner_index]["ok"])
                    self.assertEqual(replay_results[winner_index]["result"]["id"], winner["id"])
                    self.assertFalse(replay_results[1 - winner_index]["ok"])
                self.assertEqual(
                    self.scalar(
                        "SELECT COUNT(*) FROM reservations WHERE product_id=?", (product["id"],)
                    ),
                    1,
                )
                self.assertEqual(
                    self.scalar("SELECT state FROM products WHERE id=?", (product["id"],)),
                    "PENDING",
                )

    def test_same_request_race_creates_one_business_record(self):
        product = self.published()
        services = [self.new_market() for _ in range(8)]
        results = self.race(
            [
                lambda service=service: service.reserve(
                    self.tokens["buyer"],
                    product["id"],
                    product["content_version"],
                    "同一次点击重试",
                    "shared-key",
                )
                for service in services
            ]
        )
        self.assertTrue(all(result["ok"] for result in results))
        self.assertEqual(len({result["result"]["id"] for result in results}), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM reservations"), 1)
        self.assertEqual(
            self.scalar(
                "SELECT COUNT(*) FROM audit_logs WHERE operation='reserve' AND result='REPLAY'"
            ),
            7,
        )

    def test_cancel_confirm_competition_ten_rounds(self):
        services = [self.new_market(), self.new_market()]
        for round_number in range(10):
            with self.subTest(round_number=round_number):
                product = self.published(title=f"取消确认竞争商品 {round_number}")
                reservation = self.reservation(product, key=f"reserve-{round_number}")
                reason = "时间冲突" if round_number % 2 else ""
                results = self.race(
                    [
                        lambda reservation=reservation,
                        round_number=round_number,
                        reason=reason: services[0].cancel(
                            self.tokens["buyer"],
                            reservation["id"],
                            f"cancel-{round_number}",
                            reason,
                        ),
                        lambda reservation=reservation, round_number=round_number: services[
                            1
                        ].confirm(
                            self.tokens["seller"], reservation["id"], f"confirm-{round_number}"
                        ),
                    ]
                )
                current = self.market.get_reservation(self.tokens["buyer"], reservation["id"])
                if reason:
                    self.assertTrue(results[0]["ok"])
                    self.assertEqual(current["state"], "CANCELLED")
                else:
                    self.assertEqual(sum(result["ok"] for result in results), 1)
                    expected = "CANCELLED" if results[0]["ok"] else "CONFIRMED"
                    self.assertEqual(current["state"], expected)
                product_state = self.scalar(
                    "SELECT state FROM products WHERE id=?", (product["id"],)
                )
                self.assertEqual(
                    product_state,
                    "ON_SALE" if current["state"] == "CANCELLED" else "CONFIRMED",
                )

    def test_competing_review_decisions_do_not_overwrite(self):
        draft = self.draft()
        submission = self.market.submit_product(
            self.tokens["seller"], draft["id"], draft["row_version"], "submit"
        )
        services = [self.new_market(), self.new_market()]
        results = self.race(
            [
                lambda: services[0].review(
                    self.tokens["admin"], submission["id"], True, "符合规定"
                ),
                lambda: services[1].review(
                    self.tokens["admin"], submission["id"], False, "描述不完整"
                ),
            ]
        )
        self.assertEqual(sum(result["ok"] for result in results), 1)
        row = self.rows("SELECT * FROM review_submissions WHERE id=?", (submission["id"],))[0]
        self.assertEqual(row["status"], "APPROVED" if results[0]["ok"] else "REJECTED")

    def install_audit_failure(self, operation):
        # The operation is a test-owned constant, not user input.
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "CREATE TRIGGER reject_test_success BEFORE INSERT ON audit_logs "
                f"WHEN NEW.operation='{operation}' AND NEW.result='SUCCESS' "
                "BEGIN SELECT RAISE(ABORT, 'injected audit write failure'); END"
            )
            connection.commit()

    def remove_audit_failure(self):
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("DROP TRIGGER reject_test_success")
            connection.commit()

    def test_reservation_rolls_back_when_success_audit_fails(self):
        product = self.published()
        before = self.business_snapshot()
        self.install_audit_failure("reserve")
        self.assert_denied(self.reservation, product)
        self.assertEqual(self.business_snapshot(), before)
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM idempotency WHERE operation='reserve'"), 0
        )
        self.remove_audit_failure()
        self.assertEqual(self.reservation(product)["state"], "PENDING")

    def test_completion_rolls_back_with_audit_and_can_retry_same_key(self):
        reservation = self.confirmed()
        before = self.business_snapshot()
        statistics = self.market.statistics(self.tokens["admin"])
        self.install_audit_failure("complete")
        self.assert_denied(
            self.market.complete, self.tokens["seller"], reservation["id"], "complete"
        )
        self.assertEqual(self.business_snapshot(), before)
        self.assertEqual(self.market.statistics(self.tokens["admin"]), statistics)
        self.remove_audit_failure()
        self.assertEqual(
            self.market.complete(self.tokens["seller"], reservation["id"], "complete")["state"],
            "COMPLETED",
        )

    def test_cancellation_rolls_back_without_releasing_product_on_audit_failure(self):
        reservation = self.confirmed()
        before = self.business_snapshot()
        self.install_audit_failure("cancel")
        self.assert_denied(
            self.market.cancel,
            self.tokens["buyer"],
            reservation["id"],
            "cancel",
            "时间冲突",
        )
        self.assertEqual(self.business_snapshot(), before)
        self.remove_audit_failure()
        cancelled = self.market.cancel(
            self.tokens["buyer"], reservation["id"], "cancel", "时间冲突"
        )
        self.assertEqual(cancelled["state"], "CANCELLED")

    def test_ban_audit_failure_rolls_back_account_sessions_and_linked_trade(self):
        self.reservation()
        before = self.business_snapshot()
        account_before = self.rows("SELECT id,status FROM accounts ORDER BY id")
        sessions_before = self.rows(
            "SELECT token_hash,revoked_at FROM sessions ORDER BY token_hash"
        )
        self.install_audit_failure("ban_account")
        self.assert_denied(
            self.market.ban_account,
            self.tokens["admin"],
            self.accounts["seller"]["id"],
            "违规处理",
        )
        self.assertEqual(self.business_snapshot(), before)
        self.assertEqual(self.rows("SELECT id,status FROM accounts ORDER BY id"), account_before)
        self.assertEqual(
            self.rows("SELECT token_hash,revoked_at FROM sessions ORDER BY token_hash"),
            sessions_before,
        )
        self.remove_audit_failure()
        self.assertEqual(self.market.whoami(self.tokens["seller"])["status"], "NORMAL")

    def test_database_constraints_prevent_duplicate_or_changed_history(self):
        reservation = self.reservation()
        with closing(self.market._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM reservations WHERE id=?", (reservation["id"],)
            ).fetchone()
            values = list(row)
            values[0] = "duplicate-active-id"
            placeholders = ",".join("?" for _ in values)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(f"INSERT INTO reservations VALUES ({placeholders})", values)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE reservations SET snapshot_json='{}' WHERE id=?",
                    (reservation["id"],),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM submitted_versions")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM audit_logs")

    def test_saved_records_and_logs_survive_restart_and_response_loss(self):
        products = [self.published(title=f"重启保留商品 {index}") for index in range(5)]
        reservations = [
            self.reservation(product, key=f"restart-{index}")
            for index, product in enumerate(products[:3])
        ]
        before = self.business_snapshot()
        audit_before = self.rows("SELECT * FROM audit_logs ORDER BY id")
        restarted = self.new_market()
        self.assertEqual(self.business_snapshot(), before)
        self.assertEqual(self.rows("SELECT * FROM audit_logs ORDER BY id"), audit_before)
        for index, reservation in enumerate(reservations):
            replay = restarted.reserve(
                self.tokens["buyer"],
                products[index]["id"],
                products[index]["content_version"],
                "周三下午图书馆门口面交",
                f"restart-{index}",
            )
            self.assertEqual(replay["id"], reservation["id"])
            self.assertEqual(replay["state"], "PENDING")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM products"), 5)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM reservations"), 3)

    def test_ban_and_reservation_compete_without_leaving_active_trade(self):
        product = self.published()
        services = [self.new_market(), self.new_market()]
        results = self.race(
            [
                lambda: services[0].reserve(
                    self.tokens["buyer"],
                    product["id"],
                    product["content_version"],
                    "尝试预约",
                    "ban-race",
                ),
                lambda: services[1].ban_account(
                    self.tokens["admin"], self.accounts["seller"]["id"], "违规封禁"
                ),
            ]
        )
        self.assertTrue(results[1]["ok"])
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM reservations WHERE state IN ('PENDING','CONFIRMED')"),
            0,
        )
        self.assertEqual(
            self.scalar("SELECT state FROM products WHERE id=?", (product["id"],)), "OFF_SHELF"
        )
