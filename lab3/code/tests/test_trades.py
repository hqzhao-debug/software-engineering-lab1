"""Reservation state transitions, immutable snapshots, and idempotency."""

import json

from tests.helpers import MarketCase


class TradeTests(MarketCase):
    def test_successful_trade_is_atomic_and_final(self):
        product = self.published()
        reservation = self.reservation(product)
        self.assertEqual(reservation["state"], "PENDING")
        self.assertEqual(
            self.market.get_product(product["id"], self.tokens["seller"])["state"],
            "PENDING",
        )
        self.assert_denied(self.market.get_product, product["id"])
        self.market.confirm(self.tokens["seller"], reservation["id"], "confirm")
        completed = self.market.complete(
            self.tokens["seller"], reservation["id"], "complete"
        )
        self.assertEqual(completed["state"], "COMPLETED")
        sold = self.market.get_product(product["id"], self.tokens["seller"])
        self.assertEqual(sold["state"], "SOLD")
        self.assertIsNotNone(completed["completed_at"])
        self.assert_denied(
            self.market.save_draft, self.tokens["seller"], self.content(),
            product["id"], sold["row_version"],
        )
        self.assert_denied(
            self.market.cancel, self.tokens["buyer"], reservation["id"],
            "new-cancel", "已完成不可取消",
        )

    def test_self_reservation_admin_reservation_and_empty_message_rejected(self):
        product = self.published()
        for actor, message in (("seller", "面交"), ("admin", "面交"), ("buyer", " ")):
            with self.subTest(actor=actor, message=message):
                self.assert_denied(
                    self.market.reserve, self.tokens[actor], product["id"],
                    product["content_version"], message, f"bad-{actor}",
                )
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM reservations"), 0)

    def test_only_seller_confirms_rejects_and_completes(self):
        reservation = self.reservation()
        for actor in ("buyer", "other", "admin"):
            for operation in (self.market.confirm, self.market.reject, self.market.complete):
                with self.subTest(actor=actor, operation=operation.__name__):
                    self.assert_denied(
                        operation, self.tokens[actor], reservation["id"],
                        f"unauthorized-{actor}-{operation.__name__}",
                    )
        self.assert_denied(
            self.market.complete, self.tokens["seller"], reservation["id"], "early"
        )
        self.assertEqual(
            self.market.get_reservation(self.tokens["buyer"], reservation["id"])
            ["state"], "PENDING",
        )

    def test_pending_buyer_cancel_requires_no_reason_and_releases(self):
        product = self.published()
        reservation = self.reservation(product)
        cancelled = self.market.cancel(
            self.tokens["buyer"], reservation["id"], "cancel"
        )
        self.assertEqual(cancelled["state"], "CANCELLED")
        self.assertEqual(self.market.get_product(product["id"])["state"], "ON_SALE")
        self.assert_denied(
            self.market.confirm, self.tokens["seller"], reservation["id"], "late"
        )

    def test_pending_seller_uses_reject_not_cancel(self):
        product = self.published()
        reservation = self.reservation(product)
        self.assert_denied(
            self.market.cancel, self.tokens["seller"], reservation["id"], "cancel"
        )
        rejected = self.market.reject(
            self.tokens["seller"], reservation["id"], "reject"
        )
        self.assertEqual(rejected["state"], "REJECTED")
        self.assertEqual(self.market.get_product(product["id"])["state"], "ON_SALE")

    def test_confirmation_then_reasoned_cancel_is_valid_current_transition(self):
        reservation = self.confirmed()
        for actor in ("buyer", "seller"):
            self.assert_denied(
                self.market.cancel, self.tokens[actor], reservation["id"],
                f"missing-reason-{actor}",
            )
        current = self.market.get_reservation(self.tokens["buyer"], reservation["id"])
        self.assertEqual(current["state"], "CONFIRMED")
        cancelled = self.market.cancel(
            self.tokens["buyer"], reservation["id"], "reasoned", "面交时间冲突"
        )
        self.assertEqual(cancelled["state"], "CANCELLED")
        self.assertEqual(cancelled["close_reason"], "面交时间冲突")

    def test_active_reservation_blocks_edit_and_manual_off_shelf(self):
        product = self.published()
        self.reservation(product)
        current = self.market.get_product(product["id"], self.tokens["seller"])
        before = self.business_snapshot()
        self.assert_denied(
            self.market.save_draft, self.tokens["seller"], self.content(price="1"),
            product["id"], current["row_version"],
        )
        self.assert_denied(
            self.market.off_shelf, self.tokens["seller"], product["id"],
            current["row_version"],
        )
        self.assertEqual(self.business_snapshot(), before)

    def test_repeated_reservation_returns_current_terminal_state(self):
        product = self.published()
        first = self.reservation(product)
        second = self.reservation(product)
        self.assertEqual(first["id"], second["id"])
        self.market.cancel(self.tokens["buyer"], first["id"], "cancel")
        replay = self.reservation(product)
        self.assertEqual(replay["id"], first["id"])
        self.assertEqual(replay["state"], "CANCELLED")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM reservations"), 1)
        self.assertEqual(self.market.get_product(product["id"])["state"], "ON_SALE")

    def test_same_key_different_payload_is_rejected(self):
        product = self.published()
        self.reservation(product)
        before = self.business_snapshot()
        self.assert_denied(
            self.market.reserve, self.tokens["buyer"], product["id"],
            product["content_version"], "不同留言", "reserve-1",
        )
        self.assertEqual(self.business_snapshot(), before)

    def test_new_device_key_links_existing_reservation_and_terminal_replay(self):
        product = self.published()
        first = self.reservation(product)
        another = self.reservation(product, key="other-device")
        self.assertEqual(first["id"], another["id"])
        self.market.reject(self.tokens["seller"], first["id"], "reject", "已约其他安排")
        replay = self.reservation(product, key="other-device")
        self.assertEqual(replay["id"], first["id"])
        self.assertEqual(replay["state"], "REJECTED")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM reservations"), 1)

    def test_successful_complete_retry_does_not_duplicate_statistics(self):
        reservation = self.confirmed()
        self.market.complete(self.tokens["seller"], reservation["id"], "complete")
        before = self.market.statistics(self.tokens["admin"])
        replay = self.market.complete(
            self.tokens["seller"], reservation["id"], "complete"
        )
        self.assertEqual(replay["state"], "COMPLETED")
        self.assertEqual(self.market.statistics(self.tokens["admin"]), before)
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM reservations WHERE state='COMPLETED'"), 1
        )

    def test_email_visibility_follows_reservation_state(self):
        reservation = self.reservation()
        buyer_view = self.market.get_reservation(self.tokens["buyer"], reservation["id"])
        seller_view = self.market.get_reservation(self.tokens["seller"], reservation["id"])
        self.assertEqual(buyer_view["counterparty_email"], "seller@campus.example")
        self.assertEqual(seller_view["counterparty_email"], "buyer@campus.example")
        self.assertNotIn("@", json.dumps(buyer_view["snapshot"]))
        self.assert_denied(
            self.market.get_reservation, self.tokens["other"], reservation["id"]
        )
        self.market.cancel(self.tokens["buyer"], reservation["id"], "cancel")
        closed = self.market.get_reservation(self.tokens["buyer"], reservation["id"])
        self.assertNotIn("seller@campus.example", json.dumps(closed))
        listed = self.market.list_reservations(self.tokens["buyer"])
        self.assertNotIn("seller@campus.example", json.dumps(listed))

    def test_old_snapshot_survives_new_price_and_new_reservation(self):
        product = self.published(price="25.50")
        old = self.reservation(product)
        self.market.cancel(self.tokens["buyer"], old["id"], "cancel")
        current = self.market.get_product(product["id"], self.tokens["seller"])
        draft = self.market.save_draft(
            self.tokens["seller"], self.content(price="30"), product["id"],
            current["row_version"],
        )
        submission = self.market.submit_product(
            self.tokens["seller"], product["id"], draft["row_version"], "new-submit"
        )
        self.market.review(self.tokens["admin"], submission["id"], True, "新价格可发布")
        new_product = self.market.get_product(product["id"])
        new = self.reservation(new_product, key="new-reservation")
        old_now = self.market.get_reservation(self.tokens["buyer"], old["id"])
        self.assertEqual(old_now["snapshot"]["price"], "25.50")
        self.assertEqual(new["snapshot"]["price"], "30.00")
        self.assertNotEqual(new["id"], old["id"])

    def test_successful_retry_still_requires_current_valid_session(self):
        product = self.published()
        self.reservation(product)
        self.market.logout(self.tokens["buyer"])
        self.assert_denied(self.reservation, product)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM reservations"), 1)
