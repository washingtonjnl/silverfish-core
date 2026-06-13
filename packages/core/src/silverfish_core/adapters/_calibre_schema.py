"""SQLAlchemy models for the Calibre ``metadata.db`` schema.

These map the real on-disk Calibre schema (verified against a database produced
by Calibre itself). Only the columns the repository needs are declared; Calibre
has extra columns (``isbn``, ``lccn``, ``flags``, per-entity ``link``) and tables
(FTS, ``tag_browser_*``) that we deliberately do not map. ``extend_existing`` is
not needed because we never create these tables — we only read an existing DB.
"""

from sqlalchemy import Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --- association tables -----------------------------------------------------

books_authors_link = Table(
    "books_authors_link",
    Base.metadata,
    Column("book", Integer, ForeignKey("books.id"), primary_key=True),
    Column("author", Integer, ForeignKey("authors.id"), primary_key=True),
)

books_tags_link = Table(
    "books_tags_link",
    Base.metadata,
    Column("book", Integer, ForeignKey("books.id"), primary_key=True),
    Column("tag", Integer, ForeignKey("tags.id"), primary_key=True),
)

books_series_link = Table(
    "books_series_link",
    Base.metadata,
    Column("book", Integer, ForeignKey("books.id"), primary_key=True),
    Column("series", Integer, ForeignKey("series.id"), primary_key=True),
)

books_ratings_link = Table(
    "books_ratings_link",
    Base.metadata,
    Column("book", Integer, ForeignKey("books.id"), primary_key=True),
    Column("rating", Integer, ForeignKey("ratings.id"), primary_key=True),
)

books_languages_link = Table(
    "books_languages_link",
    Base.metadata,
    Column("book", Integer, ForeignKey("books.id"), primary_key=True),
    Column("lang_code", Integer, ForeignKey("languages.id"), primary_key=True),
)

books_publishers_link = Table(
    "books_publishers_link",
    Base.metadata,
    Column("book", Integer, ForeignKey("books.id"), primary_key=True),
    Column("publisher", Integer, ForeignKey("publishers.id"), primary_key=True),
)


# --- entities ---------------------------------------------------------------


class Author(Base):
    __tablename__ = "authors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    sort: Mapped[str | None] = mapped_column(String)


class Series(Base):
    __tablename__ = "series"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    sort: Mapped[str | None] = mapped_column(String)


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)


class Rating(Base):
    __tablename__ = "ratings"
    id: Mapped[int] = mapped_column(primary_key=True)
    rating: Mapped[int] = mapped_column(Integer)


class Publisher(Base):
    __tablename__ = "publishers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    sort: Mapped[str | None] = mapped_column(String)


class Language(Base):
    __tablename__ = "languages"
    id: Mapped[int] = mapped_column(primary_key=True)
    lang_code: Mapped[str] = mapped_column(String)


class Data(Base):
    __tablename__ = "data"
    id: Mapped[int] = mapped_column(primary_key=True)
    book: Mapped[int] = mapped_column(ForeignKey("books.id"))
    format: Mapped[str] = mapped_column(String)
    uncompressed_size: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String)


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    book: Mapped[int] = mapped_column(ForeignKey("books.id"))
    text: Mapped[str] = mapped_column(String)


class Identifier(Base):
    __tablename__ = "identifiers"
    id: Mapped[int] = mapped_column(primary_key=True)
    book: Mapped[int] = mapped_column(ForeignKey("books.id"))
    type: Mapped[str] = mapped_column(String)
    val: Mapped[str] = mapped_column(String)


class Book(Base):
    __tablename__ = "books"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String)
    sort: Mapped[str | None] = mapped_column(String)
    author_sort: Mapped[str | None] = mapped_column(String)
    series_index: Mapped[float] = mapped_column()
    path: Mapped[str] = mapped_column(String)
    has_cover: Mapped[bool | None] = mapped_column()
    uuid: Mapped[str | None] = mapped_column(String)

    authors: Mapped[list[Author]] = relationship(secondary=books_authors_link)
    tags: Mapped[list[Tag]] = relationship(secondary=books_tags_link)
    series: Mapped[list[Series]] = relationship(secondary=books_series_link)
    ratings: Mapped[list[Rating]] = relationship(secondary=books_ratings_link)
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
