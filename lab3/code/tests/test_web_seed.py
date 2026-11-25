"""Verify persistent GUI fixtures never overwrite an unrelated database."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from campus_market.models import DomainError
from campus_market.web_seed import DATABASE_NAME, METADATA_NAME, prepare_demo


class GraphicalDemoSeedTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="market-gui-seed-test-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_fixtures_offer_market_review_draft_and_two_reservation_stages(self):
        directory = self.root / "新的 演示目录"
        market, credentials = prepare_demo(directory)
        self.assertEqual(set(credentials), {"buyer", "seller", "admin"})
        self.assertEqual(market.list_products()["total"], 8)
        seller = market.login(**credentials["seller"])
        products = market.list_products(seller["token"], scope="mine")["items"]
        states = {product["state"] for product in products}
        self.assertTrue({"DRAFT", "REVIEW", "PENDING", "CONFIRMED", "ON_SALE"} <= states)
        reservations = market.list_reservations(seller["token"], side="seller")["items"]
        self.assertEqual({entry["state"] for entry in reservations}, {"PENDING", "CONFIRMED"})
        self.assertEqual((directory / METADATA_NAME).stat().st_mode & 0o777, 0o600)

    def test_reopening_preserves_user_changes_and_does_not_reseed(self):
        directory = self.root / "demo"
        market, credentials = prepare_demo(directory)
        seller = market.login(**credentials["seller"])
        product = market.save_draft(seller["token"], {"title": "本次操作应当保留"})
        first_count = market.list_products(seller["token"], scope="mine")["total"]
        reopened, saved_credentials = prepare_demo(directory)
        self.assertEqual(credentials, saved_credentials)
        self.assertEqual(
            reopened.get_product(product["id"], seller["token"])["content"]["title"],
            "本次操作应当保留",
        )
        self.assertEqual(
            reopened.list_products(seller["token"], scope="mine")["total"], first_count
        )

    def test_unmarked_database_is_rejected_without_modifying_its_bytes(self):
        directory = self.root / "existing"
        directory.mkdir()
        database = directory / DATABASE_NAME
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE valuable_data (value TEXT)")
            connection.execute("INSERT INTO valuable_data VALUES ('keep this data')")
            connection.commit()
        before = database.read_bytes()
        with self.assertRaises(DomainError):
            prepare_demo(directory)
        self.assertEqual(database.read_bytes(), before)
        self.assertFalse((directory / METADATA_NAME).exists())

    def test_corrupted_marker_is_rejected_and_existing_database_is_preserved(self):
        directory = self.root / "demo"
        prepare_demo(directory)
        database = directory / DATABASE_NAME
        marker = directory / METADATA_NAME
        before = database.read_bytes()
        data = json.loads(marker.read_text())
        data["kind"] = "not-the-demo"
        marker.write_text(json.dumps(data))
        with self.assertRaises(DomainError):
            prepare_demo(directory)
        self.assertEqual(database.read_bytes(), before)
