"""Synthetic event-loop error tests without sockets, files, or a server."""

import unittest
from collections.abc import Callable
from typing import Any
from unittest.mock import Mock, patch

from src.interface.server_errors import install_disconnect_handler


class DisconnectHandlerTests(unittest.TestCase):
    """Limit filtering to the exact Windows socket teardown failure."""

    @staticmethod
    def install(previous: Callable[..., None] | None = None) -> tuple[Mock, Callable[..., None]]:
        """Install the disconnect filter on a mocked event loop.

        Args:
            previous: Optional existing exception handler to preserve.

        Returns:
            Mocked event loop and its installed exception handler.
        """
        loop = Mock()
        loop.get_exception_handler.return_value = previous
        with patch("src.interface.server_errors.asyncio.get_running_loop", return_value=loop):
            install_disconnect_handler()
        return loop, loop.set_exception_handler.call_args.args[0]

    @staticmethod
    def teardown_error(error: OSError) -> OSError:
        """Attach a synthetic Windows socket teardown frame to an exception.

        Args:
            error: Operating-system exception raised by the synthetic callback.

        Returns:
            The supplied exception with a teardown traceback attached.

        Raises:
            AssertionError: The synthetic callback unexpectedly returns normally.
        """
        namespace: dict[str, Any] = {"__name__": "asyncio.proactor_events"}
        exec("def _call_connection_lost(error):\n    raise error\n", namespace)
        try:
            namespace["_call_connection_lost"](error)
        except OSError as raised:
            return raised
        raise AssertionError("Synthetic callback did not raise")

    def test_filters_only_windows_connection_reset_during_teardown(self):
        """Suppress WinError 10054 only when its traceback identifies socket teardown."""
        loop, handler = self.install()
        error = ConnectionResetError("Synthetic disconnected client")
        # noinspection SpellCheckingInspection
        error.winerror = 10054
        handler(loop, {"exception": self.teardown_error(error)})
        loop.default_exception_handler.assert_not_called()

    def test_preserves_unrelated_errors_and_resets_outside_teardown(self):
        """Forward unrelated failures to the previously installed exception handler."""
        previous = Mock()
        loop, handler = self.install(previous)
        reset = ConnectionResetError("Synthetic application reset")
        # noinspection SpellCheckingInspection
        reset.winerror = 10054
        other_reset = ConnectionResetError("Different Windows reset code")
        # noinspection SpellCheckingInspection
        other_reset.winerror = 10053
        for error in (reset, ValueError("Application failure"),
                      self.teardown_error(OSError("Different teardown failure")),
                      self.teardown_error(other_reset)):
            with self.subTest(error=error):
                context = {"exception": error}
                handler(loop, context)
                previous.assert_called_with(loop, context)
        self.assertEqual(previous.call_count, 4)
        loop.default_exception_handler.assert_not_called()

    def test_uses_default_handler_when_no_previous_handler_exists(self):
        """Delegate unfiltered failures to asyncio's default exception handler."""
        loop, handler = self.install()
        context = {"message": "Other asyncio failure"}
        handler(loop, context)
        loop.default_exception_handler.assert_called_once_with(context)
