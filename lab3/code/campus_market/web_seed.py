"""Persistent, explicitly identified fixtures for the local graphical demo.

The application never seeds an existing unmarked database. Credentials belong
only to fictional demo accounts and are kept in an owner-readable metadata file.
"""

import json
import os
import secrets
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from .models import DomainError
from .service import Market

DEMO_KIND = "campus-market-graphical-demo"
DEMO_VERSION = 1
METADATA_NAME = "demo-metadata.json"
DATABASE_NAME = "market.sqlite3"
PROFILE_NAMES = {"seller": "林同学", "buyer": "陈同学", "admin": "校园管理员"}

PUBLIC_LISTINGS = (
    (
        "软件工程教材",
        "教材书籍",
        "九成新",
        "38.50",
        "书页完整，重点章节有少量铅笔标记。图书馆门口面交。",
    ),
    ("机械键盘", "数码电子", "九成新", "129.00", "87 键有线键盘，所有按键正常，附原装线材。"),
    ("宿舍阅读台灯", "生活用品", "八成新", "45.00", "三档亮度可调，灯罩有轻微使用痕迹，光源正常。"),
    ("入门羽毛球拍", "体育器材", "九成新", "68.00", "适合日常运动，附拍套，握把胶可按习惯更换。"),
    ("入门尤克里里", "乐器", "八成新", "99.00", "四弦乐器，琴体完整，附便携琴包，适合入门练习。"),
    ("桌面文具收纳盒", "文具", "全新", "15.00", "闲置未使用，分格收纳，适合宿舍书桌。"),
    ("算法导论参考书", "教材书籍", "九成新", "42.00", "正版教材，无缺页，封面边角有轻微磨损。"),
    ("通勤帆布包", "其他", "九成新", "22.00", "可放下 A4 书本，已清洗，校内当面查看后交付。"),
)


def _market(directory):
    return Market(directory / DATABASE_NAME, outbox=directory / "outbox")


def _metadata(directory):
    """Read a marker and verify that its fictional identities match this DB."""
    marker = directory / METADATA_NAME
    database = directory / DATABASE_NAME
    if (
        not marker.is_file()
        or not database.is_file()
        or marker.is_symlink()
        or database.is_symlink()
    ):
        raise DomainError("DEMO_DIRECTORY", "此目录不是完整的图形演示库，请选择新的空目录")
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or data.get("kind") != DEMO_KIND
            or data.get("version") != DEMO_VERSION
        ):
            raise ValueError("Unrecognized demo marker")
        credentials = data["credentials"]
        account_ids = data["account_ids"]
        if not isinstance(credentials, dict) or not isinstance(account_ids, dict):
            raise ValueError("Invalid demo metadata")
        if set(credentials) != set(PROFILE_NAMES) or set(account_ids) != set(PROFILE_NAMES):
            raise ValueError("Incomplete demo profiles")
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            for profile, expected_name in PROFILE_NAMES.items():
                credential = credentials[profile]
                if not isinstance(credential, dict):
                    raise ValueError("Invalid credential format")
                if (
                    credential["identifier"] != expected_name
                    or not isinstance(credential["password"], str)
                    or not credential["password"]
                ):
                    raise ValueError("Invalid demo profile")
                row = connection.execute(
                    "SELECT username,role,email FROM accounts WHERE id=?", (account_ids[profile],)
                ).fetchone()
                expected_role = "ADMIN" if profile == "admin" else "USER"
                if row != (expected_name, expected_role, f"{profile}@campus.example"):
                    raise ValueError("Demo identities do not match database")
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        raise DomainError(
            "DEMO_DIRECTORY", "演示标记与数据库不匹配；保留原文件并选择新的空目录"
        ) from error
    marker.chmod(0o600)
    return credentials


def _verify_local_registration(market, result):
    """Consume the specific fictional account's development email."""
    account = result["account"]
    mail = json.loads((market.outbox / f"{account['id']}.json").read_text(encoding="utf-8"))
    market.verify_email(mail["verification_token"])
    return account


def _draft(market, seller_token, listing):
    title, category, condition, price, description = listing
    return market.save_draft(
        seller_token,
        {
            "title": title,
            "category": category,
            "condition": condition,
            "price": price,
            "description": description,
            "images": [],
        },
    )


def _submit(market, seller_token, product):
    return market.submit_product(
        seller_token, product["id"], product["row_version"], f"seed-submit-{product['id']}"
    )


def _publish(market, tokens, listing):
    product = _draft(market, tokens["seller"], listing)
    submission = _submit(market, tokens["seller"], product)
    market.review(tokens["admin"], submission["id"], True, "演示资料完整，符合发布规则")
    return market.get_product(product["id"])


def _create_fixtures(directory):
    """Create every identity and state through the real service boundary."""
    market = _market(directory)
    credentials = {
        profile: {"identifier": name, "password": secrets.token_urlsafe(24)}
        for profile, name in PROFILE_NAMES.items()
    }
    administrator = credentials["admin"]
    result = market.bootstrap_admin(
        administrator["identifier"], "admin@campus.example", "DEMO-ADMIN", administrator["password"]
    )
    market.verify_email(result["verification_token"])
    account_ids = {"admin": result["account"]["id"]}
    for profile in ("seller", "buyer"):
        credential = credentials[profile]
        result = market.register(
            credential["identifier"],
            f"{profile}@campus.example",
            f"DEMO-{profile.upper()}",
            credential["password"],
        )
        account_ids[profile] = _verify_local_registration(market, result)["id"]
    tokens = {
        profile: market.login(credential["identifier"], credential["password"])["token"]
        for profile, credential in credentials.items()
    }
    for listing in PUBLIC_LISTINGS:
        _publish(market, tokens, listing)
    review = _draft(
        market,
        tokens["seller"],
        (
            "折叠电脑支架",
            "数码电子",
            "九成新",
            "35.00",
            "铝合金支架，折叠关节牢固，等待管理员审核。",
        ),
    )
    _submit(market, tokens["seller"], review)
    _draft(
        market,
        tokens["seller"],
        ("手写笔记本", "文具", "全新", "12.00", "私人草稿，可先补充信息，再提交审核。"),
    )
    pending = _publish(
        market,
        tokens,
        ("计算机网络教材", "教材书籍", "八成新", "28.00", "保存完整，有课程笔记，校内面交。"),
    )
    market.reserve(
        tokens["buyer"],
        pending["id"],
        pending["content_version"],
        "周三下午图书馆门口面交。",
        "seed-pending",
    )
    confirmed = _publish(
        market,
        tokens,
        ("桌面蓝牙音箱", "数码电子", "九成新", "58.00", "播放正常，附充电线，可当面试听。"),
    )
    reservation = market.reserve(
        tokens["buyer"],
        confirmed["id"],
        confirmed["content_version"],
        "周五傍晚食堂门口面交。",
        "seed-confirmed",
    )
    market.confirm(tokens["seller"], reservation["id"], "seed-confirm")
    for token in tokens.values():
        market.logout(token)
    metadata = {
        "kind": DEMO_KIND,
        "version": DEMO_VERSION,
        "credentials": credentials,
        "account_ids": account_ids,
    }
    descriptor = os.open(directory / METADATA_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def prepare_demo(directory: Path):
    """Initialize a new demo atomically, or reopen it without resetting any data."""
    directory = Path(directory).expanduser().absolute()
    if directory.is_symlink():
        raise DomainError("DEMO_DIRECTORY", "演示数据目录不能是符号链接")
    if directory.exists() and not directory.is_dir():
        raise DomainError("DEMO_DIRECTORY", "演示数据路径必须是目录")
    if (directory / METADATA_NAME).exists():
        credentials = _metadata(directory)
        return _market(directory), credentials
    if directory.exists() and any(directory.iterdir()):
        raise DomainError("DEMO_DIRECTORY", "已有目录含其他文件，不能自动初始化演示库")
    directory.parent.mkdir(parents=True, exist_ok=True)
    lock = directory.with_name(f".{directory.name}.initializing")
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise DomainError("DEMO_BUSY", "演示库正在初始化，请稍后再次打开") from error
    os.close(descriptor)
    try:
        if directory.exists() and any(directory.iterdir()):
            raise DomainError("DEMO_DIRECTORY", "目标目录已发生变化，请重新打开")
        with tempfile.TemporaryDirectory(prefix=".campus-demo-", dir=directory.parent) as temporary:
            staging = Path(temporary)
            _create_fixtures(staging)
            os.replace(staging, directory)
        credentials = _metadata(directory)
        return _market(directory), credentials
    finally:
        lock.unlink(missing_ok=True)
