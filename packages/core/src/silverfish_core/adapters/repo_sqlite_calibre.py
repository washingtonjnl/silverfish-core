"""SQLite-Calibre implementation of the ``MetadataRepository`` port (read side).

Maps the real Calibre ``metadata.db`` schema to the neutral domain models. The
rating stored in the DB is on the 0-10 scale, which is exactly the domain scale,
so it maps across directly (no conversion). Consumers that want Calibre-desktop
compatibility use this repository.
"""

from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql.selectable import Select

from silverfish_core.adapters import _calibre_schema as cs
from silverfish_core.domain import models as dm
from silverfish_core.ports.types import (
    Page,
    SearchFilters,
    SortDirection,
    SortField,
    SortOrder,
)

_SORT_COLUMNS = {
    SortField.TITLE: cs.Book.sort,
    SortField.PUBDATE: cs.Book.id,  # placeholder until pubdate is mapped
    SortField.TIMESTAMP: cs.Book.id,
    SortField.LAST_MODIFIED: cs.Book.id,
    SortField.SERIES: cs.Book.series_index,
    SortField.AUTHOR: cs.Book.author_sort,
    SortField.RATING: cs.Book.id,
}


class SqliteCalibreRepository:
    """Read book metadata from a Calibre ``metadata.db``."""

    def __init__(self, db_path: Path) -> None:
        # Read-only intent for now; a single engine reused across calls.
        self._engine = create_engine(f"sqlite:///{db_path}")

    def close(self) -> None:
        self._engine.dispose()

    # --- mapping ------------------------------------------------------------

    def _to_domain(self, row: cs.Book) -> dm.Book:
        series = (
            dm.Series(name=row.series[0].name, sort=row.series[0].sort or row.series[0].name)
            if row.series
            else None
        )
        rating = row.ratings[0].rating if row.ratings else None
        return dm.Book(
            id=row.id,
            title=row.title,
            sort=row.sort or row.title,
            author_sort=row.author_sort or "",
            authors=tuple(
                dm.Author(name=a.name, sort=a.sort or a.name, link="") for a in row.authors
            ),
            tags=tuple(dm.Tag(name=t.name) for t in row.tags),
            series=series,
            series_index=row.series_index,
            rating=rating,
            languages=tuple(lang.lang_code for lang in row.languages),
            publisher=row.publishers[0].name if row.publishers else None,
            identifiers=tuple(dm.Identifier(scheme=i.type, value=i.val) for i in row.identifiers),
            formats=tuple(
                dm.BookFormat(extension=d.format, size_bytes=d.uncompressed_size, name=d.name)
                for d in row.data
            ),
            comment=row.comments[0].text if row.comments else None,
            has_cover=bool(row.has_cover),
            uuid=row.uuid,
        )

    def _eager(self, stmt: Select[tuple[cs.Book]]) -> Select[tuple[cs.Book]]:
        return stmt.options(
            selectinload(cs.Book.authors),
            selectinload(cs.Book.tags),
            selectinload(cs.Book.series),
            selectinload(cs.Book.ratings),
            selectinload(cs.Book.languages),
            selectinload(cs.Book.publishers),
            selectinload(cs.Book.data),
            selectinload(cs.Book.comments),
            selectinload(cs.Book.identifiers),
        )

    # --- reads --------------------------------------------------------------

    def get_book(self, book_id: int) -> dm.Book | None:
        with Session(self._engine) as session:
            stmt = self._eager(select(cs.Book).where(cs.Book.id == book_id))
            row = session.scalars(stmt).one_or_none()
            return self._to_domain(row) if row is not None else None

    def list_books(self, *, page: int, page_size: int, sort: SortOrder) -> Page[dm.Book]:
        with Session(self._engine) as session:
            total = session.scalar(select(func.count()).select_from(cs.Book)) or 0
            column = _SORT_COLUMNS[sort.field]
            ordering = column.desc() if sort.direction is SortDirection.DESC else column.asc()
            stmt = (
                self._eager(select(cs.Book))
                .order_by(ordering)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            rows = session.scalars(stmt).all()
            return self._page(rows, total, page, page_size)

    def search(
        self, term: str, *, filters: SearchFilters, page: int, page_size: int
    ) -> Page[dm.Book]:
        with Session(self._engine) as session:
            stmt = self._eager(select(cs.Book))
            stmt = self._apply_term(stmt, term)
            stmt = self._apply_filters(stmt, filters)

            count_stmt = self._apply_filters(self._apply_term(select(cs.Book.id), term), filters)
            total = session.scalar(select(func.count()).select_from(count_stmt.subquery())) or 0

            stmt = stmt.order_by(cs.Book.sort.asc()).offset((page - 1) * page_size).limit(page_size)
            rows = session.scalars(stmt).all()
            return self._page(rows, total, page, page_size)

    # --- query helpers ------------------------------------------------------

    def _apply_term[R](self, stmt: Select[tuple[R]], term: str) -> Select[tuple[R]]:
        term = term.strip()
        if not term:
            return stmt
        like = f"%{term.lower()}%"
        title_match = func.lower(cs.Book.title).like(like)
        author_match = cs.Book.authors.any(func.lower(cs.Author.name).like(like))
        series_match = cs.Book.series.any(func.lower(cs.Series.name).like(like))
        tag_match = cs.Book.tags.any(func.lower(cs.Tag.name).like(like))
        return stmt.where(title_match | author_match | series_match | tag_match)

    def _apply_filters[R](self, stmt: Select[tuple[R]], filters: SearchFilters) -> Select[tuple[R]]:
        for tag in filters.include_tags:
            stmt = stmt.where(cs.Book.tags.any(func.lower(cs.Tag.name) == tag.lower()))
        for tag in filters.exclude_tags:
            stmt = stmt.where(~cs.Book.tags.any(func.lower(cs.Tag.name) == tag.lower()))
        for name in filters.include_series:
            stmt = stmt.where(cs.Book.series.any(func.lower(cs.Series.name) == name.lower()))
        for name in filters.exclude_series:
            stmt = stmt.where(~cs.Book.series.any(func.lower(cs.Series.name) == name.lower()))
        if filters.languages:
            wanted = {lang.lower() for lang in filters.languages}
            stmt = stmt.where(cs.Book.languages.any(func.lower(cs.Language.lang_code).in_(wanted)))
        if filters.formats:
            wanted = {fmt.lower() for fmt in filters.formats}
            stmt = stmt.where(cs.Book.data.any(func.lower(cs.Data.format).in_(wanted)))
        if filters.publisher:
            stmt = stmt.where(
                cs.Book.publishers.any(func.lower(cs.Publisher.name) == filters.publisher.lower())
            )
        if filters.rating_min is not None:
            stmt = stmt.where(cs.Book.ratings.any(cs.Rating.rating >= filters.rating_min))
        if filters.rating_max is not None:
            stmt = stmt.where(cs.Book.ratings.any(cs.Rating.rating <= filters.rating_max))
        return stmt

    def _page(
        self, rows: Sequence[cs.Book], total: int, page: int, page_size: int
    ) -> Page[dm.Book]:
        return Page(
            items=tuple(self._to_domain(r) for r in rows),
            total=total,
            page=page,
            page_size=page_size,
        )

    # --- writes (implemented in a later step) -------------------------------

    def create_book(self, book: dm.Book) -> dm.Book:
        raise NotImplementedError("create_book is implemented in the write step")

    def update_book(self, book: dm.Book) -> dm.Book:
        raise NotImplementedError("update_book is implemented in the write step")

    def delete_book(self, book_id: int) -> None:
        raise NotImplementedError("delete_book is implemented in the write step")
