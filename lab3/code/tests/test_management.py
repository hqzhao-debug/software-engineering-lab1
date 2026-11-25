"""Administrative restrictions, linked cancellation, and aggregate integrity."""

from tests.helpers import PASSWORD, MarketCase


class ManagementTests(MarketCase):
    def test_violation_cancels_active_trade_and_requires_review_to_restore(self):
        product = self.published()
        reservation = self.confirmed(product)
        blocked = self.market.mark_violation(
            self.tokens["admin"], product["id"], "描述隐瞒严重缺陷"
        )
        self.assertEqual(blocked["state"], "VIOLATION")
        closed = self.market.get_reservation(self.tokens["buyer"], reservation["id"])
        self.assertEqual(closed["state"], "CANCELLED")
        self.assertIn("违规", closed["close_reason"])
        self.assert_denied(
            self.market.cancel, self.tokens["buyer"], reservation["id"],
            "late-cancel", "已被管理处理",
        )
        draft = self.market.save_draft(
            self.tokens["seller"], self.content(description="已补充全部缺陷说明"),
            product["id"], blocked["row_version"],
        )
        self.assertTrue(draft["active_restriction"])
        submission = self.market.submit_product(
            self.tokens["seller"], product["id"], draft["row_version"], "fix-submit"
        )
        self.market.review(self.tokens["admin"], submission["id"], True, "整改完成")
        public = self.market.get_product(product["id"])
        self.assertEqual(public["state"], "ON_SALE")
        owner_view = self.market.get_product(product["id"], self.tokens["seller"])
        self.assertFalse(owner_view["active_restriction"])
        self.assertEqual(
            self.market.get_reservation(self.tokens["buyer"], reservation["id"])
            ["state"], "CANCELLED",
        )
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM violations"), 1)

    def test_violation_after_completion_preserves_trade_and_statistics(self):
        product = self.published()
        reservation = self.confirmed(product)
        self.market.complete(self.tokens["seller"], reservation["id"], "complete")
        before = self.market.statistics(self.tokens["admin"])
        marked = self.market.mark_violation(
            self.tokens["admin"], product["id"], "成交后发现侵权"
        )
        self.assertEqual(marked["state"], "SOLD")
        self.assertEqual(self.market.statistics(self.tokens["admin"]), before)
        self.assertEqual(
            self.market.get_reservation(self.tokens["buyer"], reservation["id"])
            ["state"], "COMPLETED",
        )

    def test_ban_seller_revokes_all_sessions_and_unban_does_not_restore(self):
        private = self.draft(title="封禁期间保留私人草稿")
        free = self.published(title="无预约商品")
        occupied = self.published(title="已有预约商品")
        reservation = self.reservation(occupied)
        extra_session = self.market.login("seller", PASSWORD)["token"]
        self.market.ban_account(
            self.tokens["admin"], self.accounts["seller"]["id"], "多次发布违规物品"
        )
        for token in (self.tokens["seller"], extra_session):
            self.assert_denied(self.market.whoami, token)
        self.assert_denied(self.market.login, "seller", PASSWORD)
        states = {row["id"]: row["state"] for row in self.rows("SELECT id,state FROM products")}
        self.assertEqual(states[private["id"]], "DRAFT")
        self.assertEqual(states[free["id"]], "OFF_SHELF")
        self.assertEqual(states[occupied["id"]], "OFF_SHELF")
        self.assertEqual(
            self.market.get_reservation(self.tokens["buyer"], reservation["id"])
            ["state"], "CANCELLED",
        )
        self.market.unban_account(
            self.tokens["admin"], self.accounts["seller"]["id"], "复核后解除"
        )
        self.tokens["seller"] = self.market.login("seller", PASSWORD)["token"]
        self.assertEqual(self.market.list_products()["total"], 0)
        self.assertEqual(
            self.market.get_product(free["id"], self.tokens["seller"])["state"],
            "OFF_SHELF",
        )
        self.assert_denied(self.market.whoami, extra_session)

    def test_ban_buyer_releases_other_normal_sellers_product(self):
        product = self.published()
        reservation = self.reservation(product)
        self.market.ban_account(
            self.tokens["admin"], self.accounts["buyer"]["id"], "违约处理"
        )
        self.assertEqual(self.market.get_product(product["id"])["state"], "ON_SALE")
        closed = self.market.get_reservation(self.tokens["seller"], reservation["id"])
        self.assertEqual(closed["state"], "CANCELLED")
        self.assertIn("封禁", closed["close_reason"])

    def test_admin_cannot_mark_current_private_draft_or_ban_an_admin(self):
        private = self.draft()
        self.assert_denied(
            self.market.mark_violation, self.tokens["admin"], private["id"], "私人内容"
        )
        self.assert_denied(
            self.market.ban_account, self.tokens["admin"],
            self.accounts["admin"]["id"], "无权操作",
        )

    def test_management_reasons_are_required(self):
        product = self.published()
        self.assert_denied(
            self.market.mark_violation, self.tokens["admin"], product["id"], " "
        )
        self.assert_denied(
            self.market.ban_account, self.tokens["admin"],
            self.accounts["buyer"]["id"], " ",
        )

    def test_statistics_change_only_for_completed_snapshot(self):
        product = self.published(price="12.34")
        reservation = self.confirmed(product)
        pending = self.market.statistics(self.tokens["admin"])
        self.clock.advance(60)
        self.market.complete(self.tokens["seller"], reservation["id"], "complete")
        completed_at = self.clock()
        complete = self.market.statistics(self.tokens["admin"])
        self.assertNotEqual(complete, pending)
        exact = self.market.statistics(
            self.tokens["admin"], start=completed_at, end=completed_at
        )
        self.assertEqual(exact["completed"], 1)
        self.assertEqual(exact["amount_cents"], 1234)
        self.assertEqual(exact["categories"], complete["categories"])
        excluded = self.market.statistics(self.tokens["admin"], end=completed_at - 1)
        self.assertEqual(excluded["completed"], 0)
        self.assertEqual(excluded["amount_cents"], 0)
        self.assert_denied(
            self.market.statistics, self.tokens["admin"],
            start=completed_at + 1, end=completed_at,
        )
        actual = self.scalar(
            "SELECT snapshot_json FROM reservations WHERE state='COMPLETED'"
        )
        self.assertIn("12.34", actual)

    def test_seller_logs_include_admin_review_of_own_product(self):
        product = self.published()
        own = self.market.list_logs(self.tokens["seller"], object_id=product["id"])
        self.assertTrue(any(
            entry["actor_id"] == self.accounts["admin"]["id"]
            for entry in own["items"]
        ))
        unrelated = self.market.list_logs(self.tokens["other"], object_id=product["id"])
        self.assertEqual(unrelated["total"], 0)

    def test_log_filters_combine_time_actor_object_operation_and_result(self):
        product = self.published()
        self.clock.advance(10)
        self.market.mark_violation(self.tokens["admin"], product["id"], "违规内容")
        filters = {
            "operation": "mark_violation", "object_id": product["id"],
            "result": "SUCCESS", "actor_id": self.accounts["admin"]["id"],
            "start": self.clock(), "end": self.clock(),
        }
        filtered = self.market.list_logs(self.tokens["admin"], **filters)
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["operation"], "mark_violation")
        filters["end"] = self.clock() - 1
        self.assert_denied(self.market.list_logs, self.tokens["admin"], **filters)
        self.assert_denied(
            self.market.list_logs, self.tokens["buyer"],
            actor_id=self.accounts["other"]["id"],
        )
