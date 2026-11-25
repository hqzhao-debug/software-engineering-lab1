"""Domain values and validation shared by the application services."""

import json
from decimal import Decimal, InvalidOperation
from enum import StrEnum

CATEGORIES = ("教材书籍", "数码电子", "生活用品", "体育器材", "乐器", "文具", "其他")
CONDITIONS = ("全新", "九成新", "八成新", "七成新及以下")


class ProductState(StrEnum):
    """Persisted states from the product state diagram."""

    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    REJECTED = "REJECTED"
    ON_SALE = "ON_SALE"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    OFF_SHELF = "OFF_SHELF"
    VIOLATION = "VIOLATION"
    SOLD = "SOLD"


class ReservationState(StrEnum):
    """Closed reservations never return to an active state."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


PRODUCT_STATES = tuple(state.value for state in ProductState)
RESERVATION_STATES = tuple(state.value for state in ReservationState)


class DomainError(Exception):
    """A safe error that may be presented to an end user."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self):
        """Return a stable error envelope for CLI clients."""
        return {"error": self.code, "message": self.message}


def required(value, label):
    """Require a nonempty string without inventing a business length limit."""
    if not isinstance(value, str) or not value.strip():
        raise DomainError("VALIDATION", f"{label}不能为空")
    return value.strip()


def money_cents(value, allow_zero=False):
    """Parse exact decimal money; never round excess fractional digits."""
    if isinstance(value, bool) or value is None:
        raise DomainError("VALIDATION", "金额格式不正确")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise DomainError("VALIDATION", "金额格式不正确") from error
    if not number.is_finite() or number.as_tuple().exponent < -2:
        raise DomainError("VALIDATION", "金额最多保留两位小数")
    lower = Decimal("0") if allow_zero else Decimal("0.01")
    if not lower <= number <= Decimal("99999.99"):
        raise DomainError("VALIDATION", f"金额须在 {lower} 至 99999.99 元之间")
    return int(number * 100)


def format_money(cents):
    """Format an integer sum without binary floating point arithmetic."""
    return f"{Decimal(cents) / 100:.2f}"


def validate_content(content, complete=False):
    """Validate a private draft or a fully submitted product version."""
    if not isinstance(content, dict):
        raise DomainError("VALIDATION", "商品内容须为对象")
    allowed = {"title", "category", "condition", "price", "description", "images"}
    if set(content) - allowed:
        raise DomainError("VALIDATION", "商品内容包含未知字段")
    title = required(content.get("title"), "标题")
    if len(title) > 50 or (complete and len(title) < 2):
        raise DomainError("VALIDATION", "提交标题须为 2 至 50 字，草稿须为 1 至 50 字")
    description = content.get("description", "")
    if not isinstance(description, str) or len(description) > 500:
        raise DomainError("VALIDATION", "描述须为不超过 500 字的文本")
    category = content.get("category", "")
    condition = content.get("condition", "")
    if (category or complete) and category not in CATEGORIES:
        raise DomainError("VALIDATION", "请选择有效的商品分类")
    if (condition or complete) and condition not in CONDITIONS:
        raise DomainError("VALIDATION", "请选择有效的商品成色")
    price = content.get("price", "")
    if price not in (None, "") or complete:
        price = format_money(money_cents(price))
    else:
        price = ""
    images = content.get("images", [])
    if not isinstance(images, list) or len(images) > 5:
        raise DomainError("VALIDATION", "图片须为列表，最多 5 张")
    if any(not isinstance(item, str) or not item for item in images):
        raise DomainError("VALIDATION", "图片引用无效")
    if len(set(images)) != len(images):
        raise DomainError("VALIDATION", "不能重复引用同一张图片")
    return {
        "title": title,
        "category": category or "",
        "condition": condition or "",
        "price": price,
        "description": description,
        "images": list(images),
    }


def json_text(value):
    """Produce deterministic JSON for persisted snapshots and request digests."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_json(value):
    """Decode JSON persisted by this package."""
    return json.loads(value)
