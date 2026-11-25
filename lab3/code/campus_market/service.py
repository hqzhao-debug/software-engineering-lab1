"""Composition root: a single application facade, separate domain modules."""

from .accounts import AccountMixin
from .admin import AdminMixin
from .base import BaseService
from .products import ProductMixin
from .trades import TradeMixin


class Market(ProductMixin, TradeMixin, AdminMixin, AccountMixin, BaseService):
    """Entry point shared by the command-line interface and automated tests."""
