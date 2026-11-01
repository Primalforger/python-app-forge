"""Callback-backed server-side table model.

The backend owns filtering, searching and sorting. Each request carries a
validated immutable snapshot of the current table state and page coordinates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

FILTER_OPS = frozenset({"eq", "ne", "contains", "gt", "gte", "lt", "lte", "between", "in"})


@dataclass(frozen=True)
class ServerFilter:
    column: str
    op: str
    value: Any


@dataclass(frozen=True)
class TableQuery:
    filters: tuple[ServerFilter, ...]
    filter_mode: str
    search_text: str
    sort_keys: tuple[tuple[str, bool], ...]
    page: int
    page_size: int


@dataclass(frozen=True)
class ServerPage:
    rows: list[dict[str, Any]]
    page: int
    page_size: int
    total: int

    @property
    def pages(self) -> int:
        return max(1, (self.total + self.page_size - 1) // self.page_size)


QueryCallback = Callable[[TableQuery], ServerPage]


class ServerSideTableModel:
    """Table configuration whose page data is fetched by a host callback.

    The callback must apply all supplied filters, search and sort keys before
    pagination, and return the total number of matching rows before pagination.
    It must return exactly the requested page metadata. No local row cache is
    kept, so large datasets remain in the host's storage/query engine.
    """

    def __init__(self, columns: Iterable[str], query_callback: QueryCallback, *,
                 page_size: int = 25):
        self.columns = tuple(columns)
        if not self.columns or any(not isinstance(c, str) or not c for c in self.columns):
            raise ValueError("columns must contain non-empty string keys")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("column keys must be unique")
        if not callable(query_callback):
            raise TypeError("query_callback must be callable")
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
            raise ValueError("page_size must be a positive integer")
        self._query_callback = query_callback
        self.page_size = page_size
        self.filters: list[ServerFilter] = []
        self.filter_mode = "and"
        self.search_text = ""
        self.sort_keys: list[tuple[str, bool]] = []
        self._last_page: ServerPage | None = None

    def _column(self, key: str) -> None:
        if key not in self.columns:
            raise KeyError(f"Unknown column {key!r}")

    def add_filter(self, column: str, op: str, value: Any) -> None:
        self._column(column)
        if op not in FILTER_OPS:
            raise ValueError(f"Unknown filter op {op!r}")
        if op == "between" and (not isinstance(value, (tuple, list)) or len(value) != 2):
            raise ValueError("between filter requires a pair of values")
        if op == "in" and isinstance(value, (str, bytes)):
            raise ValueError("in filter requires a collection, not text")
        self.filters.append(ServerFilter(column, op, value))

    def clear_filters(self) -> None:
        self.filters.clear()

    def set_filter_mode(self, mode: str) -> None:
        if mode not in ("and", "or"):
            raise ValueError("filter mode must be 'and' or 'or'")
        self.filter_mode = mode

    def set_sort(self, *keys: tuple[str, bool]) -> None:
        for key, descending in keys:
            self._column(key)
            if not isinstance(descending, bool):
                raise ValueError("sort direction must be a boolean")
        self.sort_keys = list(keys)

    def query(self, page: int = 1) -> TableQuery:
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("page must be a positive integer")
        return TableQuery(tuple(self.filters), self.filter_mode, self.search_text,
                          tuple(self.sort_keys), page, self.page_size)

    def page(self, number: int = 1) -> ServerPage:
        request = self.query(number)
        result = self._query_callback(request)
        if not isinstance(result, ServerPage):
            raise TypeError("query_callback must return ServerPage")
        if (isinstance(result.total, bool) or not isinstance(result.total, int)
                or result.total < 0):
            raise ValueError("callback total must be a non-negative integer")
        if result.page != request.page or result.page_size != request.page_size:
            raise ValueError("callback page metadata must match the request")
        if len(result.rows) > request.page_size:
            raise ValueError("callback returned more rows than the requested page size")
        if result.total and not result.rows and request.page <= result.pages:
            raise ValueError("callback returned an empty page within the result range")
        self._last_page = result
        return result

    @property
    def state(self) -> str:
        if self._last_page is None:
            return "loading"
        if self._last_page.total == 0:
            return "empty"
        if not self._last_page.rows:
            return "no_results"
        return "ready"

    def refresh(self, page: int = 1) -> ServerPage:
        """Re-run the callback using the current state; no stale cache is reused."""
        self._last_page = None
        return self.page(page)
