"""SQLite-Calibre implementation of the ``MetadataRepository`` port.

Maps the real Calibre ``metadata.db`` schema to/from the neutral domain models.
The rating stored in the DB is on the 0-10 scale, which is exactly the domain
scale, so it maps across directly (no conversion). Writes compute sort keys,
path and uuid the way Calibre does and reuse existing entities, so the resulting
database is indistinguishable from one Calibre produced. Consumers that want
Calibre-desktop compatibility use this repository.
"""

import sqlite3
import uuid as uuid_module
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.pool import ConnectionPoolEntry
from sqlalchemy.sql.selectable import Select

from silverfish_core.adapters import _calibre_schema as cs
from silverfish_core.domain import models as dm
from silverfish_core.domain.rules import author_sort, build_path, title_sort
from silverfish_core.ports.types import (
    Page,
    SearchFilters,
    SortDirection,
    SortField,
    SortOrder,
)


def _register_calibre_functions(engine: Engine) -> None:
    """Register the SQL functions Calibre's triggers rely on.

    The ``books`` table has an insert trigger that calls ``title_sort(title)``
    and ``uuid4()`` to fill ``sort`` and ``uuid``. A plain SQLite connection does
    not know these, so inserts fail until we register them — matching what
    Calibre itself does on its connection. We reuse our own ``title_sort`` rule
    so the result is identical to ours.
    """

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: DBAPIConnection, _: ConnectionPoolEntry) -> None:
        if isinstance(dbapi_connection, sqlite3.Connection):
            dbapi_connection.create_function("title_sort", 1, _sql_title_sort)
            dbapi_connection.create_function("uuid4", 0, _sql_uuid4)


def _sql_title_sort(title: str | None) -> str:
    return title_sort(title) if title else ""


def _sql_uuid4() -> str:
    return str(uuid_module.uuid4())


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
        self._db_path = db_path
        self._engine = create_engine(f"sqlite:///{db_path}")
        _register_calibre_functions(self._engine)

    @property
    def db_path(self) -> Path:
        return self._db_path

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

    # --- file locations (library-relative; never exposed via the API) -------

    def cover_path(self, book_id: int) -> str | None:
        """Return the library-relative path to a book's cover, or ``None``.

        ``None`` when the book does not exist or has no cover.
        """
        with Session(self._engine) as session:
            row = session.get(cs.Book, book_id)
            if row is None or not row.has_cover:
                return None
            return f"{row.path}/cover.jpg"

    def format_path(self, book_id: int, book_format: str) -> str | None:
        """Return the library-relative path to a book's file in *book_format*.

        ``None`` when the book or that format does not exist. Format match is
        case-insensitive.
        """
        with Session(self._engine) as session:
            row = session.get(cs.Book, book_id)
            if row is None:
                return None
            wanted = book_format.upper()
            for data in row.data:
                if data.format.upper() == wanted:
                    return f"{row.path}/{data.name}.{data.format.lower()}"
            return None

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

    # --- writes -------------------------------------------------------------

    def create_book(self, book: dm.Book) -> dm.Book:
        """Insert a new book, computing Calibre-style sort/path/uuid and reusing
        existing entities. Returns the book with its assigned id.
        """
        sort = book.sort or title_sort(book.title)
        resolved_authors = self._resolve_author_sorts(book.authors)
        book_author_sort = book.author_sort or " & ".join(a.sort for a in resolved_authors)

        with Session(self._engine) as session:
            row = cs.Book(
                title=book.title,
                sort=sort,
                author_sort=book_author_sort,
                series_index=book.series_index,
                path="",  # set after we know the id
                has_cover=book.has_cover,
                uuid=book.uuid or str(uuid_module.uuid4()),
            )
            session.add(row)
            session.flush()  # assign row.id

            row.path = build_path(
                resolved_authors[0].name if resolved_authors else "Unknown",
                book.title,
                book_id=row.id,
            )

            row.authors = [self._upsert_author(session, a) for a in resolved_authors]
            row.tags = [self._upsert_tag(session, t.name) for t in book.tags]
            if book.series is not None:
                row.series = [self._upsert_series(session, book.series)]
            row.languages = [self._upsert_language(session, code) for code in book.languages]
            if book.publisher:
                row.publishers = [self._upsert_publisher(session, book.publisher)]
            if book.rating is not None:
                row.ratings = [self._upsert_rating(session, book.rating)]

            for fmt in book.formats:
                session.add(
                    cs.Data(
                        book=row.id,
                        format=fmt.extension.upper(),
                        uncompressed_size=fmt.size_bytes,
                        name=fmt.name,
                    )
                )
            if book.comment:
                session.add(cs.Comment(book=row.id, text=book.comment))
            for ident in book.identifiers:
                session.add(cs.Identifier(book=row.id, type=ident.scheme.lower(), val=ident.value))

            session.commit()
            new_id = row.id

        fetched = self.get_book(new_id)
        if fetched is None:  # pragma: no cover - just-created row must exist
            msg = "Failed to read back the created book"
            raise RuntimeError(msg)
        return fetched

    def update_book(self, book: dm.Book) -> dm.Book:
        """Update an existing book: fields, recomputed sort/author_sort, synced
        M2M relationships (orphans removed) and recomputed path on author/title
        change. Returns the updated book.
        """
        if book.id is None:
            msg = "update_book requires a book with an id"
            raise ValueError(msg)

        resolved_authors = self._resolve_author_sorts(book.authors)
        new_author_sort = book.author_sort or " & ".join(a.sort for a in resolved_authors)

        with Session(self._engine) as session:
            row = session.get(cs.Book, book.id)
            if row is None:
                msg = f"Book {book.id} does not exist"
                raise ValueError(msg)

            row.title = book.title
            row.sort = title_sort(book.title)
            row.author_sort = new_author_sort
            row.series_index = book.series_index
            row.has_cover = book.has_cover
            row.path = build_path(
                resolved_authors[0].name if resolved_authors else "Unknown",
                book.title,
                book_id=row.id,
            )

            old_authors = list(row.authors)
            old_tags = list(row.tags)
            old_series = list(row.series)
            old_publishers = list(row.publishers)
            old_ratings = list(row.ratings)

            row.authors = [self._upsert_author(session, a) for a in resolved_authors]
            row.tags = [self._upsert_tag(session, t.name) for t in book.tags]
            row.series = (
                [self._upsert_series(session, book.series)] if book.series is not None else []
            )
            row.languages = [self._upsert_language(session, code) for code in book.languages]
            row.publishers = (
                [self._upsert_publisher(session, book.publisher)] if book.publisher else []
            )
            row.ratings = (
                [self._upsert_rating(session, book.rating)] if book.rating is not None else []
            )

            self._sync_comment(session, row.id, book.comment)
            self._sync_identifiers(session, row.id, book.identifiers)

            session.flush()
            # Remove entities that no longer belong to any book.
            self._prune_orphans(session, "books_authors_link", old_authors)
            self._prune_orphans(session, "books_tags_link", old_tags)
            self._prune_orphans(session, "books_series_link", old_series)
            self._prune_orphans(session, "books_publishers_link", old_publishers)
            self._prune_orphans(session, "books_ratings_link", old_ratings)

            session.commit()
            updated_id = row.id

        fetched = self.get_book(updated_id)
        if fetched is None:  # pragma: no cover - just-updated row must exist
            msg = "Failed to read back the updated book"
            raise RuntimeError(msg)
        return fetched

    def delete_book(self, book_id: int) -> None:
        """Delete a book. Calibre's ``books_delete_trg`` cascades to the
        link/data/comment tables, so we delete the books row directly with a
        Core statement rather than letting the ORM manage child rows (which would
        fight the trigger). A missing book is a no-op.
        """
        with Session(self._engine) as session:
            if session.get(cs.Book, book_id) is None:
                return
            session.execute(text("DELETE FROM books WHERE id = :id"), {"id": book_id})
            session.commit()

    def book_dir(self, book_id: int) -> str | None:
        """Return the library-relative directory of a book (``books.path``)."""
        with Session(self._engine) as session:
            row = session.get(cs.Book, book_id)
            return row.path if row is not None else None

    def add_format(self, book_id: int, extension: str, size_bytes: int, name: str) -> None:
        """Insert (or replace) a ``data`` row for a new format of the book."""
        fmt = extension.upper()
        with Session(self._engine) as session:
            existing = session.scalars(
                select(cs.Data).where(cs.Data.book == book_id, cs.Data.format == fmt)
            ).first()
            if existing is not None:
                existing.uncompressed_size = size_bytes
                existing.name = name
            else:
                session.add(
                    cs.Data(book=book_id, format=fmt, uncompressed_size=size_bytes, name=name)
                )
            session.commit()

    def remove_format(self, book_id: int, book_format: str) -> None:
        """Delete a book's ``data`` row for *book_format* (case-insensitive).

        A format the book does not have is a no-op.
        """
        fmt = book_format.upper()
        with Session(self._engine) as session:
            row = session.scalars(
                select(cs.Data).where(cs.Data.book == book_id, func.upper(cs.Data.format) == fmt)
            ).first()
            if row is not None:
                session.delete(row)
                session.commit()

    # --- entity upserts (case-insensitive, reuse existing) ------------------

    def _resolve_author_sorts(self, authors: Sequence[dm.Author]) -> list[dm.Author]:
        return [
            a if a.sort else dm.Author(name=a.name, sort=author_sort(a.name), link=a.link)
            for a in authors
        ]

    def _sync_comment(self, session: Session, book_id: int, text: str | None) -> None:
        existing = session.scalars(select(cs.Comment).where(cs.Comment.book == book_id)).first()
        if text:
            if existing is not None:
                existing.text = text
            else:
                session.add(cs.Comment(book=book_id, text=text))
        elif existing is not None:
            session.delete(existing)

    def _sync_identifiers(
        self, session: Session, book_id: int, identifiers: Sequence[dm.Identifier]
    ) -> None:
        for old in session.scalars(
            select(cs.Identifier).where(cs.Identifier.book == book_id)
        ).all():
            session.delete(old)
        for ident in identifiers:
            session.add(cs.Identifier(book=book_id, type=ident.scheme.lower(), val=ident.value))

    # link table -> column referencing the entity. A fixed allowlist: the only
    # values ever passed to _prune_orphans, so the SQL built from them is not
    # user-influenced (guards against accidental injection via this helper).
    _LINK_TABLES: ClassVar[dict[str, str]] = {
        "books_authors_link": "author",
        "books_tags_link": "tag",
        "books_series_link": "series",
        "books_publishers_link": "publisher",
        "books_ratings_link": "rating",
    }

    def _prune_orphans[E](
        self,
        session: Session,
        link_table: str,
        candidates: Sequence[E],
    ) -> None:
        """Delete each candidate entity no longer linked to any book.

        *link_table* must be one of the known link tables; the query is built
        only from that vetted constant, never from user input.
        """
        column = self._LINK_TABLES[link_table]
        query = text(f"SELECT 1 FROM {link_table} WHERE {column} = :id LIMIT 1")  # noqa: S608 - table/column from vetted allowlist
        for entity in candidates:
            entity_id = entity.id  # type: ignore[attr-defined]  # all entities have an int id
            still_used = session.execute(query, {"id": entity_id}).first()
            if still_used is None:
                session.delete(entity)

    def _upsert_author(self, session: Session, author: dm.Author) -> cs.Author:
        existing = session.scalars(
            select(cs.Author).where(func.lower(cs.Author.name) == author.name.lower())
        ).first()
        if existing is not None:
            return existing
        created = cs.Author(name=author.name, sort=author.sort or author_sort(author.name))
        session.add(created)
        return created

    def _upsert_tag(self, session: Session, name: str) -> cs.Tag:
        existing = session.scalars(
            select(cs.Tag).where(func.lower(cs.Tag.name) == name.lower())
        ).first()
        if existing is not None:
            return existing
        created = cs.Tag(name=name)
        session.add(created)
        return created

    def _upsert_series(self, session: Session, series: dm.Series) -> cs.Series:
        existing = session.scalars(
            select(cs.Series).where(func.lower(cs.Series.name) == series.name.lower())
        ).first()
        if existing is not None:
            return existing
        created = cs.Series(name=series.name, sort=series.sort or title_sort(series.name))
        session.add(created)
        return created

    def _upsert_language(self, session: Session, code: str) -> cs.Language:
        existing = session.scalars(
            select(cs.Language).where(func.lower(cs.Language.lang_code) == code.lower())
        ).first()
        if existing is not None:
            return existing
        created = cs.Language(lang_code=code)
        session.add(created)
        return created

    def _upsert_publisher(self, session: Session, name: str) -> cs.Publisher:
        existing = session.scalars(
            select(cs.Publisher).where(func.lower(cs.Publisher.name) == name.lower())
        ).first()
        if existing is not None:
            return existing
        created = cs.Publisher(name=name, sort=name)
        session.add(created)
        return created

    def _upsert_rating(self, session: Session, rating: int) -> cs.Rating:
        existing = session.scalars(select(cs.Rating).where(cs.Rating.rating == rating)).first()
        if existing is not None:
            return existing
        created = cs.Rating(rating=rating)
        session.add(created)
        return created
