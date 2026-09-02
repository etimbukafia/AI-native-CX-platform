"""Typed CX history reads."""

from cx_platform.domain.models import CustomerHistory
from cx_platform.persistence.sqlite import CXRepositories


class CXHistoryService:
    """Read authoritative customer-service history from CX SQLite."""

    def __init__(self, repositories: CXRepositories) -> None:
        self.repositories = repositories

    def get_customer_history(self, customer_id: str) -> CustomerHistory:
        """Return the durable CX history for one customer."""

        return self.repositories.customer_history(customer_id)


__all__ = ["CXHistoryService"]
