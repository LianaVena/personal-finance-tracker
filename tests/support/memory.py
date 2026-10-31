"""Optional in-memory filesystem and SQLite fixtures for read-only test runs."""

import sqlite3
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


@contextmanager
def synthetic_files():
    """Redirect temporary test files and databases to memory.

    Source reads retain their normal behavior. Writes outside registered test
    directories and database connections outside memory are rejected.

    Yields:
        Control to the test runner with the temporary fixture adapters installed.
    """
    original_connect = sqlite3.connect
    methods = ("exists", "stat", "mkdir", "write_bytes", "write_text", "read_bytes",
               "read_text", "iterdir", "is_file", "is_dir")
    original = {name: getattr(Path, name) for name in methods}
    roots: set[Path] = set()
    directories: set[Path] = set()
    files: dict[Path, bytes] = {}
    databases: dict[Path, tuple[str, sqlite3.Connection]] = {}
    sequence = 0

    def virtual(path: Path) -> bool:
        """Check whether a path belongs to a registered synthetic directory.

        Args:
            path: Path being accessed by a test.

        Returns:
            Whether a virtual fixture directory contains the path.
        """
        return any(path == root or root in path.parents for root in roots)

    class MemoryDirectory:
        """Replace temporary directories with registered virtual paths."""

        def __init__(self, *_args, **_kwargs):
            """Register a fresh directory without writing to disk.

            Args:
                *_args: Unused temporary-directory positional options.
                **_kwargs: Unused temporary-directory keyword options.
            """
            self.root = Path(tempfile.gettempdir()) / f"finance-memory-fixture-{len(roots)}"
            self.name = str(self.root)
            roots.add(self.root)
            directories.add(self.root)

        def cleanup(self) -> None:
            """Close the SQLite keepers belonging to this fixture directory."""
            for path, (_, keeper) in list(databases.items()):
                if self.root in path.parents:
                    keeper.close()
                    del databases[path]

        def __enter__(self) -> str:
            """Enter the synthetic directory context.

            Returns:
                Virtual directory name, matching the temporary-directory API.
            """
            return self.name

        def __exit__(self, *_exception) -> None:
            """Release database keepers without suppressing exceptions.

            Args:
                *_exception: Exception details supplied by the context manager.
            """
            self.cleanup()

    def connect(database, *args, **kwargs):
        """Open an isolated SQLite database backed only by memory.

        Args:
            database: In-memory database name or registered synthetic fixture path.
            *args: Additional SQLite connection options.
            **kwargs: Named SQLite connection options.

        Returns:
            Connection to the fixture's shared in-memory database.

        Raises:
            RuntimeError: The requested database is not a registered fixture.
        """
        nonlocal sequence
        if database == ":memory:":
            return original_connect(database, *args, **kwargs)
        path = Path(database)
        if not virtual(path):
            raise RuntimeError("Only synthetic in-memory databases are allowed")
        if path not in databases:
            sequence += 1
            uri = f"file:finance-memory-fixture-{sequence}?mode=memory&cache=shared"
            databases[path] = (uri, original_connect(uri, uri=True))
        return original_connect(databases[path][0], *args, uri=True, **kwargs)

    def exists(path):
        """Report virtual fixture existence or delegate source-path checks.

        Args:
            path: Path being checked.

        Returns:
            Whether the path exists in memory or on the source filesystem.
        """
        return path in files or path in directories or path in databases if virtual(path) else original["exists"](path)

    def stat(path, *args, **kwargs):
        """Report fixture sizes while preserving normal source metadata reads.

        Args:
            path: Path being inspected.
            *args: Positional filesystem metadata options.
            **kwargs: Named filesystem metadata options.

        Returns:
            Fixture size metadata or the original filesystem metadata.

        Raises:
            FileNotFoundError: The requested virtual fixture does not exist.
        """
        if not virtual(path):
            return original["stat"](path, *args, **kwargs)
        if not exists(path):
            raise FileNotFoundError(str(path))
        return SimpleNamespace(st_size=len(files[path]) if path in files else 1)

    def mkdir(path, *_args, **_kwargs):
        """Register a directory inside a synthetic fixture.

        Args:
            path: Fixture directory to create.
            *_args: Unused directory creation options.
            **_kwargs: Unused directory creation options.

        Raises:
            RuntimeError: The operation would write to the real filesystem.
        """
        if not virtual(path):
            raise RuntimeError("No filesystem writes during in-memory tests")
        directories.add(path)

    def write_bytes(path, data):
        """Store synthetic file bytes in memory.

        Args:
            path: Registered fixture file path.
            data: Bytes to store.

        Returns:
            Number of bytes stored.

        Raises:
            RuntimeError: The operation would write to the real filesystem.
        """
        if not virtual(path):
            raise RuntimeError("No filesystem writes during in-memory tests")
        files[path] = bytes(data)
        return len(data)

    def write_text(path, data, encoding=None, errors=None, newline=None):
        """Encode and store synthetic text in memory.

        Args:
            path: Registered fixture file path.
            data: Text to store.
            encoding: Text encoding, defaulting to UTF-8.
            errors: Encoding error policy, defaulting to strict.
            newline: Optional newline replacement applied before encoding.

        Returns:
            Number of original text characters stored.
        """
        encoded = data.replace("\n", newline) if newline else data
        write_bytes(path, encoded.encode(encoding or "utf-8", errors or "strict"))
        return len(data)

    def read_bytes(path):
        """Read virtual fixture bytes or delegate public source reads.

        Args:
            path: Fixture or source path to read.

        Returns:
            File bytes from memory or the source filesystem.
        """
        return files[path] if virtual(path) else original["read_bytes"](path)

    def read_text(path, encoding=None, errors=None, newline=None):
        """Decode fixture text or delegate public source reads.

        Args:
            path: Fixture or source path to read.
            encoding: Text encoding, defaulting to UTF-8 for fixtures.
            errors: Decoding error policy, defaulting to strict.
            newline: Newline option forwarded for source reads.

        Returns:
            Decoded file text.
        """
        if virtual(path):
            return files[path].decode(encoding or "utf-8", errors or "strict")
        return original["read_text"](path, encoding=encoding, errors=errors, newline=newline)

    def iterdir(path):
        """List direct fixture children or delegate source directory traversal.

        Args:
            path: Directory whose direct children are requested.

        Returns:
            Iterator over child paths.
        """
        if virtual(path):
            return iter(sorted(child for child in set(files) | directories | set(databases) if child.parent == path))
        return original["iterdir"](path)

    def is_file(path):
        """Identify fixture files or delegate source file checks.

        Args:
            path: Path being checked.

        Returns:
            Whether the path represents a file.
        """
        return path in files or path in databases if virtual(path) else original["is_file"](path)

    def is_dir(path):
        """Identify fixture directories or delegate source directory checks.

        Args:
            path: Path being checked.

        Returns:
            Whether the path represents a directory.
        """
        return path in directories if virtual(path) else original["is_dir"](path)

    replacements = {"exists": exists, "stat": stat, "mkdir": mkdir, "write_bytes": write_bytes,
                    "write_text": write_text, "read_bytes": read_bytes, "read_text": read_text,
                    "iterdir": iterdir, "is_file": is_file, "is_dir": is_dir}
    with ExitStack() as stack:
        stack.enter_context(patch.object(tempfile, "TemporaryDirectory", MemoryDirectory))
        stack.enter_context(patch.object(sqlite3, "connect", connect))
        for name, replacement in replacements.items():
            stack.enter_context(patch.object(Path, name, replacement))
        try:
            yield
        finally:
            for _, remaining_connection in databases.values():
                remaining_connection.close()
