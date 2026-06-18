"""Native SQL implementation of the ``MetadataRepository`` port.

The standalone-mode repository: it owns its schema (``_native_schema``), creates
it on construction, and is agnostic of the backing engine — SQLite for local use
or Postgres for a robust deployment. Unlike the Calibre repository, nothing here
relies on SQLite triggers or registered SQL functions: sort keys, uuid and path
are computed in Python with the shared domain rules, and the 64-bit book id is
minted by an injected ``SnowflakeGenerator``. The result is a portable,
time-ordered library the core fully controls.
"""

import uuid as uuid_module
from collections.abc import Sequence

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Select

from silverfish_core.adapters import _native_schema as ns
from silverfish_core.domain import models as dm
from silverfish_core.domain.rules import author_sort, build_path, title_sort
from silverfish_core.ids import SnowflakeGenerator
from silverfish_core.ports.types import (
    Page,
    SearchFilters,
    SortDirection,
    SortField,
    SortOrder,
)

_SORT_COLUMNS = {
    SortField.TITLE: ns.Book.sort,
    SortField.PUBDATE: ns.Book.pubdate,
    SortField.TIMESTAMP: ns.Book.timestamp,
    SortField.LAST_MODIFIED: ns.Book.last_modified,
    SortField.SERIES: ns.Book.series_index,
    SortField.AUTHOR: ns.Book.author_sort,
    SortField.RATING: ns.Book.rating,
}


class SqlNativeRepository:
    """Persist book metadata in Silverfish's own schema (SQLite or Postgres)."""

    def __init__(self, *, conn_string: str, id_generator: SnowflakeGenerator) -> None:
        self._engine = create_engine(conn_string)
        self._ids = id_generator
        ns.NativeBase.metadata.create_all(self._engine)

    def close(self) -> None:
        self._engine.dispose()

    # --- mapping ------------------------------------------------------------

    def _to_domain(self, row: ns.Book) -> dm.Book:
        series = (
            dm.Series(name=row.series[0].name, sort=row.series[0].sort or row.series[0].name)
            if row.series
            else None
        )
        return dm.Book(
            id=row.id,
            title=row.title,
            sort=row.sort or row.title,
            author_sort=row.author_sort or "",
            authors=tuple(
                dm.Author(name=a.name, sort=a.sort or a.name, link=a.link) for a in row.authors
            ),
            tags=tuple(dm.Tag(name=t.name) for t in row.tags),
            series=series,
            series_index=row.series_index,
            rating=row.rating,
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
            pubdate=row.pubdate,
            timestamp=row.timestamp,
            last_modified=row.last_modified,
        )

    def _eager(self, stmt: Select[tuple[ns.Book]]) -> Select[tuple[ns.Book]]:
        return stmt.options(
            selectinload(ns.Book.authors),
            selectinload(ns.Book.tags),
            selectinload(ns.Book.series),
            selectinload(ns.Book.languages),
            selectinload(ns.Book.publishers),
            selectinload(ns.Book.data),
            selectinload(ns.Book.comments),
            selectinload(ns.Book.identifiers),
        )

    # --- reads --------------------------------------------------------------

    def get_book(self, book_id: int) -> dm.Book | None:
        with Session(self._engine) as session:
            stmt = self._eager(select(ns.Book).where(ns.Book.id == book_id))
            row = session.scalars(stmt).one_or_none()
            return self._to_domain(row) if row is not None else None

    def list_books(self, *, page: int, page_size: int, sort: SortOrder) -> Page[dm.Book]:
        with Session(self._engine) as session:
            total = session.scalar(select(func.count()).select_from(ns.Book)) or 0
            column = _SORT_COLUMNS[sort.field]
            ordering = column.desc() if sort.direction is SortDirection.DESC else column.asc()
            stmt = (
                self._eager(select(ns.Book))
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
            stmt = self._eager(select(ns.Book))
            stmt = self._apply_term(stmt, term)
            stmt = self._apply_filters(stmt, filters)

            count_stmt = self._apply_filters(self._apply_term(select(ns.Book.id), term), filters)
            total = session.scalar(select(func.count()).select_from(count_stmt.subquery())) or 0

            stmt = stmt.order_by(ns.Book.sort.asc()).offset((page - 1) * page_size).limit(page_size)
            rows = session.scalars(stmt).all()
            return self._page(rows, total, page, page_size)

    # --- file locations (storage-relative; never exposed via the API) -------

    def cover_path(self, book_id: int) -> str | None:
        with Session(self._engine) as session:
            row = session.get(ns.Book, book_id)
            if row is None or not row.has_cover:
                return None
            return f"{row.path}/cover.jpg"

    def format_path(self, book_id: int, book_format: str) -> str | None:
        with Session(self._engine) as session:
            row = session.get(ns.Book, book_id)
            if row is None:
                return None
            wanted = book_format.upper()
            for data in row.data:
                if data.format.upper() == wanted:
                    return f"{row.path}/{data.name}.{data.format.lower()}"
            return None

    def book_dir(self, book_id: int) -> str | None:
        with Session(self._engine) as session:
            row = session.get(ns.Book, book_id)
            return row.path if row is not None else None

    # --- query helpers ------------------------------------------------------

    def _apply_term[R](self, stmt: Select[tuple[R]], term: str) -> Select[tuple[R]]:
        term = term.strip()
        if not term:
            return stmt
        like = f"%{term.lower()}%"
        title_match = func.lower(ns.Book.title).like(like)
        author_match = ns.Book.authors.any(func.lower(ns.Author.name).like(like))
        series_match = ns.Book.series.any(func.lower(ns.Series.name).like(like))
        tag_match = ns.Book.tags.any(func.lower(ns.Tag.name).like(like))
        return stmt.where(title_match | author_match | series_match | tag_match)

    def _apply_filters[R](self, stmt: Select[tuple[R]], filters: SearchFilters) -> Select[tuple[R]]:
        for tag in filters.include_tags:
            stmt = stmt.where(ns.Book.tags.any(func.lower(ns.Tag.name) == tag.lower()))
        for tag in filters.exclude_tags:
            stmt = stmt.where(~ns.Book.tags.any(func.lower(ns.Tag.name) == tag.lower()))
        for name in filters.include_series:
            stmt = stmt.where(ns.Book.series.any(func.lower(ns.Series.name) == name.lower()))
        for name in filters.exclude_series:
            stmt = stmt.where(~ns.Book.series.any(func.lower(ns.Series.name) == name.lower()))
        if filters.languages:
            wanted = {lang.lower() for lang in filters.languages}
            stmt = stmt.where(ns.Book.languages.any(func.lower(ns.Language.lang_code).in_(wanted)))
        if filters.formats:
            fmts = {fmt.lower() for fmt in filters.formats}
            stmt = stmt.where(ns.Book.data.any(func.lower(ns.Data.format).in_(fmts)))
        if filters.publisher:
            stmt = stmt.where(
                ns.Book.publishers.any(func.lower(ns.Publisher.name) == filters.publisher.lower())
            )
        if filters.rating_min is not None:
            stmt = stmt.where(ns.Book.rating >= filters.rating_min)
        if filters.rating_max is not None:
            stmt = stmt.where(ns.Book.rating <= filters.rating_max)
        return stmt

    def _page(
        self, rows: Sequence[ns.Book], total: int, page: int, page_size: int
    ) -> Page[dm.Book]:
        return Page(
            items=tuple(self._to_domain(r) for r in rows),
            total=total,
            page=page,
            page_size=page_size,
        )

    # --- writes -------------------------------------------------------------

    def create_book(self, book: dm.Book) -> dm.Book:
        sort = book.sort or title_sort(book.title)
        resolved_authors = self._resolve_author_sorts(book.authors)
        book_author_sort = book.author_sort or " & ".join(a.sort for a in resolved_authors)
        new_id = self._ids.next_id()

        with Session(self._engine) as session:
            row = ns.Book(
                id=new_id,
                title=book.title,
                sort=sort,
                author_sort=book_author_sort,
                series_index=book.series_index,
                path=build_path(
                    resolved_authors[0].name if resolved_authors else "Unknown",
                    book.title,
                    book_id=new_id,
                ),
                has_cover=book.has_cover,
                rating=book.rating,
                uuid=book.uuid or str(uuid_module.uuid4()),
                pubdate=book.pubdate,
                timestamp=book.timestamp,
                last_modified=book.last_modified,
            )
            row.authors = [self._upsert_author(session, a) for a in resolved_authors]
            row.tags = [self._upsert_tag(session, t.name) for t in book.tags]
            if book.series is not None:
                row.series = [self._upsert_series(session, book.series)]
            row.languages = [self._upsert_language(session, code) for code in book.languages]
            if book.publisher:
                row.publishers = [self._upsert_publisher(session, book.publisher)]
            session.add(row)
            session.flush()

            for fmt in book.formats:
                session.add(
                    ns.Data(
                        book=new_id,
                        format=fmt.extension.upper(),
                        uncompressed_size=fmt.size_bytes,
                        name=fmt.name,
                    )
                )
            if book.comment:
                session.add(ns.Comment(book=new_id, text=book.comment))
            for ident in book.identifiers:
                session.add(ns.Identifier(book=new_id, type=ident.scheme.lower(), val=ident.value))

            session.commit()

        fetched = self.get_book(new_id)
        if fetched is None:  # pragma: no cover - just-created row must exist
            msg = "Failed to read back the created book"
            raise RuntimeError(msg)
        return fetched

    def update_book(self, book: dm.Book) -> dm.Book:
        if book.id is None:
            msg = "update_book requires a book with an id"
            raise ValueError(msg)

        resolved_authors = self._resolve_author_sorts(book.authors)
        new_author_sort = book.author_sort or " & ".join(a.sort for a in resolved_authors)

        with Session(self._engine) as session:
            row = session.get(ns.Book, book.id)
            if row is None:
                msg = f"Book {book.id} does not exist"
                raise ValueError(msg)

            row.title = book.title
            row.sort = title_sort(book.title)
            row.author_sort = new_author_sort
            row.series_index = book.series_index
            row.has_cover = book.has_cover
            row.rating = book.rating
            row.pubdate = book.pubdate
            row.last_modified = book.last_modified
            row.path = build_path(
                resolved_authors[0].name if resolved_authors else "Unknown",
                book.title,
                book_id=row.id,
            )

            old_authors = list(row.authors)
            old_tags = list(row.tags)
            old_series = list(row.series)
            old_publishers = list(row.publishers)

            row.authors = [self._upsert_author(session, a) for a in resolved_authors]
            row.tags = [self._upsert_tag(session, t.name) for t in book.tags]
            row.series = (
                [self._upsert_series(session, book.series)] if book.series is not None else []
            )
            row.languages = [self._upsert_language(session, code) for code in book.languages]
            row.publishers = (
                [self._upsert_publisher(session, book.publisher)] if book.publisher else []
            )

            self._sync_comment(session, row.id, book.comment)
            self._sync_identifiers(session, row.id, book.identifiers)

            session.flush()
            self._prune_orphans(session, ns.books_authors_link.c.author, ns.Author, old_authors)
            self._prune_orphans(session, ns.books_tags_link.c.tag, ns.Tag, old_tags)
            self._prune_orphans(session, ns.books_series_link.c.series, ns.Series, old_series)
            self._prune_orphans(
                session, ns.books_publishers_link.c.publisher, ns.Publisher, old_publishers
            )

            session.commit()
            updated_id = row.id

        fetched = self.get_book(updated_id)
        if fetched is None:  # pragma: no cover - just-updated row must exist
            msg = "Failed to read back the updated book"
            raise RuntimeError(msg)
        return fetched

    def delete_book(self, book_id: int) -> None:
        with Session(self._engine) as session:
            row = session.get(ns.Book, book_id)
            if row is None:
                return
            # Child rows (data/comments/identifiers/links) are removed explicitly
            # so behaviour is identical on SQLite and Postgres regardless of how
            # the dialect honours ON DELETE CASCADE.
            session.execute(text("DELETE FROM data WHERE book = :id"), {"id": book_id})
            session.execute(text("DELETE FROM comments WHERE book = :id"), {"id": book_id})
            session.execute(text("DELETE FROM identifiers WHERE book = :id"), {"id": book_id})
            row.authors = []
            row.tags = []
            row.series = []
            row.languages = []
            row.publishers = []
            session.flush()
            session.delete(row)
            session.commit()

    def add_format(self, book_id: int, extension: str, size_bytes: int, name: str) -> None:
        fmt = extension.upper()
        with Session(self._engine) as session:
            existing = session.scalars(
                select(ns.Data).where(ns.Data.book == book_id, ns.Data.format == fmt)
            ).first()
            if existing is not None:
                existing.uncompressed_size = size_bytes
                existing.name = name
            else:
                session.add(
                    ns.Data(book=book_id, format=fmt, uncompressed_size=size_bytes, name=name)
                )
            session.commit()

    def remove_format(self, book_id: int, book_format: str) -> None:
        fmt = book_format.upper()
        with Session(self._engine) as session:
            row = session.scalars(
                select(ns.Data).where(ns.Data.book == book_id, func.upper(ns.Data.format) == fmt)
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

    def _sync_comment(self, session: Session, book_id: int, comment: str | None) -> None:
        existing = session.scalars(select(ns.Comment).where(ns.Comment.book == book_id)).first()
        if comment:
            if existing is not None:
                existing.text = comment
            else:
                session.add(ns.Comment(book=book_id, text=comment))
        elif existing is not None:
            session.delete(existing)

    def _sync_identifiers(
        self, session: Session, book_id: int, identifiers: Sequence[dm.Identifier]
    ) -> None:
        for old in session.scalars(
            select(ns.Identifier).where(ns.Identifier.book == book_id)
        ).all():
            session.delete(old)
        for ident in identifiers:
            session.add(ns.Identifier(book=book_id, type=ident.scheme.lower(), val=ident.value))

    def _prune_orphans[E](
        self,
        session: Session,
        link_column: "ColumnElement[int]",
        entity_type: type[E],
        candidates: Sequence[E],
    ) -> None:
        """Delete each candidate entity no longer linked to any book.

        The link column is a vetted SQLAlchemy column object (never user input),
        so the lookup is expressed through the ORM rather than raw SQL.
        """
        for entity in candidates:
            entity_id = entity.id  # type: ignore[attr-defined]  # all entities have an int id
            still_used = session.scalar(select(func.count()).where(link_column == entity_id))
            if not still_used:
                merged = session.get(entity_type, entity_id)
                if merged is not None:
                    session.delete(merged)

    def _upsert_author(self, session: Session, author: dm.Author) -> ns.Author:
        existing = session.scalars(
            select(ns.Author).where(func.lower(ns.Author.name) == author.name.lower())
        ).first()
        if existing is not None:
            return existing
        created = ns.Author(
            name=author.name, sort=author.sort or author_sort(author.name), link=author.link
        )
        session.add(created)
        return created

    def _upsert_tag(self, session: Session, name: str) -> ns.Tag:
        existing = session.scalars(
            select(ns.Tag).where(func.lower(ns.Tag.name) == name.lower())
        ).first()
        if existing is not None:
            return existing
        created = ns.Tag(name=name)
        session.add(created)
        return created

    def _upsert_series(self, session: Session, series: dm.Series) -> ns.Series:
        existing = session.scalars(
            select(ns.Series).where(func.lower(ns.Series.name) == series.name.lower())
        ).first()
        if existing is not None:
            return existing
        created = ns.Series(name=series.name, sort=series.sort or title_sort(series.name))
        session.add(created)
        return created

    def _upsert_language(self, session: Session, code: str) -> ns.Language:
        existing = session.scalars(
            select(ns.Language).where(func.lower(ns.Language.lang_code) == code.lower())
        ).first()
        if existing is not None:
            return existing
        created = ns.Language(lang_code=code)
        session.add(created)
        return created

    def _upsert_publisher(self, session: Session, name: str) -> ns.Publisher:
        existing = session.scalars(
            select(ns.Publisher).where(func.lower(ns.Publisher.name) == name.lower())
        ).first()
        if existing is not None:
            return existing
        created = ns.Publisher(name=name, sort=name)
        session.add(created)
        return created
