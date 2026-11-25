"""Chinese command-line interface for the local campus marketplace.

The interface delegates every authorization and state check to ``Market``.
Session files contain bearer credentials and are created with owner-only access.
Passwords are read from the terminal or an explicitly named environment variable.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any

from .models import CATEGORIES, CONDITIONS, DomainError
from .service import Market


def emit(value: Any) -> None:
    """Print a machine-readable, Unicode-preserving result."""
    print(json.dumps(value, ensure_ascii=False, indent=2))


def read_password() -> str:
    """Keep passwords out of command arguments and normal command output."""
    password = os.environ.get("CAMPUS_PASSWORD")
    if password is None:
        password = getpass.getpass("密码（输入不回显）：")
    if not password:
        raise DomainError("INVALID_INPUT", "密码不能为空")
    return password


def load_json_file(path: str) -> Any:
    """Load a UTF-8 JSON file without exposing malformed input in errors."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DomainError("INVALID_FILE", "文件不存在、不可读取或不是有效 JSON") from exc


class SessionStore:
    """Store one role's local session; prevent accidental cross-database use."""

    def __init__(self, path: Path, database: Path) -> None:
        self.path = path.expanduser().resolve()
        self.database = str(database.expanduser().resolve())

    def token(self, required: bool = True) -> str | None:
        """Read a saved credential, or use the process-local session override."""
        token = os.environ.get("CAMPUS_SESSION_TOKEN")
        if token:
            return token
        if not self.path.exists():
            if required:
                raise DomainError("LOGIN_REQUIRED", "请先登录，或选择已有的 --session-file")
            return None
        data = load_json_file(str(self.path))
        if not isinstance(data, dict) or data.get("database") != self.database:
            raise DomainError("SESSION_FILE", "会话文件格式错误或属于另一个数据库")
        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise DomainError("SESSION_FILE", "会话文件没有有效登录凭据")
        return token

    def save(self, result: dict[str, Any]) -> None:
        """Use an exclusive temporary file and atomic replace for credentials."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        data = {
            "database": self.database,
            "account_id": result["account"]["id"],
            "token": result["token"],
        }
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False)
                stream.write("\n")
            os.replace(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)

    def clear(self) -> None:
        """Delete only this local credential, leaving other role files intact."""
        self.path.unlink(missing_ok=True)


def add_identity(parser: argparse.ArgumentParser) -> None:
    """Collect the three independent unique account fields."""
    parser.add_argument("--username", required=True, help="唯一用户名")
    parser.add_argument("--email", required=True, help="配置域名下的校园邮箱")
    parser.add_argument("--campus-id", required=True, help="唯一学号/工号")


def add_version(parser: argparse.ArgumentParser) -> None:
    """Require the row version visible when the user began an edit."""
    parser.add_argument("product_id", help="商品编号")
    parser.add_argument("--version", type=int, required=True, help="当前 row_version")


def add_request_key(parser: argparse.ArgumentParser) -> None:
    """A required explicit key makes retries reproducible from the terminal."""
    parser.add_argument(
        "--key",
        required=True,
        help="本次操作唯一请求键；重试复用，新操作换键，同键不得改内容",
    )


def parser_for_cli() -> argparse.ArgumentParser:
    """Build discoverable commands for the full six-module use-case surface."""
    parser = argparse.ArgumentParser(
        prog="python -m campus_market",
        description="校园循物：单件物品发布、审核、预约与线下成交管理",
        epilog="图形界面：python3 -m campus_market gui --demo。全局选项应放在子命令前；子命令后加 --help 查看参数。",
    )
    parser.add_argument("--db", default="data/market.sqlite3", help="SQLite 数据库路径")
    parser.add_argument(
        "--domain",
        default="campus.example",
        help="允许注册的校园邮箱域名；默认仅用于本地演示",
    )
    parser.add_argument("--outbox", help="本地验证邮件目录；仅限可信操作系统用户读取")
    parser.add_argument(
        "--mail-mode",
        choices=("local", "smtp"),
        default="local",
        help="local 为开发邮箱；smtp 使用 CAMPUS_SMTP_* 环境配置发送验证邮件",
    )
    parser.add_argument("--session-file", help="当前角色的本地会话文件")
    parser.add_argument("--guest", action="store_true", help="公开查询时不加载已存会话")
    commands = parser.add_subparsers(dest="command", required=True, title="操作命令")

    for name, help_text in (
        ("init-admin", "空库初始化首个管理员，随后仍需验证邮箱"),
        ("register", "注册普通账号，验证后可登录"),
        ("create-admin", "已登录管理员创建新管理员账号"),
    ):
        add_identity(commands.add_parser(name, help=help_text))
    verify = commands.add_parser("verify", help="完成邮箱验证")
    verify.add_argument("--mail-file", help="本地演示邮件 JSON；未指定时安全输入验证码")
    login = commands.add_parser("login", help="以用户名或邮箱登录并保存本角色会话")
    login.add_argument("identifier", help="用户名或邮箱")
    commands.add_parser("logout", help="撤销当前会话并清除本地凭据")
    commands.add_parser("me", help="查看当前账号")
    commands.add_parser("accounts", help="管理员查看账号列表")

    draft = commands.add_parser("draft", help="新建或修改本人私人草稿")
    draft.add_argument("--product-id", help="修改时填写已有商品编号")
    draft.add_argument("--version", type=int, help="修改时必须提供当前 row_version")
    draft.add_argument("--content-file", help="UTF-8 商品 JSON；不能与单字段参数混用")
    draft.add_argument("--title", help="商品标题")
    draft.add_argument("--category", choices=CATEGORIES, help="商品分类")
    draft.add_argument("--condition", choices=CONDITIONS, help="商品成色")
    draft.add_argument("--price", help="元，不超过两位小数")
    draft.add_argument("--description", help="商品描述")
    draft.add_argument("--image", action="append", help="已上传图片编号，可重复最多五次")
    for name, help_text in (
        ("delete-draft", "删除从未正式提交的本人纯草稿"),
        ("withdraw", "撤回尚未处理的当前审核批次"),
        ("off-shelf", "下架本人在售且未被预约的商品"),
    ):
        add_version(commands.add_parser(name, help=help_text))
    submit = commands.add_parser("submit", help="完整校验商品并提交新审核批次")
    add_version(submit)
    add_request_key(submit)
    product = commands.add_parser("product", help="按访问权限查看一件商品")
    product.add_argument("product_id")
    history = commands.add_parser("product-history", help="查看商品的提交版本和审核历史")
    history.add_argument("product_id")
    products = commands.add_parser("products", help="组合筛选、排序并分页查询商品")
    products.add_argument("--scope", choices=("public", "mine", "admin"), default="public")
    products.add_argument("--keyword", default="", help="标题或描述关键词")
    products.add_argument("--category", choices=CATEGORIES, default="")
    products.add_argument("--min-price")
    products.add_argument("--max-price")
    products.add_argument("--state", default="", help="状态英文名；不能扩大访问范围")
    products.add_argument("--sort", choices=("newest", "price_asc", "price_desc"), default="newest")
    products.add_argument("--page", type=int, default=1)
    upload = commands.add_parser("upload-image", help="上传 JPG/PNG，保留不可变历史引用")
    upload.add_argument("path", help="本地图片路径")
    image = commands.add_parser("image", help="按引用权限导出图片，拒绝覆盖已有文件")
    image.add_argument("image_id")
    image.add_argument("output", help="图片保存路径")

    reserve = commands.add_parser("reserve", help="确认当前标题/价格后预约他人的在售商品")
    reserve.add_argument("product_id")
    reserve.add_argument("--content-version", type=int, required=True)
    reserve.add_argument("--message", required=True, help="面交约定，不能为空")
    reserve.add_argument(
        "--yes", action="store_true", help="已确认标题价格，跳过交互；也用于成功重试"
    )
    add_request_key(reserve)
    for name, help_text in (
        ("confirm", "卖家确认待确认预约"),
        ("reject", "卖家拒绝待确认预约"),
        ("cancel", "按阶段和身份取消预约"),
        ("complete", "卖家声明已面交完成；不代表核验付款"),
    ):
        action = commands.add_parser(name, help=help_text)
        action.add_argument("reservation_id")
        add_request_key(action)
        if name in ("reject", "cancel"):
            action.add_argument("--reason", default="", help="已确认后取消必填")
    reservation = commands.add_parser("reservation", help="查看本人相关预约，邮箱按状态返回")
    reservation.add_argument("reservation_id")
    reservations = commands.add_parser("reservations", help="查询有权访问的预约历史")
    reservations.add_argument("--side", choices=("all", "buyer", "seller"), default="all")
    reservations.add_argument("--state", default="")
    reservations.add_argument("--page", type=int, default=1)

    review = commands.add_parser("review", help="管理员处理当前提交批次，结论与原因必填")
    review.add_argument("submission_id")
    review.add_argument("decision", choices=("approve", "reject"))
    review.add_argument("--reason", required=True)
    violation = commands.add_parser("violation", help="管理员违规下架；成交后仅加标记")
    violation.add_argument("product_id")
    violation.add_argument("--reason", required=True)
    for name, help_text in (
        ("ban", "封禁普通账号并联动撤销会话、商品与预约"),
        ("unban", "解封普通账号，不自动恢复商品和预约"),
    ):
        action = commands.add_parser(name, help=help_text)
        action.add_argument("account_id")
        action.add_argument("--reason", required=True)
    stats = commands.add_parser("stats", help="个人分类统计或管理员平台统计")
    stats.add_argument("--start", type=float, help="完成时间下限，Unix 秒，包含边界")
    stats.add_argument("--end", type=float, help="完成时间上限，Unix 秒，包含边界")
    logs = commands.add_parser("logs", help="按权限查看不可修改的操作日志，每页 50 条")
    logs.add_argument("--operation", default="")
    logs.add_argument("--object-id", default="")
    logs.add_argument("--result", default="")
    logs.add_argument("--actor-id", default="", help="操作者编号，仍受当前日志访问权限限制")
    logs.add_argument("--start", type=float, help="操作时间下限，Unix 秒，包含边界")
    logs.add_argument("--end", type=float, help="操作时间上限，Unix 秒，包含边界")
    logs.add_argument("--page", type=int, default=1)
    return parser


def content_from_args(args: argparse.Namespace) -> dict[str, Any]:
    """Preserve an explicit content source rather than silently merging inputs."""
    fields = ("title", "category", "condition", "price", "description", "image")
    if args.content_file:
        if any(getattr(args, field) is not None for field in fields):
            raise DomainError("INVALID_INPUT", "--content-file 不能与商品字段参数混用")
        data = load_json_file(args.content_file)
        if not isinstance(data, dict):
            raise DomainError("INVALID_INPUT", "商品 JSON 顶层必须是对象")
        return data
    return {
        "title": args.title or "",
        "category": args.category or "",
        "condition": args.condition or "",
        "price": args.price or "",
        "description": args.description or "",
        "images": args.image or [],
    }


def verification_from_args(args: argparse.Namespace) -> str:
    """Consume a local mailbox fixture or a token supplied privately by the user."""
    if not args.mail_file:
        return getpass.getpass("邮箱验证码（输入不回显）：").strip()
    data = load_json_file(args.mail_file)
    if not isinstance(data, dict) or not isinstance(data.get("verification_token"), str):
        raise DomainError("INVALID_FILE", "邮件文件缺少 verification_token")
    return data["verification_token"]


def run_account_command(
    market: Market,
    sessions: SessionStore,
    args: argparse.Namespace,
) -> Any:
    """Execute account commands while withholding credentials from output."""
    name = args.command
    if name in ("init-admin", "register", "create-admin"):
        identity = (args.username, args.email, args.campus_id, read_password())
        if name == "init-admin":
            result = market.bootstrap_admin(*identity)
            return {
                "account": result["account"],
                "delivery": args.mail_mode,
                "next": "读取本地 outbox 或收到的验证邮件，再运行 verify 完成邮箱验证",
            }
        if name == "register":
            return market.register(*identity)
        return market.create_admin(sessions.token(), *identity)
    if name == "verify":
        return market.verify_email(verification_from_args(args))
    if name == "login":
        result = market.login(args.identifier, read_password())
        sessions.save(result)
        return {"account": result["account"], "session_file": str(sessions.path)}
    if name == "logout":
        result = market.logout(sessions.token())
        sessions.clear()
        return result or {"message": "当前会话已退出"}
    if name == "me":
        return market.whoami(sessions.token())
    return market.list_accounts(sessions.token())


def run_product_command(
    market: Market,
    sessions: SessionStore,
    args: argparse.Namespace,
) -> Any:
    """Map product commands to the shared permission-enforcing service."""
    name = args.command
    if name == "draft":
        return market.save_draft(
            sessions.token(),
            content_from_args(args),
            product_id=args.product_id,
            expected_version=args.version,
        )
    if name == "delete-draft":
        result = market.delete_draft(sessions.token(), args.product_id, args.version)
        return result or {"message": "纯草稿已删除", "product_id": args.product_id}
    if name == "submit":
        return market.submit_product(
            sessions.token(),
            args.product_id,
            args.version,
            args.key,
        )
    if name in ("withdraw", "off-shelf"):
        action = market.withdraw_product if name == "withdraw" else market.off_shelf
        return action(sessions.token(), args.product_id, args.version)
    if name == "product-history":
        return market.product_history(sessions.token(), args.product_id)
    if name == "upload-image":
        return market.upload_image(sessions.token(), args.path)
    token = None if args.guest else sessions.token(required=False)
    if name == "product":
        return market.get_product(args.product_id, token=token)
    if name == "products":
        return market.list_products(
            token=token,
            scope=args.scope,
            keyword=args.keyword,
            category=args.category,
            min_price=args.min_price,
            max_price=args.max_price,
            state=args.state,
            sort=args.sort,
            page=args.page,
        )
    image = market.read_image(args.image_id, token=token)
    output = Path(args.output).expanduser()
    with output.open("xb") as stream:
        stream.write(image["data"])
    return {"id": image["id"], "mime": image["mime"], "saved_to": str(output.resolve())}


def run_trade_command(
    market: Market,
    sessions: SessionStore,
    args: argparse.Namespace,
) -> Any:
    """Confirm the item in the terminal before executing a new reservation."""
    token = sessions.token()
    name = args.command
    if name == "reserve":
        if not args.yes:
            product = market.get_product(args.product_id, token=token)
            content = product["content"]
            print(
                f"预约确认：{content['title']} / ¥{content['price']} / "
                f"内容版本 {product['content_version']}",
                file=sys.stderr,
            )
            if input("确认上述标题和价格？输入 yes 继续：").strip().lower() != "yes":
                raise DomainError("USER_CANCELLED", "已放弃本次预约，未改变商品")
        return market.reserve(
            token,
            args.product_id,
            args.content_version,
            args.message,
            args.key,
        )
    if name == "reservation":
        return market.get_reservation(token, args.reservation_id)
    if name == "reservations":
        return market.list_reservations(token, side=args.side, state=args.state, page=args.page)
    action = getattr(market, name)
    if name in ("cancel", "reject"):
        return action(token, args.reservation_id, args.key, reason=args.reason)
    return action(token, args.reservation_id, args.key)


def run_admin_command(market: Market, sessions: SessionStore, args: argparse.Namespace) -> Any:
    """Administrative commands never bypass the same server-side role checks."""
    token = sessions.token()
    name = args.command
    if name == "review":
        return market.review(token, args.submission_id, args.decision == "approve", args.reason)
    if name == "violation":
        return market.mark_violation(token, args.product_id, args.reason)
    if name in ("ban", "unban"):
        action = market.ban_account if name == "ban" else market.unban_account
        return action(token, args.account_id, args.reason)
    if name == "stats":
        return market.statistics(token, start=args.start, end=args.end)
    return market.list_logs(
        token,
        operation=args.operation,
        object_id=args.object_id,
        result=args.result,
        page=args.page,
        actor_id=args.actor_id,
        start=args.start,
        end=args.end,
    )


def main(argv: list[str] | None = None) -> int:
    """Return stable exit statuses: success=0, usage/domain/IO failure=2."""
    args = parser_for_cli().parse_args(argv)
    database = Path(args.db).expanduser().resolve()
    session_file = (
        Path(args.session_file) if args.session_file else database.with_suffix(".session.json")
    )
    sessions = SessionStore(session_file, database)
    try:
        market = Market(
            database,
            email_domain=args.domain,
            outbox=args.outbox,
            mail_mode=args.mail_mode,
        )
        if args.command in {
            "init-admin",
            "register",
            "create-admin",
            "verify",
            "login",
            "logout",
            "me",
            "accounts",
        }:
            result = run_account_command(market, sessions, args)
        elif args.command in {
            "draft",
            "delete-draft",
            "submit",
            "withdraw",
            "off-shelf",
            "product",
            "product-history",
            "products",
            "upload-image",
            "image",
        }:
            result = run_product_command(market, sessions, args)
        elif args.command in {
            "reserve",
            "confirm",
            "reject",
            "cancel",
            "complete",
            "reservation",
            "reservations",
        }:
            result = run_trade_command(market, sessions, args)
        else:
            result = run_admin_command(market, sessions, args)
        emit(result)
        return 0
    except DomainError as exc:
        emit({"error": exc.code, "message": str(exc)})
        return 2
    except ValueError:
        emit({"error": "CONFIGURATION", "message": "配置或数据格式不正确，请检查邮箱域名与输入"})
        return 2
    except (OSError, sqlite3.Error, EOFError) as exc:
        emit({"error": "LOCAL_IO", "message": "本地读写失败或输入结束", "type": type(exc).__name__})
        return 2
    except KeyboardInterrupt:
        emit({"error": "INTERRUPTED", "message": "操作已中断，请查询当前状态再决定是否重试"})
        return 130
