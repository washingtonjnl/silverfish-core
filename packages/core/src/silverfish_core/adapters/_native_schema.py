"""SQLAlchemy models for the native Silverfish book schema.

Unlike ``_calibre_schema`` (which maps a metadata.db we only ever read), this is
the schema the core CREATES and OWNS in standalone mode. It is therefore free of
Calibre quirks: ratings are a plain 0-10 integer (no on-disk x2), ids are 64-bit
Snowflake integers (``BigInteger``), and the neutral domain's pubdate/timestamp/
last_modified are first-class columns.

Crucially it has its own ``DeclarativeBase`` (``NativeBase``), separate from the
Calibre ``Base`` and from the system schema's base. That isolation is what
guarantees we never create our tables into a Calibre library — ``create_all`` on
``NativeBase.metadata`` only ever touches our own tables.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Integer, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class NativeBase(DeclarativeBase):
    pass


# --- association tables -----------------------------------------------------

books_authors_link = Table(
    "books_authors_link",
    NativeBase.metadata,
    Column("book", BigInteger, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
    Column("author", Integer, ForeignKey("authors.id"), primary_key=True),
)

books_tags_link = Table(
    "books_tags_link",
    NativeBase.metadata,
    Column("book", BigInteger, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
    Column("tag", Integer, ForeignKey("tags.id"), primary_key=True),
)

books_series_link = Table(
    "books_series_link",
    NativeBase.metadata,
    Column("book", BigInteger, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
    Column("series", Integer, ForeignKey("series.id"), primary_key=True),
)

books_languages_link = Table(
    "books_languages_link",
    NativeBase.metadata,
    Column("book", BigInteger, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
    Column("lang_code", Integer, ForeignKey("languages.id"), primary_key=True),
)

books_publishers_link = Table(
    "books_publishers_link",
    NativeBase.metadata,
    Column("book", BigInteger, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
    Column("publisher", Integer, ForeignKey("publishers.id"), primary_key=True),
)


# --- entities ---------------------------------------------------------------


class Author(NativeBase):
    __tablename__ = "authors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    sort: Mapped[str | None] = mapped_column(String)
    link: Mapped[str] = mapped_column(String, default="")


class Series(NativeBase):
    __tablename__ = "series"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    sort: Mapped[str | None] = mapped_column(String)


class Tag(NativeBase):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)


class Publisher(NativeBase):
    __tablename__ = "publishers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    sort: Mapped[str | None] = mapped_column(String)


class Language(NativeBase):
    __tablename__ = "languages"
    id: Mapped[int] = mapped_column(primary_key=True)
    lang_code: Mapped[str] = mapped_column(String, unique=True)


# Rating is a plain 0-10 integer stored inline on the book (no Calibre x2, no
# separate ratings entity table — the join-table indirection Calibre uses buys
# us nothing in our own schema).


class Data(NativeBase):
    __tablename__ = "data"
    id: Mapped[int] = mapped_column(primary_key=True)
    book: Mapped[int] = mapped_column(BigInteger, ForeignKey("books.id", ondelete="CASCADE"))
    format: Mapped[str] = mapped_column(String)
    uncompressed_size: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String)


class Comment(NativeBase):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    book: Mapped[int] = mapped_column(BigInteger, ForeignKey("books.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String)


class Identifier(NativeBase):
    __tablename__ = "identifiers"
    id: Mapped[int] = mapped_column(primary_key=True)
    book: Mapped[int] = mapped_column(BigInteger, ForeignKey("books.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String)
    val: Mapped[str] = mapped_column(String)


class Book(NativeBase):
    __tablename__ = "books"
    # 64-bit Snowflake id, assigned by the application (not autoincremented).
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String)
    sort: Mapped[str | None] = mapped_column(String)
    author_sort: Mapped[str | None] = mapped_column(String)
    series_index: Mapped[float] = mapped_column(Float, default=1.0)
    path: Mapped[str] = mapped_column(String, default="")
    has_cover: Mapped[bool] = mapped_column(default=False)
    rating: Mapped[int | None] = mapped_column(Integer)
    uuid: Mapped[str | None] = mapped_column(String)
    pubdate: Mapped[datetime | None] = mapped_column(DateTime)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    last_modified: Mapped[datetime | None] = mapped_column(DateTime)

    authors: Mapped[list[Author]] = relationship(secondary=books_authors_link)
    tags: Mapped[list[Tag]] = relationship(secondary=books_tags_link)
    series: Mapped[list[Series]] = relationship(secondary=books_series_link)
    languages: Mapped[list[Language]] = relationship(secondary=books_languages_link)
    publishers: Mapped[list[Publisher]] = relationship(secondary=books_publishers_link)
    data: Mapped[list[Data]] = relationship(
        primaryjoin="Book.id == Data.book", foreign_keys="Data.book"
    )
    comments: Mapped[list[Comment]] = relationship(
        primaryjoin="Book.id == Comment.book", foreign_keys="Comment.book"
    )
    identifiers: Mapped[list[Identifier]] = relationship(
        primaryjoin="Book.id == Identifier.book", foreign_keys="Identifier.book"
    )
