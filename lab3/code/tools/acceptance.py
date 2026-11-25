"""Record reproducible local-service load and contention acceptance evidence.

This exercises the real SQLite service on separate connections, not browsers or
human participants. Password hashing is not replaced or mocked. All fixtures and
verification mail are disposable; output contains no authentication credentials.
"""

import argparse
import json
import platform
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from campus_market.models import DomainError  # noqa: E402
from campus_market.service import Market  # noqa: E402


class Benchmark:
    """Prepare fixtures through public service operations, never direct inserts."""

    def __init__(self, root):
        self.db_path = root / "acceptance.sqlite3"
        self.outbox = root / "outbox"
        self.market = self.new_service()
        password = "Disposable-Acceptance-2026!"
        admin = self.market.bootstrap_admin("admin", "admin@campus.example", "ADMIN", password)
        self.market.verify_email(admin["verification_token"])
        self.tokens = {"admin": self.market.login("admin", password)["token"]}
        for name in ("seller", "buyer", "other"):
            existing = set(self.outbox.glob("*.json"))
            self.market.register(name, f"{name}@campus.example", name, password)
            new_mail = set(self.outbox.glob("*.json")) - existing
            if len(new_mail) != 1:
                raise RuntimeError("Expected exactly one local verification message")
            message = json.loads(new_mail.pop().read_text(encoding="utf-8"))
            self.market.verify_email(message["verification_token"])
            self.tokens[name] = self.market.login(name, password)["token"]

    def new_service(self):
        return Market(self.db_path, outbox=self.outbox)

    def publish(self, index):
        draft = self.market.save_draft(
            self.tokens["seller"],
            {
                "title": f"性能教材 {index:04d}",
                "category": "教材书籍",
                "condition": "九成新",
                "price": "25.50",
                "description": "校园面交测试样本",
                "images": [],
            },
        )
        submission = self.market.submit_product(
            self.tokens["seller"], draft["id"], draft["row_version"], f"submit-{index}"
        )
        self.market.review(self.tokens["admin"], submission["id"], True, "测试样本资料完整")
        return self.market.get_product(draft["id"])

    def product_state(self, product_id):
        with closing(sqlite3.connect(self.db_path)) as connection:
            return connection.execute(
                "SELECT state FROM products WHERE id=?", (product_id,)
            ).fetchone()[0]


def timed_call(index, inputs, call):
    """Record each request's wall start and actual service elapsed time."""
    started = datetime.now(UTC).isoformat()
    timer = time.perf_counter()
    try:
        value = call()
        result = {"success": True, "result": value}
    except DomainError as error:
        result = {"success": False, "error": error.code}
    elapsed = time.perf_counter() - timer
    return {
        "index": index,
        "inputs": inputs,
        "started_at_utc": started,
        "elapsed_seconds": round(elapsed, 6),
        **result,
    }


def summarize(samples):
    durations = sorted(sample["elapsed_seconds"] for sample in samples)
    within = sum(sample["success"] and sample["elapsed_seconds"] <= 2 for sample in samples)
    return {
        "samples": len(samples),
        "successful": sum(sample["success"] for sample in samples),
        "successful_within_2_seconds": within,
        "passes_95_of_100": len(samples) == 100 and within >= 95,
        "mean_seconds": round(statistics.mean(durations), 6),
        "p95_seconds": durations[94],
        "max_seconds": max(durations),
    }


def load_samples(benchmark, products):
    services = [benchmark.new_service() for _ in range(20)]

    def query(index):
        inputs = {"keyword": "性能", "category": "教材书籍", "min_price": "20", "max_price": "30"}

        def run():
            result = services[index % 20].list_products(**inputs)
            return {"total": result["total"], "returned": len(result["items"])}

        return timed_call(index, inputs, run)

    def reserve(index):
        product = products[index]
        inputs = {
            "product_id": product["id"],
            "content_version": product["content_version"],
            "message": "周三下午校园面交",
            "request_key": f"load-{index}",
        }

        def run():
            result = services[index % 20].reserve(benchmark.tokens["buyer"], **inputs)
            return {"reservation_id": result["id"], "state": result["state"]}

        return timed_call(index, inputs, run)

    with ThreadPoolExecutor(max_workers=20) as executor:
        queries = list(executor.map(query, range(100)))
    with ThreadPoolExecutor(max_workers=20) as executor:
        reservations = list(executor.map(reserve, range(100)))
    return {
        "query_summary": summarize(queries),
        "reservation_summary": summarize(reservations),
        "query_samples": queries,
        "reservation_samples": reservations,
    }


def contention_samples(benchmark, products):
    rounds = []
    services = [benchmark.new_service(), benchmark.new_service()]
    for number, product in enumerate(products[100:110]):
        barrier = threading.Barrier(2)

        def reserve(index, product=product, number=number, barrier=barrier):
            name = ("buyer", "other")[index]
            inputs = {
                "product_id": product["id"],
                "content_version": product["content_version"],
                "message": "双买家竞争测试",
                "request_key": f"race-{number}",
            }
            barrier.wait(timeout=10)
            return timed_call(
                index, inputs, lambda: services[index].reserve(benchmark.tokens[name], **inputs)
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(reserve, (0, 1)))
        winners = [sample for sample in results if sample["success"]]
        replays = []
        for retry in range(5):
            with ThreadPoolExecutor(max_workers=2) as executor:
                repeated = list(executor.map(reserve, (0, 1)))
            replays.append({"retry": retry + 1, "requests": repeated})
        valid = len(winners) == 1
        if valid:
            winner = winners[0]
            for repeated in replays:
                for request in repeated["requests"]:
                    if request["index"] == winner["index"]:
                        valid = (
                            valid
                            and request["success"]
                            and (request["result"]["id"] == winner["result"]["id"])
                        )
                    else:
                        valid = valid and not request["success"]
        state = benchmark.product_state(product["id"])
        with closing(sqlite3.connect(benchmark.db_path)) as connection:
            reservation_count = connection.execute(
                "SELECT COUNT(*) FROM reservations WHERE product_id=?", (product["id"],)
            ).fetchone()[0]
        audit = benchmark.market.list_logs(
            benchmark.tokens["admin"], operation="reserve", object_id=product["id"]
        )
        rounds.append(
            {
                "round": number + 1,
                "requests": results,
                "retries_per_buyer": 5,
                "both_buyers_retries": replays,
                "reservation_count": reservation_count,
                "audit_logs": audit["items"],
                "product_state": state,
                "passed": valid and state == "PENDING" and reservation_count == 1,
            }
        )
    return rounds


def cancel_confirm_samples(benchmark, products):
    """Cover both deterministic arrival orders plus true simultaneous calls."""
    rounds = []
    services = [benchmark.new_service(), benchmark.new_service()]
    scenarios = (
        "cancel_first",
        "confirm_first_with_reason",
        "confirm_first_no_reason",
        "simultaneous",
    )
    for number, product in enumerate(products[110:120]):
        reservation = benchmark.market.reserve(
            benchmark.tokens["buyer"],
            product["id"],
            product["content_version"],
            "取消确认顺序测试",
            f"cancel-confirm-reserve-{number}",
        )
        scenario = scenarios[number % len(scenarios)]
        reason = "面交时间冲突" if scenario in ("confirm_first_with_reason", "simultaneous") else ""
        barrier = threading.Barrier(2) if scenario == "simultaneous" else None

        def cancel(reservation=reservation, number=number, reason=reason, barrier=barrier):
            inputs = {
                "reservation_id": reservation["id"],
                "request_key": f"cancel-{number}",
                "reason": reason,
            }
            if barrier is not None:
                barrier.wait(timeout=10)
            return timed_call(
                0, inputs, lambda: services[0].cancel(benchmark.tokens["buyer"], **inputs)
            )

        def confirm(reservation=reservation, number=number, barrier=barrier):
            inputs = {"reservation_id": reservation["id"], "request_key": f"confirm-{number}"}
            if barrier is not None:
                barrier.wait(timeout=10)
            return timed_call(
                1, inputs, lambda: services[1].confirm(benchmark.tokens["seller"], **inputs)
            )

        if scenario == "simultaneous":
            with ThreadPoolExecutor(max_workers=2) as executor:
                cancel_future = executor.submit(cancel)
                confirm_future = executor.submit(confirm)
                cancelled, confirmed = cancel_future.result(), confirm_future.result()
        elif scenario == "cancel_first":
            cancelled, confirmed = cancel(), confirm()
        else:
            confirmed, cancelled = confirm(), cancel()
        current = benchmark.market.get_reservation(benchmark.tokens["buyer"], reservation["id"])
        expected = "CONFIRMED" if scenario == "confirm_first_no_reason" else "CANCELLED"
        product_state = benchmark.product_state(product["id"])
        passed = current["state"] == expected and product_state == (
            "CONFIRMED" if expected == "CONFIRMED" else "ON_SALE"
        )
        if scenario == "cancel_first":
            passed = passed and cancelled["success"] and not confirmed["success"]
        elif scenario == "confirm_first_no_reason":
            passed = passed and confirmed["success"] and not cancelled["success"]
        elif scenario == "confirm_first_with_reason":
            passed = passed and cancelled["success"] and confirmed["success"]
        else:
            passed = passed and cancelled["success"]
        rounds.append(
            {
                "round": number + 1,
                "scenario": scenario,
                "cancel": cancelled,
                "confirm": confirmed,
                "reservation_state": current["state"],
                "product_state": product_state,
                "audit_logs": benchmark.market.list_logs(
                    benchmark.tokens["admin"], object_id=product["id"]
                )["items"],
                "passed": passed,
            }
        )
    return rounds


def main(argv=None):
    parser = argparse.ArgumentParser(description="记录本机 API 负载测试及跨连接竞争原始样本")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="campus-acceptance-") as temporary:
        benchmark = Benchmark(Path(temporary))
        products = []
        for index in range(1000):
            products.append(benchmark.publish(index))
            if (index + 1) % 250 == 0:
                print(f"Prepared {index + 1} / 1000 published items", flush=True)
        output = {
            "environment": {
                "recorded_at_utc": datetime.now(UTC).isoformat(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
                "mode": "local Python service API; SQLite; fresh connections per operation",
                "concurrency": 20,
                "initial_published_products": 1000,
                "network": "none; in-process service calls",
                "browser": "not applicable",
                "limitations": "Does not measure browser/UI/network or human usability acceptance.",
            },
            **load_samples(benchmark, products),
        }
        output["buyer_contention_rounds"] = contention_samples(benchmark, products)
        output["cancel_confirm_rounds"] = cancel_confirm_samples(benchmark, products)
        output["passed"] = (
            output["query_summary"]["passes_95_of_100"]
            and output["reservation_summary"]["passes_95_of_100"]
            and all(item["passed"] for item in output["buyer_contention_rounds"])
            and all(item["passed"] for item in output["cancel_confirm_rounds"])
        )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {key: output[key] for key in ("query_summary", "reservation_summary", "passed")},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
