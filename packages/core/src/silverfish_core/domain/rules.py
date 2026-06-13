"""Pure Calibre-dialect rules: sort keys, filename sanitisation and path layout.

These functions are deterministic and side-effect free. They replicate how
Calibre/Calibre-Web derive ``sort``/``author_sort``, sanitise names for the
filesystem and lay out the ``Author/Title (id)`` directory structure, so that a
library written by Silverfish is indistinguishable from one written by Calibre.
"""

import re

from unidecode import unidecode

# Leading-article regex used by Calibre's title-sort. Articles in EN/DE/FR are
# moved to the end of the title ("The Hobbit" -> "Hobbit, The"). Mirrors the
# default `config_title_regex` in calibre-web cps/config_sql.py:86.
DEFAULT_TITLE_ARTICLE_PATTERN = (
    r"^(A|The|An|Der|Die|Das|Den|Ein|Eine|Einen|Dem|Des|Einem|Eines"
    r"|Le|La|Les|L'|Un|Une)(\s+|(?<='))"
)

_TITLE_ARTICLE_RE = re.compile(DEFAULT_TITLE_ARTICLE_PATTERN, re.IGNORECASE)

# Author-name suffixes that must stay attached at the end of the sorted name
# (e.g. "Martin Luther King Jr." -> "King, Martin Luther Jr.").
_AUTHOR_SUFFIX_RE = re.compile(r"^(JR|SR)\.?$|^I{1,3}\.?$|^IV\.?$", re.IGNORECASE)

# Characters that are unsafe in filesystem names; collapsed runs become a single
# underscore. The pipe is handled separately (Calibre turns it into a comma).
_FORBIDDEN_FS_CHARS_RE = re.compile(r'[*+:\\"/<>?]+')
_PIPE_RE = re.compile(r"[|]+")


def title_sort(title: str, *, article_pattern: re.Pattern[str] | None = None) -> str:
    """Return the Calibre sort key for *title*.

    A leading article is moved to the end: ``"The Stand" -> "Stand, The"``. The
    original casing of the article is preserved even though the match is
    case-insensitive. Titles without a leading article are returned trimmed but
    otherwise unchanged.
    """
    pattern = article_pattern if article_pattern is not None else _TITLE_ARTICLE_RE
    match = pattern.search(title)
    if match:
        prefix = match.group(1)
        title = f"{title[len(prefix) :]}, {prefix}"
    return title.strip()


def author_sort(name: str) -> str:
    """Return the Calibre ``author_sort`` for *name*.

    ``"John F. Kennedy" -> "Kennedy, John F."``. A trailing suffix (Jr/Sr or a
    roman numeral) is kept attached. A name already containing a comma is assumed
    to be in ``"Last, First"`` form and returned unchanged. A single token is
    returned unchanged.
    """
    if "," in name:
        return name

    parts = name.split(" ")
    if _AUTHOR_SUFFIX_RE.match(parts[-1]):
        if len(parts) > 1:
            return f"{parts[-2]}, {' '.join(parts[:-2])} {parts[-1]}".replace("  ", " ")
        return parts[0]
    if len(parts) == 1:
        return parts[0]
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def valid_filename(
    value: str,
    *,
    chars: int = 128,
    force_unidecode: bool = False,
) -> str:
    """Sanitise *value* into a name usable as a single filesystem path segment.

    Mirrors Calibre's rules: a trailing dot becomes ``_``; ``/`` and ``:`` and a
    set of forbidden characters become ``_``; the pipe becomes a comma; the
    result is truncated to *chars* **bytes** (UTF-8), never splitting a multibyte
    character. Transliteration to ASCII happens only when *force_unidecode* is
    set. Raises ``ValueError`` if the result is empty.
    """
    if value.endswith("."):
        value = value[:-1] + "_"
    value = value.replace("/", "_").replace(":", "_").strip("\0")

    if force_unidecode:
        value = unidecode(value)

    value = _FORBIDDEN_FS_CHARS_RE.sub("_", value)
    value = _PIPE_RE.sub(",", value)

    # Truncate by UTF-8 byte budget, dropping a trailing partial character.
    value = value.encode("utf-8")[:chars].decode("utf-8", errors="ignore").strip()

    if not value:
        msg = "Filename cannot be empty after sanitisation"
        raise ValueError(msg)
    return value


def build_path(
    author: str,
    title: str,
    *,
    book_id: int | None = None,
    chars: int = 96,
    force_unidecode: bool = False,
) -> str:
    """Build the library-relative path ``Author/Title`` (or ``Title (id)``).

    Each component is sanitised with :func:`valid_filename`. The separator is
    always ``/`` regardless of OS, matching how Calibre stores ``books.path``.
    When *book_id* is given, the Calibre ``" (id)"`` suffix is appended to the
    title directory.
    """
    author_dir = valid_filename(author, chars=chars, force_unidecode=force_unidecode)
    title_dir = valid_filename(title, chars=chars, force_unidecode=force_unidecode)
    if book_id is not None:
        title_dir = f"{title_dir} ({book_id})"
    return f"{author_dir}/{title_dir}"
