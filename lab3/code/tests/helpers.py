"""Isolated, real-database fixtures shared by integration tests."""

import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from campus_market.models import DomainError
from campus_market.service import Market


PASSWORD = "Course-Test-2026!"
DOMAIN = "campus.example"
START_TIME = 1_800_000_000.0


class Clock:
    """A manually advanced clock; security tests never need real sleeps."""

    def __init__(self, value=START_TIME):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def verification_token(outbox, previous_paths=()):
    """Read only newly generated local-development verification mail."""
    candidates = set(Path(outbox).glob("*.json")) - set(previous_paths)
    if len(candidates) != 1:
        raise AssertionError(f"Expected one new verification mail, got {candidates}")
    message = json.loads(candidates.pop().read_text(encoding="utf-8"))
    return message["verification_token"]


class MarketCase(unittest.TestCase):
    """Copy a verified-account baseline into a fresh database for each test."""

    @classmethod
    def setUpClass(cls):
        cls.seed_directory = tempfile.TemporaryDirectory(prefix="market-test-seed-")
        seed_root = Path(cls.seed_directory.name)
        cls.seed_db = seed_root / "seed.sqlite3"
        seed_outbox = seed_root / "outbox"
        seed = Market(
            cls.seed_db, email_domain=DOMAIN, clock=Clock(), outbox=seed_outbox
        )
        initial = seed.bootstrap_admin(
            "admin", f"admin@{DOMAIN}", "ADMIN-1", PASSWORD
        )
        seed.verify_email(initial["verification_token"])
        cls.seed_accounts = {}
        cls.seed_tokens = {}
        for name in ("admin", "seller", "buyer", "other"):
            if name != "admin":
                previous = set(seed_outbox.glob("*.json"))
                seed.register(name, f"{name}@{DOMAIN}", f"ID-{name}", PASSWORD)
                seed.verify_email(verification_token(seed_outbox, previous))
            logged_in = seed.login(name, PASSWORD)
            cls.seed_accounts[name] = logged_in["account"]
            cls.seed_tokens[name] = logged_in["token"]

    @classmethod
    def tearDownClass(cls):
        cls.seed_directory.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="market-test-")
        self.root = Path(self.directory.name)
        self.db_path = self.root / "market.sqlite3"
        with closing(sqlite3.connect(self.seed_db)) as source:
            with closing(sqlite3.connect(self.db_path)) as target:
                source.backup(target)
        self.clock = Clock()
        self.outbox = self.root / "outbox"
        self.market = self.new_market()
        self.tokens = dict(self.seed_tokens)
        self.accounts = dict(self.seed_accounts)

    def tearDown(self):
        self.directory.cleanup()

    def new_market(self):
        return Market(
            self.db_path, email_domain=DOMAIN, clock=self.clock, outbox=self.outbox
        )

    def rows(self, sql, parameters=()):
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, parameters)]

    def scalar(self, sql, parameters=()):
        with closing(sqlite3.connect(self.db_path)) as connection:
            return connection.execute(sql, parameters).fetchone()[0]

    def content(self, **changes):
        result = {
            "title": "软件工程教材",
            "category": "教材书籍",
            "condition": "九成新",
            "price": "25.50",
            "description": "无缺页，校园当面交付。",
            "images": [],
        }
        result.update(changes)
        return result

    def draft(self, owner="seller", **changes):
        return self.market.save_draft(self.tokens[owner], self.content(**changes))

    def published(self, owner="seller", **changes):
        product = self.draft(owner, **changes)
        submission = self.market.submit_product(
            self.tokens[owner], product["id"], product["row_version"],
            f"submit-{product['id']}",
        )
        self.market.review(
            self.tokens["admin"], submission["id"], True, "资料完整，符合发布规定"
        )
        return self.market.get_product(product["id"], self.tokens[owner])

    def reservation(self, product=None, buyer="buyer", key="reserve-1"):
        product = product or self.published()
        return self.market.reserve(
            self.tokens[buyer], product["id"], product["content_version"],
            "周三下午图书馆门口面交", key,
        )

    def confirmed(self, product=None):
        reservation = self.reservation(product)
        return self.market.confirm(
            self.tokens["seller"], reservation["id"], "confirm-1"
        )

    def assert_denied(self, callable_, *args, **kwargs):
        with self.assertRaises(DomainError):
            callable_(*args, **kwargs)

    def business_snapshot(self):
        """Exclude audit/session/security counters from business comparisons."""
        return {
            table: self.rows(f"SELECT * FROM {table} ORDER BY id")
            for table in (
                "products", "submitted_versions", "review_submissions",
                "reservations", "violations", "bans",
            )
        }
