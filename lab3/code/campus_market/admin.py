"""Review, moderation, linked account restrictions, audit access, and statistics."""

from .accounts import public_account
from .models import CATEGORIES, DomainError, format_money, load_json, money_cents, required


class AdminMixin:
    """Administrative actions cannot impersonate a seller or bypass review."""

    def review(self, token, submission_id, approve, reason):
        """Review exactly the current pending batch and immutable submitted version."""
        with self._atomic(token, "review", submission_id, "ADMIN") as (connection, actor):
            reason = required(reason, "审核原因")
            if not isinstance(approve, bool):
                raise DomainError("VALIDATION", "审核结论须为通过或驳回")
            submission = self._one(connection, "review_submissions", submission_id)
            product = self._one(connection, "products", submission["product_id"])
            version = self._one(connection, "submitted_versions", submission["version_id"])
            if (submission["status"] != "PENDING" or product["state"] != "REVIEW"
                    or product["current_submission_id"] != submission_id
                    or product["content_version"] != version["content_version"]):
                raise DomainError("STALE", "审核批次或商品版本已变化，请刷新")
            seller = self._one(connection, "accounts", product["seller_id"])
            if seller["status"] != "NORMAL":
                raise DomainError("ACCOUNT_RESTRICTED", "卖家受限，不能处理发布审核")
            new_state = "ON_SALE" if approve else "REJECTED"
            review_state = "APPROVED" if approve else "REJECTED"
            connection.execute(
                "UPDATE review_submissions SET status=?,reviewer_id=?,reason=?,reviewed_at=? WHERE id=?",
                (review_state, actor["id"], reason, self._now(), submission_id),
            )
            connection.execute(
                "UPDATE products SET state=?,row_version=row_version+1,updated_at=?, "
                "active_restriction=?,ban_restriction=?,published_at=? WHERE id=?",
                (new_state, self._now(), 0 if approve else product["active_restriction"],
                 0 if approve else product["ban_restriction"],
                 self._now() if approve else product["published_at"], product["id"]),
            )
            if approve:
                connection.execute("UPDATE violations SET active=0 WHERE product_id=? AND active=1",
                                   (product["id"],))
            self._audit(connection, actor, "review", product["id"], product["state"],
                        new_state, reason=reason, details={"submission_id": submission_id})
            return self._one(connection, "review_submissions", submission_id)

    def _cancel_linked(self, connection, actor, reservation, reason):
        """Close an active reservation as part of one moderation transaction."""
        if reservation["state"] not in ("PENDING", "CONFIRMED"):
            return
        connection.execute(
            "UPDATE reservations SET state='CANCELLED',closed_at=?,closed_by=?,close_reason=? WHERE id=?",
            (self._now(), actor["id"], reason, reservation["id"]),
        )
        self._audit(connection, actor, "moderation_cancel", reservation["id"],
                    reservation["state"], "CANCELLED", reason=reason,
                    details={"product_id": reservation["product_id"]})

    def _invalidate_pending_review(self, connection, product, reason):
        if product["current_submission_id"]:
            connection.execute(
                "UPDATE review_submissions SET status='WITHDRAWN',reason=?,reviewed_at=? "
                "WHERE id=? AND status='PENDING'",
                (reason, self._now(), product["current_submission_id"]),
            )

    def mark_violation(self, token, product_id, reason):
        """Withdraw an unpublished/active item, or annotate a completed sale."""
        with self._atomic(token, "mark_violation", product_id, "ADMIN") as (connection, actor):
            reason = required(reason, "违规原因")
            product = self._one(connection, "products", product_id)
            if product["state"] == "DRAFT":
                raise DomainError("FORBIDDEN", "不能处理当前私人草稿；可查看已提交历史")
            connection.execute("INSERT INTO violations VALUES (?,?,?,?,1,?)",
                               (self._new_id(), product_id, actor["id"], reason, self._now()))
            reservations = connection.execute(
                "SELECT * FROM reservations WHERE product_id=? AND state IN ('PENDING','CONFIRMED')",
                (product_id,),
            ).fetchall()
            for reservation in reservations:
                self._cancel_linked(connection, actor, dict(reservation), f"违规终止：{reason}")
            self._invalidate_pending_review(connection, product, f"违规终止：{reason}")
            state = "SOLD" if product["state"] == "SOLD" else "VIOLATION"
            connection.execute(
                "UPDATE products SET state=?,active_restriction=1,row_version=row_version+1,updated_at=? WHERE id=?",
                (state, self._now(), product_id),
            )
            self._audit(connection, actor, "mark_violation", product_id,
                        product["state"], state, reason=reason)
            result = self._one(connection, "products", product_id)
            result["content"] = load_json(result.pop("content_json"))
            return result

    def ban_account(self, token, account_id, reason):
        """Revoke all sessions and atomically close both sides of active trades."""
        with self._atomic(token, "ban_account", account_id, "ADMIN") as (connection, actor):
            reason = required(reason, "封禁原因")
            account = self._one(connection, "accounts", account_id)
            if account["role"] != "USER":
                raise DomainError("FORBIDDEN", "此功能只允许封禁普通用户")
            if account["status"] != "NORMAL":
                raise DomainError("STATE", "账号已被封禁")
            connection.execute("UPDATE accounts SET status='BANNED' WHERE id=?", (account_id,))
            connection.execute("UPDATE sessions SET revoked_at=? WHERE account_id=? AND revoked_at IS NULL",
                               (self._now(), account_id))
            connection.execute("INSERT INTO bans VALUES (?,?,?,?,?,NULL,NULL)",
                               (self._new_id(), account_id, actor["id"], reason, self._now()))
            products = connection.execute(
                "SELECT * FROM products WHERE seller_id=? AND state NOT IN ('DRAFT','SOLD')", (account_id,)
            ).fetchall()
            for row in products:
                product = dict(row)
                self._invalidate_pending_review(connection, product, f"账号封禁：{reason}")
                connection.execute(
                    "UPDATE products SET state='OFF_SHELF',ban_restriction=1,"
                    "row_version=row_version+1,updated_at=? WHERE id=?", (self._now(), product["id"])
                )
                self._audit(connection, actor, "ban_product", product["id"],
                            product["state"], "OFF_SHELF", reason=reason)
            reservations = connection.execute(
                "SELECT * FROM reservations WHERE (buyer_id=? OR seller_id=?) "
                "AND state IN ('PENDING','CONFIRMED')", (account_id, account_id)
            ).fetchall()
            for row in reservations:
                reservation = dict(row)
                self._cancel_linked(connection, actor, reservation, f"账号封禁：{reason}")
                product = self._one(connection, "products", reservation["product_id"])
                if product["seller_id"] != account_id:
                    self._release_product(connection, product)
            self._audit(connection, actor, "ban_account", account_id, "NORMAL", "BANNED", reason=reason)
            return public_account(self._one(connection, "accounts", account_id))

    def unban_account(self, token, account_id, reason):
        """Restore identity access, without relisting items or reviving sessions."""
        with self._atomic(token, "unban_account", account_id, "ADMIN") as (connection, actor):
            reason = required(reason, "解封原因")
            account = self._one(connection, "accounts", account_id)
            if account["role"] != "USER" or account["status"] != "BANNED":
                raise DomainError("STATE", "只能解封处于封禁状态的普通用户")
            connection.execute("UPDATE accounts SET status='NORMAL' WHERE id=?", (account_id,))
            connection.execute("UPDATE bans SET lifted_by=?,lifted_at=? WHERE account_id=? AND lifted_at IS NULL",
                               (actor["id"], self._now(), account_id))
            self._audit(connection, actor, "unban_account", account_id, "BANNED", "NORMAL", reason=reason)
            return public_account(self._one(connection, "accounts", account_id))

    def statistics(self, token, start=None, end=None):
        """Aggregate completed immutable prices, inclusive of completion bounds."""
        with self._read(token) as (connection, actor):
            if start is not None and end is not None and start > end:
                raise DomainError("VALIDATION", "开始时间不能晚于结束时间")
            conditions = ["state='COMPLETED'"]
            parameters = []
            if actor["role"] == "USER":
                conditions.append("seller_id=?")
                parameters.append(actor["id"])
            if start is not None:
                conditions.append("completed_at>=?")
                parameters.append(start)
            if end is not None:
                conditions.append("completed_at<=?")
                parameters.append(end)
            rows = connection.execute(
                "SELECT * FROM reservations WHERE " + " AND ".join(conditions), parameters
            ).fetchall()
            categories = {name: {"category": name, "on_sale": 0, "completed": 0, "amount_cents": 0}
                          for name in CATEGORIES}
            for row in rows:
                snapshot = load_json(row["snapshot_json"])
                bucket = categories[snapshot["category"]]
                bucket["completed"] += 1
                bucket["amount_cents"] += money_cents(snapshot["price"])
            if actor["role"] == "USER":
                for row in connection.execute(
                    "SELECT content_json FROM products WHERE seller_id=? AND state='ON_SALE'", (actor["id"],)
                ):
                    content = load_json(row["content_json"])
                    categories[content["category"]]["on_sale"] += 1
            amount = sum(item["amount_cents"] for item in categories.values())
            for bucket in categories.values():
                bucket["amount"] = format_money(bucket["amount_cents"])
            return {
                "scope": "platform" if actor["role"] == "ADMIN" else "mine",
                "completed": len(rows), "amount_cents": amount, "amount": format_money(amount),
                "categories": list(categories.values()), "start": start, "end": end,
                "notice": "金额为完成预约的标价汇总，不代表已核验的实际付款。",
            }

    def list_logs(self, token, operation="", object_id="", result="", page=1,
                  start=None, end=None, actor_id=""):
        """Apply authorization before filters and redact private draft details."""
        with self._read(token) as (connection, actor):
            if not isinstance(page, int) or isinstance(page, bool) or page < 1:
                raise DomainError("VALIDATION", "页码须为正整数")
            conditions = []
            parameters = []
            if start is not None and end is not None and start > end:
                raise DomainError("VALIDATION", "开始时间不能晚于结束时间")
            if actor["role"] != "ADMIN":
                conditions.append(
                    "(actor_id=? OR (result!='FAILURE' AND ("
                    "object_id IN (SELECT id FROM products WHERE seller_id=?) OR "
                    "object_id IN (SELECT id FROM reservations WHERE buyer_id=? OR seller_id=?))))"
                )
                parameters.extend([actor["id"]] * 4)
                if actor_id and actor_id != actor["id"]:
                    raise DomainError("FORBIDDEN", "普通用户不能按他人身份查询日志")
            if actor_id:
                conditions.append("actor_id=?")
                parameters.append(actor_id)
            if start is not None:
                conditions.append("created_at>=?")
                parameters.append(start)
            if end is not None:
                conditions.append("created_at<=?")
                parameters.append(end)
            for field, value in (("operation", operation), ("object_id", object_id), ("result", result)):
                if value:
                    conditions.append(f"{field}=?")
                    parameters.append(value)
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            total = connection.execute("SELECT COUNT(*) FROM audit_logs" + where, parameters).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM audit_logs" + where + " ORDER BY created_at DESC,id DESC LIMIT 50 OFFSET ?",
                (*parameters, (page - 1) * 50),
            ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                details = load_json(item.pop("details_json"))
                if item["private_owner"] and item["private_owner"] != actor["id"]:
                    details = {}
                item["details"] = details
                items.append(item)
            return {"items": items, "total": total, "page": page, "page_size": 50}
