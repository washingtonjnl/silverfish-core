# silverfish-core

Core library for Silverfish — the domain rules, ports (interfaces), services
(use cases) and reference adapters for managing an ebook library in the Calibre
dialect.

`domain/` and `services/` never import a concrete adapter or any web framework.
A `LibraryService` is assembled by injecting the adapters you choose
(SQLite-Calibre or Postgres repository, local disk or cloud storage, SMTP or a
managed mailer, etc.).
