"""Framework-independent advanced table model.

Semantics (documented and tested):
* Filters are combined with ``mode`` ("and" by default, or "or") across *all* filters.
* Global search is always ANDed with the column filters.
* Sorting supports several keys; it is stable and None values always sort last.
* Pagination is applied after filtering and sorting.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

OPS = ("eq", "ne", "contains", "gt", "gte", "lt", "lte", "between", "in")


@dataclass(frozen=True)
class Column:
    key: str
    title: str = ""
    visible: bool = True


@dataclass(frozen=True)
class Filter:
    column: str
    op: str
    value: Any


@dataclass
class Page:
    rows: list[dict]
    page: int
    page_size: int
    total: int
    pages: int


def _match(row_value: Any, op: str, value: Any) -> bool:
    if op not in OPS:
        raise ValueError(f"Unknown filter op {op!r}")
    if row_value is None:
        return False
    if op == "eq":
        return row_value == value
    if op == "ne":
        return row_value != value
    if op == "contains":
        return str(value).lower() in str(row_value).lower()
    if op == "gt":
        return row_value > value
    if op == "gte":
        return row_value >= value
    if op == "lt":
        return row_value < value
    if op == "lte":
        return row_value <= value
    if op == "between":
        low, high = value
        return low <= row_value <= high
    return row_value in value


class TableModel:
    def __init__(self, columns: Iterable[Column | str], rows: Iterable[dict], *, state: str = "ready",
                 error: str = ""):
        self.columns = [c if isinstance(c, Column) else Column(c, c.title()) for c in columns]
        self._rows = list(rows)
        self.filters: list[Filter] = []
        self.filter_mode = "and"
        self.search_text = ""
        self.sort_keys: list[tuple[str, bool]] = []  # (column, descending)
        self.page_size = 25
        self.selection: set[int] = set()  # selection holds stable row ids (index in source data)
        self._state = state
        self.error = error

    # -- configuration ------------------------------------------------------------------
    def add_filter(self, column: str, op: str, value: Any) -> None:
        self._column(column)
        if op not in OPS:
            raise ValueError(f"Unknown filter op {op!r}")
        self.filters.append(Filter(column, op, value))

    def clear_filters(self) -> None:
        self.filters.clear()

    def set_sort(self, *keys: tuple[str, bool]) -> None:
        for k, _ in keys:
            self._column(k)
        self.sort_keys = list(keys)

    def _column(self, key: str) -> Column:
        for c in self.columns:
            if c.key == key:
                return c
        raise KeyError(f"Unknown column {key!r}")

    def set_visible(self, key: str, visible: bool) -> None:
        idx = self.columns.index(self._column(key))
        self.columns[idx] = Column(key, self.columns[idx].title, visible)

    def move_column(self, key: str, new_index: int) -> None:
        col = self._column(key)
        self.columns.remove(col)
        self.columns.insert(new_index, col)

    # -- processing ---------------------------------------------------------------------
    @property
    def state(self) -> str:
        if self._state in ("loading", "error", "stale"):
            return self._state
        if not self._rows:
            return "empty"
        return "no_results" if not self.result_rows() else "ready"

    def result_rows(self) -> list[dict]:
        indexed = list(enumerate(self._rows))
        if self.filters:
            combine = all if self.filter_mode == "and" else any
            indexed = [(i, r) for i, r in indexed
                       if combine(_match(r.get(f.column), f.op, f.value) for f in self.filters)]
        if self.search_text:
            needle = self.search_text.lower()
            indexed = [(i, r) for i, r in indexed
                       if any(needle in str(r.get(c.key, "")).lower() for c in self.columns if c.visible)]
        for key, desc in reversed(self.sort_keys):  # stable multi-key sort
            present = [(i, r) for i, r in indexed if r.get(key) is not None]
            missing = [(i, r) for i, r in indexed if r.get(key) is None]
            present.sort(key=lambda p: p[1][key], reverse=desc)
            indexed = present + missing
        return [{**r, "_id": i} for i, r in indexed]

    def page(self, number: int = 1) -> Page:
        rows = self.result_rows()
        size = max(1, self.page_size)
        pages = max(1, -(-len(rows) // size))
        number = min(max(1, number), pages)
        return Page(rows[(number - 1) * size: number * size], number, size, len(rows), pages)


    # -- grouping / aggregation ---------------------------------------------------------
    def group_by(self, column: str, aggregates: Mapping[str, tuple[str, str]] | None = None) -> list[dict]:
        """Group filtered and searched rows by a column and calculate aggregates.

        Each aggregate maps an output name to (operation, source_column).
        Supported operations are count, sum, avg, min and max. Use "*" as the
        source for count to count every row in a group; otherwise count ignores
        null values. Numeric operations reject booleans and non-numeric values.
        Groups retain first-seen order and their source rows retain current sort
        order. Pagination is deliberately not applied.
        """
        self._column(column)
        specs = dict(aggregates or {})
        if any(not isinstance(name, str) or not name for name in specs):
            raise ValueError("aggregate names must be non-empty strings")
        allowed = {"count", "sum", "avg", "min", "max"}
        for name, spec in specs.items():
            if (not isinstance(spec, tuple) or len(spec) != 2
                    or spec[0] not in allowed or not isinstance(spec[1], str)):
                raise ValueError(f"invalid aggregate specification for {name!r}")
            operation, source = spec
            if operation == "count" and source == "*":
                continue
            self._column(source)

        grouped: dict[Any, list[dict]] = {}
        for row in self.result_rows():
            value = row.get(column)
            try:
                grouped.setdefault(value, []).append(row)
            except TypeError as exc:
                raise ValueError(f"grouping values in {column!r} must be hashable") from exc

        output = []
        for value, rows in grouped.items():
            values: dict[str, Any] = {}
            for name, (operation, source) in specs.items():
                selected = [row.get(source) for row in rows] if source != "*" else [1] * len(rows)
                present = [item for item in selected if item is not None]
                if operation == "count":
                    values[name] = len(present)
                elif not present:
                    values[name] = None
                elif operation in {"sum", "avg"}:
                    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in present):
                        raise ValueError(f"{operation} aggregate {name!r} requires numeric values")
                    total = sum(present)
                    values[name] = total if operation == "sum" else total / len(present)
                else:
                    try:
                        values[name] = min(present) if operation == "min" else max(present)
                    except TypeError as exc:
                        raise ValueError(f"{operation} aggregate {name!r} values are not comparable") from exc
            output.append({"key": value, "rows": rows, "count": len(rows), "aggregates": values})
        return output

    # -- selection / export -------------------------------------------------------------
    def select(self, row_id: int, selected: bool = True) -> None:
        (self.selection.add if selected else self.selection.discard)(row_id)

    def selected_rows(self) -> list[dict]:
        return [r for r in self.result_rows() if r["_id"] in self.selection]

    def export_csv(self, only_selected: bool = False) -> str:
        cols = [c for c in self.columns if c.visible]
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow([c.title or c.key for c in cols])
        for r in (self.selected_rows() if only_selected else self.result_rows()):
            w.writerow(["" if r.get(c.key) is None else r.get(c.key) for c in cols])
        return buf.getvalue()
