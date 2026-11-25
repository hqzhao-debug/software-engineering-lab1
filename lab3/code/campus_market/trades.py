"""Reservation state machine with transactional ownership and idempotency.

Every state-changing operation acquires the database write transaction before
reading permissions or state.  SQLite serializes competing writers; partial
unique indexes provide an independent guard against double booking/completion.
"""

from .models import DomainError, RESERVATION_STATES, json_text, load_json, required


ACTIVE_STATES = {"PENDING", "CONFIRMED"}
CONTACT_STATES = {"PENDING", "CONFIRMED", "COMPLETED"}
PAGE_SIZE = 20


class TradeMixin:
    """Implement reservation, confirmation, rejection, cancellation and sale."""

    @staticmethod
    def _check_participant(reservation, actor):
        if actor["id"] not in {reservation["buyer_id"], reservation["seller_id"]}:
            raise DomainError("FORBIDDEN", "只能操作本人参与的预约")

    @staticmethod
    def _check_seller(reservation, actor):
        if actor["id"] != reservation["seller_id"] or actor["role"] != "USER":
            raise DomainError("FORBIDDEN", "此操作只能由商品卖家执行")

    @staticmethod
    def _check_trade_consistency(conn, product, reservation):
        """Fail closed on inconsistent links; do not repair them during a trade."""
        if (
            product["id"] != reservation["product_id"]
            or product["seller_id"] != reservation["seller_id"]
            or reservation["buyer_id"] == reservation["seller_id"]
        ):
            raise DomainError("INCONSISTENT", "预约与商品的归属信息不一致")
        if reservation["state"] not in ACTIVE_STATES:
            raise DomainError("INVALID_STATE", "预约已结束，不能再次改变状态")
        if product["state"] != reservation["state"]:
            raise DomainError("INCONSISTENT", "商品与预约的当前状态不一致")
        active = conn.execute(
            "SELECT id FROM reservations WHERE product_id=? "
            "AND state IN ('PENDING','CONFIRMED')",
            (product["id"],),
        ).fetchall()
        if len(active) != 1 or active[0]["id"] != reservation["id"]:
            raise DomainError("INCONSISTENT", "商品有效预约约束不一致")

    def _check_trade_accounts(self, conn, reservation):
        """Management changes must have ended affected trades in one commit."""
        for account_id in (reservation["buyer_id"], reservation["seller_id"]):
            account = self._one(conn, "accounts", account_id)
            if (
                account["status"] != "NORMAL"
                or account["role"] != "USER"
                or not account["verified"]
            ):
                raise DomainError("RESTRICTED", "交易参与账号当前不可交易")

    def _reservation_view(self, conn, reservation, actor):
        """Contact access is computed from current state, not stored snapshots."""
        is_participant = actor["id"] in {
            reservation["buyer_id"], reservation["seller_id"]
        }
        if not is_participant and actor["role"] != "ADMIN":
            raise DomainError("FORBIDDEN", "无权查看该预约")
        result = dict(reservation)
        result["snapshot"] = load_json(result.pop("snapshot_json"))
        buyer = self._one(conn, "accounts", reservation["buyer_id"])
        seller = self._one(conn, "accounts", reservation["seller_id"])
        result["buyer_username"] = buyer["username"]
        result["seller_username"] = seller["username"]
        if is_participant and reservation["state"] in CONTACT_STATES:
            other = seller if actor["id"] == buyer["id"] else buyer
            result["counterparty_email"] = other["email"]
        # Administrative account lookup is a separate authorized operation.
        # Returning an admin reservation does not automatically disclose emails.
        return result

    def _current_reservation(self, conn, reservation_id, actor):
        reservation = self._one(conn, "reservations", reservation_id)
        return self._reservation_view(conn, reservation, actor)

    def _release_product(self, conn, product):
        """Release a closed reservation only if publishing is still authorized.

        Re-read all current restrictions so an administrative caller cannot
        accidentally restore a stale, previously legal product snapshot.
        Callers must close the active reservation before invoking this helper.
        """
        product = self._one(conn, "products", product["id"])
        active = conn.execute(
            "SELECT id FROM reservations WHERE product_id=? "
            "AND state IN ('PENDING','CONFIRMED') LIMIT 1",
            (product["id"],),
        ).fetchone()
        if active:
            raise DomainError("INCONSISTENT", "仍有有效预约，不能释放商品")
        if product["state"] == "SOLD":
            raise DomainError("INVALID_STATE", "已成交商品不能恢复在售")
        seller = self._one(conn, "accounts", product["seller_id"])
        if product["active_restriction"]:
            state = "VIOLATION"
        elif (
            product["ban_restriction"]
            or seller["status"] != "NORMAL"
            or not seller["verified"]
        ):
            state = "OFF_SHELF"
        else:
            submission = conn.execute(
                "SELECT r.status,v.content_version FROM review_submissions r "
                "JOIN submitted_versions v ON v.id=r.version_id WHERE r.id=?",
                (product["current_submission_id"],),
            ).fetchone()
            legal = bool(
                submission
                and submission["status"] == "APPROVED"
                and submission["content_version"] == product["content_version"]
            )
            state = "ON_SALE" if legal else "OFF_SHELF"
        conn.execute(
            "UPDATE products SET state=?,row_version=row_version+1,updated_at=? WHERE id=?",
            (state, self._now(), product["id"]),
        )
        return state

    def reserve(self, token, product_id, content_version, message, request_key):
        """Atomically occupy one published item and freeze its agreed content."""
        payload = {
            "product_id": product_id,
            "content_version": content_version,
            "message": message,
        }
        with self._atomic(token, "reserve", product_id, role="USER") as pair:
            conn, actor = pair
            replay = self._idempotent(conn, actor, "reserve", request_key, payload)
            if replay:
                return self._current_reservation(conn, replay, actor)
            product = self._one(conn, "products", product_id)
            if product["seller_id"] == actor["id"]:
                raise DomainError("FORBIDDEN", "不能预约本人发布的商品")
            existing = conn.execute(
                "SELECT * FROM reservations WHERE product_id=? AND buyer_id=? "
                "AND state IN ('PENDING','CONFIRMED')",
                (product_id, actor["id"]),
            ).fetchone()
            if existing:
                # A second device can obtain the same active reservation even
                # with a different request key.  A closed reservation never
                # follows this path and cannot be resurrected.
                self._remember(
                    conn, actor, "reserve", request_key, payload, existing["id"]
                )
                self._audit(
                    conn,
                    actor,
                    "reserve",
                    existing["id"],
                    before=existing["state"],
                    after=existing["state"],
                    result="REPLAY",
                    reason="本人已有该商品的有效预约",
                )
                return self._reservation_view(conn, dict(existing), actor)
            message = required(message, "面交留言")
            if (
                not isinstance(content_version, int)
                or isinstance(content_version, bool)
                or content_version != product["content_version"]
            ):
                raise DomainError("STALE_VERSION", "商品内容已变化，请重新确认标题与价格")
            if product["state"] != "ON_SALE":
                raise DomainError("INVALID_STATE", "商品当前不可预约")
            if product["active_restriction"] or product["ban_restriction"]:
                raise DomainError("RESTRICTED", "商品当前受到发布限制")
            seller = self._one(conn, "accounts", product["seller_id"])
            if (
                seller["status"] != "NORMAL"
                or seller["role"] != "USER"
                or not seller["verified"]
            ):
                raise DomainError("RESTRICTED", "卖家当前不可交易")
            submission = conn.execute(
                "SELECT r.status,v.content_version FROM review_submissions r "
                "JOIN submitted_versions v ON v.id=r.version_id WHERE r.id=?",
                (product["current_submission_id"],),
            ).fetchone()
            if (
                not submission
                or submission["status"] != "APPROVED"
                or submission["content_version"] != product["content_version"]
            ):
                raise DomainError("INCONSISTENT", "商品缺少对应版本的审核通过记录")
            self._check_no_reservation(conn, product_id)
            completed = conn.execute(
                "SELECT id FROM reservations WHERE product_id=? AND state='COMPLETED'",
                (product_id,),
            ).fetchone()
            if completed:
                raise DomainError("INVALID_STATE", "该单件商品已经完成交易")
            reservation_id = self._new_id()
            snapshot = load_json(product["content_json"])
            snapshot["buyer_message"] = message
            now = self._now()
            conn.execute(
                "INSERT INTO reservations "
                "(id,product_id,buyer_id,seller_id,state,snapshot_json,message,"
                "created_at,confirmed_at,closed_at,completed_at,closed_by,close_reason) "
                "VALUES (?,?,?,?,'PENDING',?,?,?,NULL,NULL,NULL,NULL,'')",
                (
                    reservation_id,
                    product_id,
                    actor["id"],
                    product["seller_id"],
                    json_text(snapshot),
                    message,
                    now,
                ),
            )
            conn.execute(
                "UPDATE products SET state='PENDING',row_version=row_version+1,"
                "updated_at=? WHERE id=?",
                (now, product_id),
            )
            self._audit(
                conn,
                actor,
                "reserve",
                reservation_id,
                before="ON_SALE",
                after="PENDING",
                details={"product_id": product_id},
            )
            self._remember(conn, actor, "reserve", request_key, payload, reservation_id)
            return self._current_reservation(conn, reservation_id, actor)

    def confirm(self, token, reservation_id, request_key):
        """The seller accepts a pending reservation; the item stays occupied."""
        payload = {"reservation_id": reservation_id}
        with self._atomic(token, "confirm", reservation_id, role="USER") as pair:
            conn, actor = pair
            reservation = self._one(conn, "reservations", reservation_id)
            self._check_seller(reservation, actor)
            replay = self._idempotent(conn, actor, "confirm", request_key, payload)
            if replay:
                return self._current_reservation(conn, replay, actor)
            if reservation["state"] != "PENDING":
                raise DomainError("INVALID_STATE", "只能确认待确认的预约")
            product = self._one(conn, "products", reservation["product_id"])
            self._check_trade_consistency(conn, product, reservation)
            self._check_trade_accounts(conn, reservation)
            if product["active_restriction"] or product["ban_restriction"]:
                raise DomainError("RESTRICTED", "商品当前受到发布限制")
            now = self._now()
            conn.execute(
                "UPDATE reservations SET state='CONFIRMED',confirmed_at=? WHERE id=?",
                (now, reservation_id),
            )
            conn.execute(
                "UPDATE products SET state='CONFIRMED',row_version=row_version+1,"
                "updated_at=? WHERE id=?",
                (now, product["id"]),
            )
            self._audit(
                conn,
                actor,
                "confirm",
                reservation_id,
                before="PENDING",
                after="CONFIRMED",
                details={"product_id": product["id"]},
            )
            self._remember(conn, actor, "confirm", request_key, payload, reservation_id)
            return self._current_reservation(conn, reservation_id, actor)

    def _close_trade(self, conn, actor, reservation, product, state, reason, operation):
        """Apply the common closed-state data and release logic in one transaction."""
        conn.execute(
            "UPDATE reservations SET state=?,closed_at=?,closed_by=?,close_reason=? "
            "WHERE id=?",
            (state, self._now(), actor["id"], reason, reservation["id"]),
        )
        product_state = self._release_product(conn, product)
        self._audit(
            conn,
            actor,
            operation,
            reservation["id"],
            before=reservation["state"],
            after=state,
            reason=reason,
            details={"product_id": product["id"], "product_state": product_state},
        )

    @staticmethod
    def _optional_reason(reason):
        if not isinstance(reason, str):
            raise DomainError("INVALID_INPUT", "原因必须是文本")
        return reason.strip()

    def reject(self, token, reservation_id, request_key, reason=""):
        """The seller may reject only a pending reservation; reason is optional."""
        payload = {"reservation_id": reservation_id, "reason": reason}
        with self._atomic(token, "reject", reservation_id, role="USER") as pair:
            conn, actor = pair
            reservation = self._one(conn, "reservations", reservation_id)
            self._check_seller(reservation, actor)
            replay = self._idempotent(conn, actor, "reject", request_key, payload)
            if replay:
                return self._current_reservation(conn, replay, actor)
            reason = self._optional_reason(reason)
            if reservation["state"] != "PENDING":
                raise DomainError("INVALID_STATE", "只能拒绝待确认预约，已确认请使用取消")
            product = self._one(conn, "products", reservation["product_id"])
            self._check_trade_consistency(conn, product, reservation)
            self._close_trade(
                conn, actor, reservation, product, "REJECTED", reason, "reject"
            )
            self._remember(conn, actor, "reject", request_key, payload, reservation_id)
            return self._current_reservation(conn, reservation_id, actor)

    def cancel(self, token, reservation_id, request_key, reason=""):
        """Cancel using the current stage, including a confirmation that just won.

        A buyer's old pending page may still cancel a now-confirmed reservation
        if a reason was supplied.  A seller must reject, not cancel, pending
        reservations.  Neither party can alter a closed reservation.
        """
        payload = {"reservation_id": reservation_id, "reason": reason}
        with self._atomic(token, "cancel", reservation_id, role="USER") as pair:
            conn, actor = pair
            reservation = self._one(conn, "reservations", reservation_id)
            self._check_participant(reservation, actor)
            replay = self._idempotent(conn, actor, "cancel", request_key, payload)
            if replay:
                return self._current_reservation(conn, replay, actor)
            reason = self._optional_reason(reason)
            if reservation["state"] == "PENDING":
                if actor["id"] != reservation["buyer_id"]:
                    raise DomainError("FORBIDDEN", "待确认阶段卖家应使用拒绝操作")
            elif reservation["state"] == "CONFIRMED":
                reason = required(reason, "取消原因")
            else:
                raise DomainError("INVALID_STATE", "预约已结束，不能取消")
            product = self._one(conn, "products", reservation["product_id"])
            self._check_trade_consistency(conn, product, reservation)
            self._close_trade(
                conn, actor, reservation, product, "CANCELLED", reason, "cancel"
            )
            self._remember(conn, actor, "cancel", request_key, payload, reservation_id)
            return self._current_reservation(conn, reservation_id, actor)

    def complete(self, token, reservation_id, request_key):
        """Record the seller's completion declaration without claiming payment."""
        payload = {"reservation_id": reservation_id}
        with self._atomic(token, "complete", reservation_id, role="USER") as pair:
            conn, actor = pair
            reservation = self._one(conn, "reservations", reservation_id)
            self._check_seller(reservation, actor)
            replay = self._idempotent(conn, actor, "complete", request_key, payload)
            if replay:
                return self._current_reservation(conn, replay, actor)
            if reservation["state"] != "CONFIRMED":
                raise DomainError("INVALID_STATE", "只有已确认预约可以完成")
            product = self._one(conn, "products", reservation["product_id"])
            self._check_trade_consistency(conn, product, reservation)
            self._check_trade_accounts(conn, reservation)
            if product["active_restriction"] or product["ban_restriction"]:
                raise DomainError("RESTRICTED", "商品受到限制，不能标记完成")
            now = self._now()
            conn.execute(
                "UPDATE reservations SET state='COMPLETED',completed_at=?,closed_at=?,"
                "closed_by=? WHERE id=?",
                (now, now, actor["id"], reservation_id),
            )
            conn.execute(
                "UPDATE products SET state='SOLD',row_version=row_version+1,"
                "updated_at=? WHERE id=?",
                (now, product["id"]),
            )
            self._audit(
                conn,
                actor,
                "complete",
                reservation_id,
                before="CONFIRMED",
                after="COMPLETED",
                reason="卖家声明线下面交已完成",
                details={"product_id": product["id"]},
            )
            self._remember(conn, actor, "complete", request_key, payload, reservation_id)
            return self._current_reservation(conn, reservation_id, actor)

    def get_reservation(self, token, reservation_id):
        """Read one's transaction history, or authorized administrative history."""
        with self._read(token) as pair:
            conn, actor = pair
            return self._current_reservation(conn, reservation_id, actor)

    def list_reservations(self, token, side="all", state="", page=1):
        """Filter and paginate only after restricting rows to the caller's scope."""
        if side not in {"all", "buyer", "seller"}:
            raise DomainError("INVALID_INPUT", "交易方向应为 all、buyer 或 seller")
        if state and state not in RESERVATION_STATES:
            raise DomainError("INVALID_INPUT", "未知预约状态")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise DomainError("INVALID_INPUT", "页码必须是正整数")
        with self._read(token) as pair:
            conn, actor = pair
            clauses = []
            args = []
            if actor["role"] != "ADMIN":
                if side == "buyer":
                    clauses.append("buyer_id=?")
                    args.append(actor["id"])
                elif side == "seller":
                    clauses.append("seller_id=?")
                    args.append(actor["id"])
                else:
                    clauses.append("(buyer_id=? OR seller_id=?)")
                    args.extend((actor["id"], actor["id"]))
            elif side != "all":
                raise DomainError("INVALID_INPUT", "管理员查询请选择 all")
            if state:
                clauses.append("state=?")
                args.append(state)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            total = conn.execute(
                "SELECT COUNT(*) FROM reservations" + where, args
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT * FROM reservations" + where
                + " ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                [*args, PAGE_SIZE, (page - 1) * PAGE_SIZE],
            ).fetchall()
            return {
                "items": [self._reservation_view(conn, dict(row), actor) for row in rows],
                "total": total,
                "page": page,
                "page_size": PAGE_SIZE,
            }
