"""Handle Windows socket teardown errors from disconnected local clients."""

import asyncio
from traceback import walk_tb
from typing import Any


def install_disconnect_handler() -> None:
    """Filter WinError 10054 during Windows asynchronous connection teardown only.

    Raises:
        RuntimeError: No event loop is running in the current thread.
    """
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()

    def handle_exception(event_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        """Keep unrelated failures visible through the existing loop handler.

        Args:
            event_loop: Event loop reporting the failure.
            context: Asyncio error details, including the exception when available.
        """
        error = context.get("exception")
        if isinstance(error, ConnectionResetError) and getattr(error, "winerror", None) == 10054:
            for frame, _ in walk_tb(error.__traceback__):
                if (frame.f_globals.get("__name__") == "asyncio.proactor_events"
                        and frame.f_code.co_name == "_call_connection_lost"):
                    return
        if previous_handler is not None:
            previous_handler(event_loop, context)
        else:
            event_loop.default_exception_handler(context)

    loop.set_exception_handler(handle_exception)
