"""Run synthetic tests with private-path and network access blocked.

Use ``python -B -m tests.run_suite``. Add ``--memory`` for read-only environments.
Add ``--coverage`` to report source
functions whose bodies were not exercised, without writing coverage files.
"""

import ast
import io
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path


def install_test_guard(project: Path, temporary_root: Path) -> None:
    """Block private project data, live networking, and non-test databases.

    Args:
        project: Project root containing the private paths to deny.
        temporary_root: Root of the synthetic files owned by this test run.
    """
    restricted = [project / name for name in ("imports", "secrets", "finance.db", "transactions.db")]

    def audit(event: str, args: tuple) -> None:
        """Reject unsafe filesystem or network operations before they execute.

        Args:
            event: Python audit event name.
            args: Operation-specific arguments supplied by Python.

        Raises:
            RuntimeError: An operation could touch private data or a live service.
        """
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
            raise RuntimeError("Tests may not use live network services")
        if event not in {"open", "sqlite3.connect", "os.listdir", "os.scandir", "os.mkdir",
                         "os.remove", "os.rmdir", "os.rename"} or not args:
            return
        values = args[:2] if event == "os.rename" else args[:1]
        for value in values:
            if not isinstance(value, (str, bytes, os.PathLike)) or value == ":memory:":
                continue
            if (event == "sqlite3.connect" and isinstance(value, str)
                    and value.startswith("file:finance-memory-fixture-")
                    and value.endswith("?mode=memory&cache=shared")):
                continue
            path = Path(os.path.realpath(os.fsdecode(value)))
            if any(path == denied or denied in path.parents for denied in restricted):
                raise RuntimeError("Test attempted to access a restricted project path")
            if event == "sqlite3.connect" and temporary_root not in path.parents:
                raise RuntimeError("Tests may open only in-memory or isolated temporary databases")

    sys.addaudithook(audit)


def report_uncalled_functions(project: Path, executed: dict[str, set[int]]) -> None:
    """Report uncalled functions and executed source statement lines.

    Args:
        project: Project root containing the application source.
        executed: Executed source line numbers keyed by normalized filename.
    """
    statement_count = 0
    executed_count = 0
    for path in sorted((project / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        seen = executed.get(str(path).casefold(), set())
        missing = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = node.body[1:] if ast.get_docstring(node) else node.body
            if not body or all(isinstance(statement, ast.Expr) and
                               isinstance(statement.value, ast.Constant) and
                               statement.value.value is Ellipsis for statement in body):
                continue
            if not any(line in seen for line in range(body[0].lineno, node.end_lineno + 1)):
                missing.append(f"{node.name}:{node.lineno}")
        if missing:
            print(f"{path.relative_to(project)} uncalled: {', '.join(missing)}")
        type_only_lines = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                type_only_lines.update(range(node.lineno, node.end_lineno + 1))
        statements: set[int] = set()
        for statement in ast.walk(tree):
            if not isinstance(statement, ast.stmt):
                continue
            line_number = statement.lineno
            if line_number in type_only_lines:
                continue
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.AnnAssign)):
                continue
            if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
                continue
            statements.add(line_number)
        statement_count += len(statements)
        executed_count += len(statements & seen)
        unseen = statements - seen
        if unseen:
            print(f"{path.relative_to(project)} unexecuted statement lines: {', '.join(map(str, sorted(unseen)))}")
    print(f"Source statement audit: {executed_count}/{statement_count} lines executed "
          "(excludes declarations, docstrings, and type-only imports; does not measure branch coverage)")


def main() -> int:
    """Discover and run tests with isolation enforced before importing tests.

    Returns:
        Zero on success, or one when a test fails or raises an error.
    """
    project = Path(__file__).resolve().parent.parent
    executed: dict[str, set[int]] = {}
    source_prefix = str(project / "src").casefold() + os.sep

    def trace(frame, event, _arg):
        """Record executed application lines without saving coverage artifacts.

        Args:
            frame: Python frame currently being traced.
            event: Trace event type.
            _arg: Event-specific payload, unused for line tracking.

        Returns:
            This trace callback for application frames, or ``None`` for other code.
        """
        filename = frame.f_code.co_filename.casefold()
        if not filename.startswith(source_prefix):
            return None
        if event == "line":
            executed.setdefault(filename, set()).add(frame.f_lineno)
        return trace

    if "--coverage" in sys.argv:
        sys.settrace(trace)
    with ExitStack() as stack:
        if "--memory" in sys.argv:
            from tests.support.memory import synthetic_files
            stack.enter_context(synthetic_files())
        directory = stack.enter_context(tempfile.TemporaryDirectory(prefix="finance-synthetic-tests-"))
        temporary_root = Path(directory).resolve()
        install_test_guard(project, temporary_root)
        previous_tempdir = tempfile.tempdir
        tempfile.tempdir = directory
        try:
            suite = unittest.defaultTestLoader.discover(str(project / "tests"), top_level_dir=str(project))
            output = io.StringIO()
            result = unittest.TextTestRunner(stream=output, verbosity=0).run(suite)
        finally:
            sys.settrace(None)
            tempfile.tempdir = previous_tempdir
        print(f"Ran {result.testsRun} tests: {len(result.failures)} failures, {len(result.errors)} errors")
        for test, detail in result.failures + result.errors:
            print(f"{test.id()}: {detail.splitlines()[-1]}")
        if "--coverage" in sys.argv:
            report_uncalled_functions(project, executed)
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
