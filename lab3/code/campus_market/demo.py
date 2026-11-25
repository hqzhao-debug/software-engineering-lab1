"""Reproducible end-to-end demonstration using a separate local database.

All accounts and items in this module are synthetic. Verification reads only the
local development mailbox created for the isolated demonstration database.
"""

from __future__ import annotations

import argparse
import json
import secrets
import tempfile
from pathlib import Path
from typing import Any

from .models import DomainError
from .service import Market


def print_step(step: int, title: str, result: Any) -> None:
    """Produce evidence without passwords, verification codes or session tokens."""
    print(json.dumps({"step": step, "action": title, "result": result}, ensure_ascii=False))


def local_token(outbox: Path, account_id: str) -> str:
    """Read this synthetic user's development email, not an external inbox."""
    for path in outbox.glob("*.json"):
        mail = json.loads(path.read_text(encoding="utf-8"))
        if mail.get("account_id") == account_id:
            return mail["verification_token"]
    raise RuntimeError("演示账号的本地验证邮件未生成")


def verified_user(market: Market, outbox: Path, name: str) -> dict[str, Any]:
    """Register, verify and log in one synthetic ordinary account."""
    password = secrets.token_urlsafe(24)
    created = market.register(name, f"{name}@campus.example", f"demo-{name}", password)
    market.verify_email(local_token(outbox, created["account"]["id"]))
    return market.login(name, password)


def new_listing(market: Market, seller: str, admin: str, title: str, price: str) -> dict[str, Any]:
    """Create a draft and complete a real review, returning the published item."""
    draft = market.save_draft(
        seller,
        {
            "title": title,
            "category": "教材书籍",
            "condition": "九成新",
            "price": price,
            "description": "演示用虚构商品；校内面交，不含支付或配送。",
            "images": [],
        },
    )
    submission = market.submit_product(
        seller,
        draft["id"],
        draft["row_version"],
        f"submit-{draft['id']}",
    )
    market.review(admin, submission["id"], True, "演示审核：资料完整，允许发布")
    return market.get_product(draft["id"])


def demonstrate(directory: Path) -> dict[str, Any]:
    """Exercise success, idempotent replay, denial and history on disk."""
    directory.mkdir(parents=True, exist_ok=True)
    database = directory / "demo.sqlite3"
    if database.exists():
        raise DomainError("DEMO_EXISTS", "演示数据库已存在；请选择新的目录，不会覆盖已有数据")
    outbox = directory / "outbox"
    market = Market(database, outbox=outbox)
    admin_password = secrets.token_urlsafe(24)
    bootstrap = market.bootstrap_admin(
        "demo_admin",
        "demo_admin@campus.example",
        "demo-admin",
        admin_password,
    )
    market.verify_email(bootstrap["verification_token"])
    admin = market.login("demo_admin", admin_password)
    seller = verified_user(market, outbox, "demo_seller")
    buyer = verified_user(market, outbox, "demo_buyer")
    print_step(
        1,
        "初始化管理员与两个已验证普通账号",
        {
            "accounts": [admin["account"]["id"], seller["account"]["id"], buyer["account"]["id"]],
            "mail_adapter": "local development outbox",
        },
    )

    product = new_listing(market, seller["token"], admin["token"], "软件工程教材", "38.50")
    print_step(
        2,
        "草稿提交、管理员审核通过并公开上架",
        {
            "id": product["id"],
            "state": product["state"],
            "content_version": product["content_version"],
            "content": product["content"],
        },
    )
    query = market.list_products(
        keyword="软件工程", category="教材书籍", min_price="30", max_price="40"
    )
    if query["total"] != 1:
        raise AssertionError("组合查询未返回预期唯一商品")
    print_step(3, "关键词、分类和金额区间组合查询", {"total": query["total"]})

    reservation = market.reserve(
        buyer["token"],
        product["id"],
        product["content_version"],
        "周三下午在校园图书馆门口面交",
        "demo-reserve-1",
    )
    repeated = market.reserve(
        buyer["token"],
        product["id"],
        product["content_version"],
        "周三下午在校园图书馆门口面交",
        "demo-reserve-1",
    )
    if repeated["id"] != reservation["id"]:
        raise AssertionError("幂等重试产生了另一条预约")
    print_step(
        4,
        "买家预约并验证同键重试",
        {
            "id": reservation["id"],
            "state": reservation["state"],
            "same_id": True,
        },
    )
    try:
        market.confirm(buyer["token"], reservation["id"], "demo-illegal-confirm")
    except DomainError as exc:
        print_step(5, "买家尝试卖家确认操作被拒绝", {"error": exc.code})
    else:
        raise AssertionError("买家越权确认未被拒绝")

    confirmed = market.confirm(seller["token"], reservation["id"], "demo-confirm-1")
    print_step(6, "卖家确认，商品同步进入已确认", {"state": confirmed["state"]})
    completed = market.complete(seller["token"], reservation["id"], "demo-complete-1")
    if completed["state"] != "COMPLETED":
        raise AssertionError("完成状态不正确")
    replayed = market.reserve(
        buyer["token"],
        product["id"],
        product["content_version"],
        "周三下午在校园图书馆门口面交",
        "demo-reserve-1",
    )
    if replayed["state"] != "COMPLETED":
        raise AssertionError("成功预约的迟到重试未返回当前终态")
    print_step(
        7,
        "卖家完成；迟到预约重试返回当前终态",
        {
            "reservation": completed["state"],
            "replay": replayed["state"],
        },
    )
    statistics = market.statistics(admin["token"])
    if statistics["completed"] != 1 or statistics["amount_cents"] != 3850:
        raise AssertionError("成交数量或快照金额统计不正确")
    print_step(8, "按快照统计一次成交", statistics)

    second = new_listing(market, seller["token"], admin["token"], "算法学习笔记", "12.00")
    pending = market.reserve(
        buyer["token"],
        second["id"],
        second["content_version"],
        "周末校内面交",
        "demo-reserve-2",
    )
    cancelled = market.cancel(buyer["token"], pending["id"], "demo-cancel-2")
    if cancelled.get("counterparty_email"):
        raise AssertionError("取消后仍然返回对方邮箱")
    released = market.get_product(second["id"])
    print_step(
        9,
        "待确认买家取消，隐藏邮箱并释放商品",
        {
            "reservation": cancelled["state"],
            "product": released["state"],
            "counterparty_email_visible": bool(cancelled.get("counterparty_email")),
        },
    )

    market.mark_violation(admin["token"], product["id"], "演示：成交后补充违规记录")
    if market.get_reservation(seller["token"], reservation["id"])["state"] != "COMPLETED":
        raise AssertionError("成交后违规错误回退交易")
    after_violation = market.statistics(admin["token"])
    if after_violation["completed"] != 1 or after_violation["amount_cents"] != 3850:
        raise AssertionError("成交后违规错误改变成交统计")
    print_step(10, "成交后违规保留完成状态和统计", after_violation)

    reopened = Market(database, outbox=outbox)
    recovered = reopened.get_reservation(seller["token"], reservation["id"])
    logs = reopened.list_logs(admin["token"], object_id=reservation["id"])
    if recovered["state"] != "COMPLETED" or not logs["total"]:
        raise AssertionError("重开数据库未能恢复完整交易和日志")
    print_step(
        11,
        "新服务实例读取持久化交易和操作日志",
        {
            "reservation_state": recovered["state"],
            "related_log_count": logs["total"],
        },
    )
    summary = {
        "status": "PASS",
        "checks": 11,
        "database": str(database.resolve()),
        "completed_reservation": reservation["id"],
        "note": "本地自动化演示；不是人工验收或真实邮箱验证。",
    }
    print_step(12, "演示结束", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    """Use a temporary database by default, or retain an explicitly chosen one."""
    parser = argparse.ArgumentParser(description="校园循物完整业务演示；不会覆盖已有数据库")
    parser.add_argument("--directory", help="保留演示数据库和本地邮件的独立新目录")
    args = parser.parse_args(argv)
    try:
        if args.directory:
            demonstrate(Path(args.directory).expanduser())
        else:
            with tempfile.TemporaryDirectory(prefix="campus-market-demo-") as temp:
                demonstrate(Path(temp))
            print(json.dumps({"temporary_data": "removed"}, ensure_ascii=False))
    except (DomainError, OSError, AssertionError, RuntimeError) as exc:
        print(
            json.dumps(
                {"status": "FAIL", "type": type(exc).__name__, "message": str(exc)},
                ensure_ascii=False,
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
