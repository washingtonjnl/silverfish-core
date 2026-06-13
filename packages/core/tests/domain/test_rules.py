"""Tests for the Calibre-dialect domain rules.

Written before the implementation (TDD). The expected behaviour mirrors how
Calibre/Calibre-Web compute sort keys, sanitise filenames and lay out paths, so
that a library produced by Silverfish is indistinguishable from one produced by
Calibre. Reference behaviour:

- title sort  -> calibre-web cps/db.py:1144 (`_title_sort`) with the default
  article regex from cps/config_sql.py:86.
- author sort -> calibre-web cps/helper.py:279 (`get_sorted_author`).
- filename    -> calibre-web cps/helper.py:240 (`get_valid_filename`).
"""

import pytest

from silverfish_core.domain.rules import (
    author_sort,
    build_path,
    title_sort,
    valid_filename,
)


class TestTitleSort:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("The Lord of the Rings", "Lord of the Rings, The"),
            ("A Game of Thrones", "Game of Thrones, A"),
            ("An Inconvenient Truth", "Inconvenient Truth, An"),
            # German articles are part of the default Calibre regex.
            ("Der Steppenwolf", "Steppenwolf, Der"),
            ("Die Verwandlung", "Verwandlung, Die"),
            # French elision: "L'" is followed by no whitespace.
            ("L'Étranger", "Étranger, L'"),
            # No leading article -> unchanged.
            ("Dune", "Dune"),
            ("1984", "1984"),
            # A word that merely starts with an article is not stripped.
            ("Theory of Everything", "Theory of Everything"),
            ("Andromeda", "Andromeda"),
            # Case-insensitive match, but the original prefix casing is kept.
            ("the hobbit", "hobbit, the"),
        ],
    )
    def test_moves_leading_article_to_the_end(self, title: str, expected: str) -> None:
        assert title_sort(title) == expected

    def test_leading_whitespace_prevents_article_match(self) -> None:
        # Calibre runs the ^-anchored regex on the raw title; leading spaces mean
        # the article is not recognised. We match that behaviour and only trim
        # the final result.
        assert title_sort("  The Stand") == "The Stand"

    def test_trailing_whitespace_is_not_collapsed_internally(self) -> None:
        # Faithful to Calibre: only leading/trailing whitespace of the *result*
        # is stripped, never collapsed. With a trailing space the article move
        # leaves the space before the comma — exactly as Calibre produces it.
        assert title_sort("The Stand ") == "Stand , The"

    def test_empty_title_returns_empty(self) -> None:
        assert title_sort("") == ""


class TestAuthorSort:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("John F. Kennedy", "Kennedy, John F."),
            ("George Orwell", "Orwell, George"),
            # Single token -> unchanged.
            ("Plato", "Plato"),
            ("Voltaire", "Voltaire"),
            # Suffixes Jr/Sr/roman numerals are kept attached at the end.
            ("Martin Luther King Jr.", "King, Martin Luther Jr."),
            ("John D. Rockefeller Sr.", "Rockefeller, John D. Sr."),
            ("Henry Ford II", "Ford, Henry II"),
            # Already in "Last, First" form -> returned as-is.
            ("Kennedy, John F.", "Kennedy, John F."),
        ],
    )
    def test_formats_as_last_comma_first(self, name: str, expected: str) -> None:
        assert author_sort(name) == expected


class TestValidFilename:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Normal Title", "Normal Title"),
            # Forbidden FS characters become underscores.
            ("a/b", "a_b"),
            ("a:b", "a_b"),
            ('quote"here', "quote_here"),
            ("a<b>c?d*e", "a_b_c_d_e"),
            # Pipe becomes a comma (Calibre quirk).
            ("a|b", "a,b"),
            # A trailing dot is replaced (FS-unsafe on Windows).
            ("name.", "name_"),
        ],
    )
    def test_sanitises_forbidden_characters(self, value: str, expected: str) -> None:
        assert valid_filename(value) == expected

    def test_truncates_to_byte_budget_not_char_count(self) -> None:
        # Each "é" is two UTF-8 bytes; a 4-byte budget keeps only two of them
        # and must not split a multibyte character.
        assert valid_filename("ééé", chars=4) == "éé"

    def test_unidecode_transliterates_when_requested(self) -> None:
        assert valid_filename("José", force_unidecode=True) == "Jose"

    def test_unidecode_off_by_default_keeps_unicode(self) -> None:
        assert valid_filename("José") == "José"

    def test_empty_result_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            valid_filename("")


class TestBuildPath:
    def test_combines_sanitised_author_and_title(self) -> None:
        assert build_path("J. R. R. Tolkien", "The Hobbit") == "J. R. R. Tolkien/The Hobbit"

    def test_appends_id_suffix_when_given(self) -> None:
        # Calibre appends " (id)" to the title directory.
        assert build_path("George Orwell", "1984", book_id=42) == "George Orwell/1984 (42)"

    def test_sanitises_each_component(self) -> None:
        assert build_path("A/B", "C:D") == "A_B/C_D"

    def test_uses_forward_slash_separator(self) -> None:
        # Path stored in the DB always uses "/" regardless of OS.
        assert "/" in build_path("Author", "Title")
        assert "\\" not in build_path("Author", "Title")
