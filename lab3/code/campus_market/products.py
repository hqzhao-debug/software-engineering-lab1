"""Product ownership, immutable submissions, catalogue and protected images.

The current editable content lives on ``products``.  Each submitted version is
copied into ``submitted_versions`` and never updated.  Administrators read the
latter, including when a seller has subsequently started a new private draft.
"""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import struct

from .models import (
    CATEGORIES,
    PRODUCT_STATES,
    DomainError,
    json_text,
    load_json,
    money_cents,
    validate_content,
)


PAGE_SIZE = 20
MAX_IMAGE_BYTES = 5 * 1024 * 1024
EDITABLE_STATES = {"DRAFT", "ON_SALE", "OFF_SHELF", "REJECTED", "VIOLATION"}


class ProductMixin:
    """Implement seller commands and access-controlled product queries."""

    @staticmethod
    def _check_owner(product, actor):
        """Do not allow a role or an identifier supplied by a client to own data."""
        if actor["role"] != "USER" or product["seller_id"] != actor["id"]:
            raise DomainError("FORBIDDEN", "只能管理本人商品")

    @staticmethod
    def _check_version(product, expected_version):
        """A form read before a competing update cannot overwrite that update."""
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or product["row_version"] != expected_version
        ):
            raise DomainError("STALE_VERSION", "商品已变化，请刷新后重新操作")

    @staticmethod
    def _check_no_reservation(conn, product_id):
        occupied = conn.execute(
            "SELECT id FROM reservations WHERE product_id=? "
            "AND state IN ('PENDING','CONFIRMED')",
            (product_id,),
        ).fetchone()
        if occupied:
            raise DomainError("INVALID_STATE", "商品存在有效预约，不能执行此操作")

    @staticmethod
    def _check_image_ownership(conn, image_ids, owner_id):
        """References are server-issued ids, not arbitrary local or remote paths."""
        for image_id in image_ids:
            image = conn.execute(
                "SELECT owner_id FROM images WHERE id=?", (image_id,)
            ).fetchone()
            if image is None or image["owner_id"] != owner_id:
                raise DomainError("INVALID_IMAGE", "图片不存在或不属于当前卖家")

    @staticmethod
    def _product_dict(product):
        result = dict(product)
        result["content"] = load_json(result.pop("content_json"))
        return result

    def _last_submitted(self, conn, product_id):
        """Return an immutable version even when the current draft is newer."""
        row = conn.execute(
            "SELECT * FROM submitted_versions WHERE product_id=? "
            "ORDER BY content_version DESC LIMIT 1",
            (product_id,),
        ).fetchone()
        return dict(row) if row else None

    def _visible_product(self, conn, product, actor):
        """Assemble only fields authorized for the requesting identity."""
        own_product = bool(actor and actor["id"] == product["seller_id"])
        administrator = bool(actor and actor["role"] == "ADMIN")
        if own_product:
            result = self._product_dict(product)
            result["content_source"] = "current"
        elif administrator:
            version = self._last_submitted(conn, product["id"])
            if version is None:
                raise DomainError("NOT_FOUND", "没有可管理的已提交版本")
            result = self._product_dict(product)
            result["content"] = load_json(version["content_json"])
            result["content_version"] = version["content_version"]
            result["content_source"] = "submitted"
            result["visible_version_id"] = version["id"]
            # The current draft's modification time and optimistic lock are not
            # needed for review; a review uses its immutable submission id.
            result.pop("row_version", None)
            result.pop("updated_at", None)
        elif product["state"] == "ON_SALE":
            result = {
                "id": product["id"],
                "seller_id": product["seller_id"],
                "state": product["state"],
                "content_version": product["content_version"],
                "published_at": product["published_at"],
                "content": load_json(product["content_json"]),
                "content_source": "published",
            }
        else:
            raise DomainError("NOT_FOUND", "商品不存在或当前不可公开查看")
        seller = self._one(conn, "accounts", product["seller_id"])
        result["seller_username"] = seller["username"]
        return result

    @contextmanager
    def _optional_reader(self, token):
        """Authenticate supplied credentials; absent credentials mean a guest."""
        if token is not None:
            with self._read(token) as pair:
                yield pair
            return
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            yield conn, None
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def save_draft(self, token, content, product_id=None, expected_version=None):
        """Create or replace the caller's private draft after basic validation.

        Content validation deliberately permits incomplete category, condition
        and price.  Submitting is a separate command with complete validation.
        Editing a published object unpublishes it without erasing old versions.
        """
        with self._atomic(token, "save_draft", product_id, role="USER") as pair:
            conn, actor = pair
            normalized = validate_content(content, complete=False)
            self._check_image_ownership(conn, normalized["images"], actor["id"])
            now = self._now()
            if product_id is None:
                product_id = self._new_id()
                conn.execute(
                    "INSERT INTO products "
                    "(id,seller_id,state,content_json,row_version,content_version,"
                    "active_restriction,ban_restriction,current_submission_id,"
                    "published_at,created_at,updated_at) "
                    "VALUES (?,?,'DRAFT',?,1,1,0,0,NULL,NULL,?,?)",
                    (product_id, actor["id"], json_text(normalized), now, now),
                )
                before = None
                old_price = None
            else:
                product = self._one(conn, "products", product_id)
                self._check_owner(product, actor)
                self._check_version(product, expected_version)
                if product["state"] not in EDITABLE_STATES:
                    raise DomainError("INVALID_STATE", "当前状态不能编辑，请先结束预约或撤回审核")
                self._check_no_reservation(conn, product_id)
                before = product["state"]
                old_price = load_json(product["content_json"]).get("price")
                conn.execute(
                    "UPDATE products SET content_json=?,state='DRAFT',"
                    "row_version=row_version+1,content_version=content_version+1,"
                    "updated_at=? WHERE id=?",
                    (json_text(normalized), now, product_id),
                )
            self._audit(
                conn,
                actor,
                "save_draft",
                product_id,
                before=before,
                after="DRAFT",
                details={"price_before": old_price, "price_after": normalized["price"]},
                private_owner=actor["id"],
            )
            return self._product_dict(self._one(conn, "products", product_id))

    def delete_draft(self, token, product_id, expected_version):
        """Only a draft that has never been submitted may be physically removed."""
        with self._atomic(token, "delete_draft", product_id, role="USER") as pair:
            conn, actor = pair
            product = self._one(conn, "products", product_id)
            self._check_owner(product, actor)
            self._check_version(product, expected_version)
            if product["state"] != "DRAFT":
                raise DomainError("INVALID_STATE", "只有从未提交的草稿可删除")
            has_history = conn.execute(
                "SELECT id FROM submitted_versions WHERE product_id=? LIMIT 1",
                (product_id,),
            ).fetchone()
            if has_history:
                raise DomainError("HAS_HISTORY", "已有提交历史的商品不能删除")
            self._check_no_reservation(conn, product_id)
            conn.execute("DELETE FROM products WHERE id=?", (product_id,))
            self._audit(
                conn, actor, "delete_draft", product_id, before="DRAFT", after="DELETED"
            )
            return {"id": product_id, "deleted": True}

    def submit_product(self, token, product_id, expected_version, request_key):
        """Freeze the content, open a new review batch and preserve all history."""
        payload = {"product_id": product_id, "expected_version": expected_version}
        with self._atomic(token, "submit_product", product_id, role="USER") as pair:
            conn, actor = pair
            product = self._one(conn, "products", product_id)
            self._check_owner(product, actor)
            replay = self._idempotent(
                conn, actor, "submit_product", request_key, payload
            )
            if replay:
                return self._one(conn, "review_submissions", replay)
            self._check_version(product, expected_version)
            if product["state"] not in {"DRAFT", "OFF_SHELF"}:
                raise DomainError("INVALID_STATE", "只能提交草稿或重新审核已下架商品")
            if product["state"] == "OFF_SHELF" and product["active_restriction"]:
                raise DomainError("RESTRICTED", "违规商品须先修改保存，再提交审核")
            self._check_no_reservation(conn, product_id)
            normalized = validate_content(load_json(product["content_json"]), complete=True)
            self._check_image_ownership(conn, normalized["images"], actor["id"])
            version = conn.execute(
                "SELECT * FROM submitted_versions "
                "WHERE product_id=? AND content_version=?",
                (product_id, product["content_version"]),
            ).fetchone()
            now = self._now()
            if version is None:
                version_id = self._new_id()
                conn.execute(
                    "INSERT INTO submitted_versions "
                    "(id,product_id,content_version,content_json,submitted_at) "
                    "VALUES (?,?,?,?,?)",
                    (
                        version_id,
                        product_id,
                        product["content_version"],
                        json_text(normalized),
                        now,
                    ),
                )
            else:
                version_id = version["id"]
                if load_json(version["content_json"]) != normalized:
                    raise DomainError("INCONSISTENT", "同一内容版本与保存资料不一致")
            submission_id = self._new_id()
            conn.execute(
                "INSERT INTO review_submissions "
                "(id,product_id,version_id,status,reviewer_id,reason,created_at,reviewed_at) "
                "VALUES (?,?,?,'PENDING',NULL,'',?,NULL)",
                (submission_id, product_id, version_id, now),
            )
            conn.execute(
                "UPDATE products SET state='REVIEW',current_submission_id=?,"
                "row_version=row_version+1,updated_at=? WHERE id=?",
                (submission_id, now, product_id),
            )
            self._audit(
                conn,
                actor,
                "submit_product",
                product_id,
                before=product["state"],
                after="REVIEW",
                details={"submission_id": submission_id, "version_id": version_id},
            )
            self._remember(
                conn, actor, "submit_product", request_key, payload, submission_id
            )
            return self._one(conn, "review_submissions", submission_id)

    def withdraw_product(self, token, product_id, expected_version):
        """Withdraw an unprocessed batch; its immutable submitted copy remains."""
        with self._atomic(token, "withdraw_product", product_id, role="USER") as pair:
            conn, actor = pair
            product = self._one(conn, "products", product_id)
            self._check_owner(product, actor)
            self._check_version(product, expected_version)
            if product["state"] != "REVIEW" or not product["current_submission_id"]:
                raise DomainError("INVALID_STATE", "当前商品没有待处理的审核批次")
            submission = self._one(
                conn, "review_submissions", product["current_submission_id"]
            )
            if submission["status"] != "PENDING":
                raise DomainError("INVALID_STATE", "该审核批次已被处理")
            conn.execute(
                "UPDATE review_submissions SET status='WITHDRAWN',reviewed_at=? "
                "WHERE id=?",
                (self._now(), submission["id"]),
            )
            conn.execute(
                "UPDATE products SET state='DRAFT',row_version=row_version+1,"
                "updated_at=? WHERE id=?",
                (self._now(), product_id),
            )
            self._audit(
                conn, actor, "withdraw_product", product_id, before="REVIEW", after="DRAFT"
            )
            return self._product_dict(self._one(conn, "products", product_id))

    def off_shelf(self, token, product_id, expected_version):
        """Unpublish an unoccupied item; a future release needs a new review."""
        with self._atomic(token, "off_shelf", product_id, role="USER") as pair:
            conn, actor = pair
            product = self._one(conn, "products", product_id)
            self._check_owner(product, actor)
            self._check_version(product, expected_version)
            if product["state"] != "ON_SALE":
                raise DomainError("INVALID_STATE", "只能主动下架当前在售商品")
            self._check_no_reservation(conn, product_id)
            conn.execute(
                "UPDATE products SET state='OFF_SHELF',row_version=row_version+1,"
                "updated_at=? WHERE id=?",
                (self._now(), product_id),
            )
            self._audit(
                conn, actor, "off_shelf", product_id, before="ON_SALE", after="OFF_SHELF"
            )
            return self._product_dict(self._one(conn, "products", product_id))

    def get_product(self, product_id, token=None):
        """Return current seller content, submitted admin content, or public data."""
        with self._optional_reader(token) as pair:
            conn, actor = pair
            product = self._one(conn, "products", product_id)
            return self._visible_product(conn, product, actor)

    @staticmethod
    def _validate_catalogue_filters(category, minimum, maximum, state, sort, page):
        if category and category not in CATEGORIES:
            raise DomainError("INVALID_INPUT", "未知商品分类")
        if state and state not in PRODUCT_STATES:
            raise DomainError("INVALID_INPUT", "未知商品状态")
        if sort not in {"newest", "price_asc", "price_desc"}:
            raise DomainError("INVALID_INPUT", "排序应为 newest、price_asc 或 price_desc")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise DomainError("INVALID_INPUT", "页码必须是正整数")
        low = money_cents(minimum, allow_zero=True) if minimum is not None else None
        high = money_cents(maximum, allow_zero=True) if maximum is not None else None
        if low is not None and high is not None and low > high:
            raise DomainError("INVALID_INPUT", "最低价格不能大于最高价格")
        return low, high

    def _catalogue_rows(self, conn, actor, scope):
        """Limit the ownership scope before applying any client-side filters."""
        if scope == "public":
            return conn.execute(
                "SELECT * FROM products WHERE state='ON_SALE'"
            ).fetchall()
        if scope == "mine":
            if not actor or actor["role"] != "USER":
                raise DomainError("FORBIDDEN", "个人商品查询需要普通用户登录")
            return conn.execute(
                "SELECT * FROM products WHERE seller_id=?", (actor["id"],)
            ).fetchall()
        if scope == "admin":
            if not actor or actor["role"] != "ADMIN":
                raise DomainError("FORBIDDEN", "管理查询需要管理员登录")
            return conn.execute(
                "SELECT p.* FROM products p WHERE EXISTS "
                "(SELECT 1 FROM submitted_versions v WHERE v.product_id=p.id)"
            ).fetchall()
        raise DomainError("INVALID_INPUT", "查询范围应为 public、mine 或 admin")

    def list_products(
        self,
        token=None,
        scope="public",
        keyword="",
        category="",
        min_price=None,
        max_price=None,
        state="",
        sort="newest",
        page=1,
    ):
        """Combine filters with AND and paginate only the authorized result set."""
        low, high = self._validate_catalogue_filters(
            category, min_price, max_price, state, sort, page
        )
        if not isinstance(keyword, str):
            raise DomainError("INVALID_INPUT", "关键词必须是文本")
        keyword = keyword.strip().casefold()
        with self._optional_reader(token) as pair:
            conn, actor = pair
            rows = self._catalogue_rows(conn, actor, scope)
            results = []
            for row in rows:
                product = dict(row)
                if state and product["state"] != state:
                    continue
                # Even administrators deliberately see only public fields when
                # they choose the public catalogue scope.
                viewer = None if scope == "public" else actor
                visible = self._visible_product(conn, product, viewer)
                content = visible["content"]
                text = f"{content['title']} {content['description']}".casefold()
                if keyword and keyword not in text:
                    continue
                if category and content["category"] != category:
                    continue
                amount = money_cents(content["price"]) if content["price"] else None
                if low is not None and (amount is None or amount < low):
                    continue
                if high is not None and (amount is None or amount > high):
                    continue
                results.append(visible)
            if sort == "newest":
                results.sort(
                    key=lambda item: (item.get("published_at") or 0, item["id"]),
                    reverse=True,
                )
            else:
                results.sort(
                    key=lambda item: (
                        money_cents(item["content"]["price"])
                        if item["content"]["price"]
                        else -1,
                        item["id"],
                    ),
                    reverse=sort == "price_desc",
                )
            start = (page - 1) * PAGE_SIZE
            return {
                "items": results[start : start + PAGE_SIZE],
                "total": len(results),
                "page": page,
                "page_size": PAGE_SIZE,
            }

    def product_history(self, token, product_id):
        """Expose submitted versions and review batches, never current drafts."""
        with self._read(token) as pair:
            conn, actor = pair
            product = self._one(conn, "products", product_id)
            if actor["role"] != "ADMIN" and product["seller_id"] != actor["id"]:
                raise DomainError("FORBIDDEN", "无权查看该商品审核历史")
            versions = conn.execute(
                "SELECT * FROM submitted_versions WHERE product_id=? "
                "ORDER BY content_version",
                (product_id,),
            ).fetchall()
            if actor["role"] == "ADMIN" and not versions:
                raise DomainError("NOT_FOUND", "该商品没有已提交历史")
            submissions = conn.execute(
                "SELECT * FROM review_submissions WHERE product_id=? "
                "ORDER BY created_at,id",
                (product_id,),
            ).fetchall()
            visible_versions = []
            for row in versions:
                version = dict(row)
                version["content"] = load_json(version.pop("content_json"))
                visible_versions.append(version)
            return {
                "product_id": product_id,
                "versions": visible_versions,
                "submissions": [dict(row) for row in submissions],
            }

    @staticmethod
    def _image_mime(data):
        """Check file signatures and dimensions without trusting an extension.

        The application stores and returns bytes without decoding or executing
        them.  This small standard-library validator rejects truncated headers;
        it is not a full image decoder or a malware scanner.
        """
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            if len(data) < 45 or data[12:16] != b"IHDR":
                raise DomainError("INVALID_IMAGE", "PNG 图片头不完整")
            width, height = struct.unpack(">II", data[16:24])
            if not width or not height or b"IEND" not in data[-12:]:
                raise DomainError("INVALID_IMAGE", "PNG 图片尺寸或结束标记非法")
            return "image/png"
        if data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
            if len(data) < 16:
                raise DomainError("INVALID_IMAGE", "JPEG 图片不完整")
            return "image/jpeg"
        raise DomainError("INVALID_IMAGE", "只接受 JPG 或 PNG 图片")

    def upload_image(self, token, path):
        """Persist a bounded image blob owned by the authenticated seller."""
        with self._atomic(token, "upload_image", role="USER") as pair:
            conn, actor = pair
            try:
                with Path(path).open("rb") as stream:
                    data = stream.read(MAX_IMAGE_BYTES + 1)
            except (OSError, TypeError, ValueError) as exc:
                raise DomainError("INVALID_IMAGE", "无法读取指定图片文件") from exc
            if len(data) > MAX_IMAGE_BYTES:
                raise DomainError("INVALID_IMAGE", "单张图片不得超过 5MB")
            mime = self._image_mime(data)
            image_id = self._new_id()
            conn.execute(
                "INSERT INTO images (id,owner_id,mime,data,created_at) VALUES (?,?,?,?,?)",
                (image_id, actor["id"], mime, sqlite3.Binary(data), self._now()),
            )
            self._audit(conn, actor, "upload_image", image_id)
            return {"id": image_id, "mime": mime, "size": len(data)}

    @staticmethod
    def _contains_image(content_json, image_id):
        return image_id in load_json(content_json).get("images", [])

    def _image_visible(self, conn, image, actor):
        """An image inherits access from a current publication or a history."""
        image_id = image["id"]
        if actor and image["owner_id"] == actor["id"]:
            return True
        publications = conn.execute(
            "SELECT content_json FROM products WHERE state='ON_SALE'"
        ).fetchall()
        if any(self._contains_image(row["content_json"], image_id) for row in publications):
            return True
        if not actor:
            return False
        if actor["role"] == "ADMIN":
            submissions = conn.execute(
                "SELECT content_json FROM submitted_versions"
            ).fetchall()
            return any(
                self._contains_image(row["content_json"], image_id) for row in submissions
            )
        histories = conn.execute(
            "SELECT snapshot_json FROM reservations WHERE buyer_id=? OR seller_id=?",
            (actor["id"], actor["id"]),
        ).fetchall()
        return any(self._contains_image(row["snapshot_json"], image_id) for row in histories)

    def read_image(self, image_id, token=None):
        """Resolve image bytes only after checking its business references."""
        with self._optional_reader(token) as pair:
            conn, actor = pair
            image = self._one(conn, "images", image_id)
            if not self._image_visible(conn, image, actor):
                raise DomainError("NOT_FOUND", "图片不存在或无权访问")
            return {"id": image_id, "mime": image["mime"], "data": bytes(image["data"])}
