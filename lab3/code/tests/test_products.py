"""Product validation, revision isolation, and role-specific visibility."""

import base64
import json

from campus_market.models import DomainError, money_cents, validate_content
from tests.helpers import MarketCase


class ProductTests(MarketCase):
    def test_minimal_private_draft_and_persistent_update(self):
        draft = self.market.save_draft(self.tokens["seller"], {"title": "书"})
        self.assertEqual(draft["state"], "DRAFT")
        self.assert_denied(
            self.market.submit_product, self.tokens["seller"], draft["id"],
            draft["row_version"], "incomplete",
        )
        updated = self.market.save_draft(
            self.tokens["seller"], self.content(), draft["id"], draft["row_version"]
        )
        self.assertEqual(updated["id"], draft["id"])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM products"), 1)
        self.assertEqual(
            self.new_market().get_product(draft["id"], self.tokens["seller"])
            ["content"]["title"], "软件工程教材",
        )

    def test_only_never_submitted_draft_can_be_deleted(self):
        draft = self.draft()
        self.market.delete_draft(
            self.tokens["seller"], draft["id"], draft["row_version"]
        )
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM products"), 0)
        draft = self.draft()
        self.market.submit_product(
            self.tokens["seller"], draft["id"], draft["row_version"], "submit"
        )
        current = self.market.get_product(draft["id"], self.tokens["seller"])
        withdrawn = self.market.withdraw_product(
            self.tokens["seller"], draft["id"], current["row_version"]
        )
        self.assert_denied(
            self.market.delete_draft, self.tokens["seller"], draft["id"],
            withdrawn["row_version"],
        )
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM submitted_versions"), 1)

    def test_stale_edit_cannot_overwrite_new_content(self):
        draft = self.draft()
        new = self.market.save_draft(
            self.tokens["seller"], self.content(title="新版软件教材"),
            draft["id"], draft["row_version"],
        )
        self.assertGreater(new["row_version"], draft["row_version"])
        self.assert_denied(
            self.market.save_draft, self.tokens["seller"],
            self.content(title="过期页面旧内容"), draft["id"], draft["row_version"],
        )
        actual = self.market.get_product(draft["id"], self.tokens["seller"])
        self.assertEqual(actual["content"]["title"], "新版软件教材")

    def test_current_draft_not_visible_to_other_user_or_admin(self):
        draft = self.draft(description="私人草稿保密内容")
        for token in (None, self.tokens["buyer"], self.tokens["admin"]):
            with self.subTest(token=token):
                self.assert_denied(self.market.get_product, draft["id"], token)
        self.assertEqual(self.market.list_products()["total"], 0)
        admin_list = self.market.list_products(
            self.tokens["admin"], scope="admin"
        )
        self.assertNotIn("私人草稿保密内容", json.dumps(admin_list, ensure_ascii=False))

    def test_admin_sees_submitted_a_but_not_unsubmitted_b(self):
        draft = self.draft(title="公开提交版本甲", price="12.00")
        first = self.market.submit_product(
            self.tokens["seller"], draft["id"], draft["row_version"], "first"
        )
        current = self.market.get_product(draft["id"], self.tokens["seller"])
        withdrawn = self.market.withdraw_product(
            self.tokens["seller"], draft["id"], current["row_version"]
        )
        updated = self.market.save_draft(
            self.tokens["seller"],
            self.content(title="绝密未提交版本乙", price="7777.77"),
            draft["id"], withdrawn["row_version"],
        )
        for view in (
            self.market.get_product(draft["id"], self.tokens["admin"]),
            self.market.product_history(self.tokens["admin"], draft["id"]),
            self.market.list_products(self.tokens["admin"], scope="admin"),
            self.market.list_logs(self.tokens["admin"], object_id=draft["id"]),
        ):
            serialized = json.dumps(view, ensure_ascii=False)
            self.assertNotIn("绝密未提交版本乙", serialized)
            self.assertNotIn("7777.77", serialized)
        second = self.market.submit_product(
            self.tokens["seller"], draft["id"], updated["row_version"], "second"
        )
        self.assertNotEqual(first["id"], second["id"])
        visible = self.market.get_product(draft["id"], self.tokens["admin"])
        self.assertEqual(visible["content"]["title"], "绝密未提交版本乙")
        self.assert_denied(
            self.market.review, self.tokens["admin"], first["id"], True, "过期审核"
        )
        self.assertEqual(
            self.market.get_product(draft["id"], self.tokens["seller"])["state"],
            "REVIEW",
        )

    def test_review_requires_reason_and_locks_pending_content(self):
        draft = self.draft()
        submission = self.market.submit_product(
            self.tokens["seller"], draft["id"], draft["row_version"], "submit"
        )
        for decision in (True, False):
            self.assert_denied(
                self.market.review, self.tokens["admin"], submission["id"],
                decision, "   ",
            )
        current = self.market.get_product(draft["id"], self.tokens["seller"])
        self.assert_denied(
            self.market.save_draft, self.tokens["seller"], self.content(price="6"),
            draft["id"], current["row_version"],
        )
        self.market.review(self.tokens["admin"], submission["id"], False, "描述不符")
        self.assertEqual(
            self.market.get_product(draft["id"], self.tokens["seller"])["state"],
            "REJECTED",
        )

    def test_submit_replay_does_not_create_extra_version_or_batch(self):
        draft = self.draft()
        first = self.market.submit_product(
            self.tokens["seller"], draft["id"], draft["row_version"], "submit"
        )
        second = self.market.submit_product(
            self.tokens["seller"], draft["id"], draft["row_version"], "submit"
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM review_submissions"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM submitted_versions"), 1)

    def test_edit_on_sale_hides_product_and_rejects_stale_reservation(self):
        product = self.published()
        edited = self.market.save_draft(
            self.tokens["seller"], self.content(price="30"),
            product["id"], product["row_version"],
        )
        self.assertEqual(edited["state"], "DRAFT")
        self.assert_denied(self.market.get_product, product["id"])
        self.assert_denied(
            self.market.reserve, self.tokens["buyer"], product["id"],
            product["content_version"], "面交", "stale",
        )

    def test_off_shelf_requires_new_review_before_publication(self):
        product = self.published()
        hidden = self.market.off_shelf(
            self.tokens["seller"], product["id"], product["row_version"]
        )
        self.assertEqual(hidden["state"], "OFF_SHELF")
        self.assert_denied(self.market.get_product, product["id"])
        submission = self.market.submit_product(
            self.tokens["seller"], product["id"], hidden["row_version"], "resubmit"
        )
        self.assertEqual(self.market.list_products()["total"], 0)
        self.market.review(self.tokens["admin"], submission["id"], True, "重新检查")
        self.assertEqual(self.market.list_products()["total"], 1)

    def test_public_search_applies_combined_filters_and_price_boundaries(self):
        self.published(title="算法教材", price="10.00")
        self.published(title="算法参考书", price="20.00")
        self.published(title="篮球", category="体育器材", price="10.00")
        result = self.market.list_products(
            keyword="算法", category="教材书籍", min_price="10", max_price="20",
            sort="price_desc",
        )
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["page_size"], 20)
        self.assertEqual(
            [item["content"]["price"] for item in result["items"]],
            ["20.00", "10.00"],
        )
        self.assert_denied(self.market.list_products, min_price="20", max_price="10")
        self.assertNotIn("@campus.example", json.dumps(result))

    def test_image_access_follows_private_public_and_historical_references(self):
        path = self.root / "pixel.png"
        path.write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
            "/x8AAwMCAO+aN1sAAAAASUVORK5CYII="
        ))
        image = self.market.upload_image(self.tokens["seller"], path)
        self.assert_denied(self.market.read_image, image["id"])
        self.assert_denied(self.market.read_image, image["id"], self.tokens["admin"])
        product = self.published(images=[image["id"]])
        self.assertEqual(self.market.read_image(image["id"])["data"], path.read_bytes())
        reservation = self.reservation(product)
        self.assert_denied(self.market.read_image, image["id"])
        self.market.cancel(self.tokens["buyer"], reservation["id"], "cancel")
        current = self.market.get_product(product["id"], self.tokens["seller"])
        self.market.save_draft(
            self.tokens["seller"], self.content(images=[]),
            product["id"], current["row_version"],
        )
        self.assertEqual(
            self.market.read_image(image["id"], self.tokens["buyer"])["data"],
            path.read_bytes(),
        )
        self.assert_denied(self.market.read_image, image["id"], self.tokens["other"])


class InputBoundaryTests(MarketCase):
    def test_money_boundaries_and_non_finite_values(self):
        self.assertEqual(money_cents("0.01"), 1)
        self.assertEqual(money_cents("99999.99"), 9_999_999)
        self.assertEqual(money_cents("0", allow_zero=True), 0)
        for value in ("0", "-1", "100000", "1.001", "NaN", "Infinity", "abc"):
            with self.subTest(value=value):
                with self.assertRaises(DomainError):
                    money_cents(value)

    def test_title_description_category_and_condition_boundaries(self):
        for length in (2, 50):
            validate_content(self.content(title="字" * length), complete=True)
        validate_content(self.content(description="字" * 500), complete=True)
        for content in (
            self.content(title="字"), self.content(title="字" * 51),
            self.content(description="字" * 501), self.content(category="食品饮料"),
            self.content(condition="六成新"), self.content(price="1.001"),
            self.content(images=["a"] * 6),
        ):
            with self.subTest(content=content):
                with self.assertRaises(DomainError):
                    validate_content(content, complete=True)

    def test_invalid_content_does_not_replace_saved_draft(self):
        draft = self.draft()
        before = self.business_snapshot()
        self.assert_denied(
            self.market.save_draft, self.tokens["seller"], self.content(price="NaN"),
            draft["id"], draft["row_version"],
        )
        self.assertEqual(self.business_snapshot(), before)

    def test_images_must_be_valid_format_size_and_owned(self):
        invalid = self.root / "fake.png"
        invalid.write_bytes(b"not a real image")
        self.assert_denied(self.market.upload_image, self.tokens["seller"], invalid)
        oversized = self.root / "oversized.png"
        oversized.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024))
        self.assert_denied(self.market.upload_image, self.tokens["seller"], oversized)
        self.assert_denied(
            self.market.save_draft, self.tokens["seller"],
            self.content(images=["nonexistent-image-id"]),
        )
