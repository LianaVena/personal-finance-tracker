"""Synthetic NiceGUI elements and UI recording helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock


class ElementProps(dict[str, Any]):
    """Support NiceGUI's callable and dictionary-style public props API."""

    def __init__(self, element: Element):
        """Attach the property recorder to an element.

        Args:
            element: Fake element whose property changes are recorded.
        """
        super().__init__()
        self.element = element

    def __call__(self, value: str):
        """Record a property string and support chained element calls.

        Args:
            value: NiceGUI property expression supplied by the renderer.

        Returns:
            Element owning this property recorder.
        """
        self.element.props_history.append(value)
        return self.element


class Element:
    """Record the public element operations needed by the renderers."""

    def __init__(self, kind: str, args: tuple = (), **kwargs: Any):
        """Create an element recorder without starting NiceGUI.

        Args:
            kind: NiceGUI element factory name.
            args: Positional arguments passed to the factory.
            **kwargs: Factory options, including values and click callbacks.
        """
        self.kind, self.args = kind, args
        self.kwargs: dict[str, Any] = kwargs
        self.value = kwargs.get("value")
        self.handlers = {}
        self.slots = {}
        self.props_history: list[str] = []
        self.props = ElementProps(self)
        self.style_history: list[str] = []
        self.title = None
        self.disabled = False
        self.parent: Element | None = None
        self.ui_context: FakeUi | None = None
        self.text = args[0] if kind == "label" and args else ""
        if "on_click" in kwargs:
            self.handlers["click"] = kwargs["on_click"]

    def __enter__(self):
        """Enter the element's child context.

        Returns:
            This element, now the parent of controls created in its context.
        """
        if self.ui_context is not None:
            self.ui_context.parents.append(self)
        return self

    def __exit__(self, *_):
        """Leave the child context without suppressing exceptions.

        Args:
            *_: Exception details supplied by the context manager protocol.

        Returns:
            ``False`` so exceptions propagate to the test runner.
        """
        if self.ui_context is not None:
            self.ui_context.parents.pop()
        return False

    def classes(self, *_):
        """Accept CSS class operations for fluent renderer calls.

        Args:
            *_: Class expressions supplied by the renderer.

        Returns:
            This element for chained calls.
        """
        return self

    def style(self, value: str):
        """Record an inline style update.

        Args:
            value: CSS declarations applied to the element.

        Returns:
            This element for chained calls.
        """
        self.style_history.append(value)
        return self

    def tooltip(self, title):
        """Record a hover label.

        Args:
            title: Text displayed on hover.

        Returns:
            This element for chained calls.
        """
        self.title = title
        return self

    def on(self, event, callback):
        """Register a synthetic event callback.

        Args:
            event: Event name used by the renderer.
            callback: Handler invoked explicitly by a test.

        Returns:
            This element for chained calls.
        """
        self.handlers[event] = callback
        return self

    def on_value_change(self, callback):
        """Register a callback for value changes.

        Args:
            callback: Handler receiving a synthetic event with a value attribute.

        Returns:
            This element for chained calls.
        """
        return self.on("value", callback)

    def set_value(self, value):
        """Set the stored value and invoke its change handler.

        Args:
            value: New synthetic control value.

        Returns:
            This element for chained calls.
        """
        self.value = value
        if "value" in self.handlers:
            self.handlers["value"](SimpleNamespace(value=value))
        return self

    def open(self):
        """Open the synthetic popup.

        Returns:
            This element with a true value.
        """
        return self.set_value(True)

    def close(self):
        """Close the synthetic popup.

        Returns:
            This element with a false value.
        """
        return self.set_value(False)

    def toggle(self):
        """Invert the synthetic popup's open state.

        Returns:
            This element with its updated value.
        """
        return self.set_value(not self.value)

    def add_slot(self, name, content):
        """Record a Vue slot template.

        Args:
            name: Slot name used by the renderer.
            content: Template source attached to the slot.
        """
        self.slots[name] = content

    def clear(self):
        """Accept container clears without removing recorded test history."""
        pass

    def set_text(self, text):
        """Replace the recorded display text.

        Args:
            text: New label or button text.
        """
        self.text = text

    def disable(self):
        """Mark the synthetic control as disabled."""
        self.disabled = True

    def enable(self):
        """Mark the synthetic control as enabled."""
        self.disabled = False


class FakeUi:
    """Build controls without NiceGUI, a browser, files, or a server."""

    def __init__(self):
        """Initialize element history, parent contexts, and mocked UI services."""
        self.elements = []
        self.parents: list[Element] = []
        self.notify = Mock()
        self.run_javascript = AsyncMock()

    def __getattr__(self, kind):
        """Build a recorder factory for a NiceGUI element type.

        Args:
            kind: Attribute name corresponding to a NiceGUI element factory.

        Returns:
            Factory that records controls and their current parent context.
        """

        def create(*args, **kwargs):
            """Record a control created by the renderer.

            Args:
                *args: Positional arguments forwarded to the fake element.
                **kwargs: Named element options and callbacks.

            Returns:
                Newly recorded element.
            """
            element = Element(kind, args, **kwargs)
            element.parent = self.parents[-1] if self.parents else None
            element.ui_context = self
            self.elements.append(element)
            return element

        return create

    def find(self, kind, label=None, title=None):
        """Find recorded controls by type and optional text.

        Args:
            kind: Element factory name to match.
            label: Optional positional or named label to match.
            title: Optional tooltip text to match.

        Returns:
            Matching elements in creation order.
        """
        return [
            element for element in self.elements if element.kind == kind
                                                    and (label is None or (element.args and element.args[0] == label)
                                                         or element.kwargs.get("label") == label)
                                                    and (title is None or element.title == title)
        ]
