"""Compact subcategory color control with a named palette in a native popup."""

from collections.abc import Callable
from math import ceil

from nicegui import ui

from ..subcategory_colors import ColorRow, normalize_subcategory_color


class SubcategoryColorGrid:
    """Open a three-row, ten-column palette from an inline color control."""

    def __init__(self, value: int | None, on_change: Callable[[int | None], None],
                 colors: list[ColorRow]) -> None:
        """Create an inline picker with a popup of named color swatches.

        Args:
            value: Initial color ID, or ``None`` for no color.
            on_change: Callback receiving the selected color ID or ``None``.
            colors: Available database color rows, already ordered for display.
        """
        self.value = value
        self.on_change = on_change
        self.colors = {color_id: (row_hex, pie_hex, name)
                       for color_id, row_hex, pie_hex, name in colors}
        column_count = max(1, ceil((len(self.colors) + 1) / 3))
        unused_cells = column_count * 3 - len(self.colors) - 1
        self.buttons: dict[int | None, ui.button] = {}
        with ui.row().classes("items-center gap-2 flex-nowrap").style("flex-shrink: 0;"):
            self.preview = ui.element("span").props("aria-hidden=true").style(
                "width: 16px; height: 16px; border-radius: 4px; flex-shrink: 0;"
            )
            self.trigger = ui.button(
                "No color", icon="palette", color="grey-4", on_click=lambda: self.menu.toggle(),
            ).props(
                'dense outline no-caps type=button aria-haspopup=menu aria-expanded=false '
                'aria-label="Choose subcategory color"'
            ).style("width: 160px; min-width: 160px; max-width: 160px; height: 42px; flex-shrink: 0;")
            with self.trigger:
                self.tooltip = ui.tooltip("No color")
                with ui.menu(value=False).props("no-parent-event").classes("rounded-lg") as self.menu:
                    with ui.element("div").props('role=group aria-label="Subcategory color"').style(
                            f"display: grid; grid-template-columns: repeat({column_count}, minmax(0, 1fr)); "
                            "grid-template-rows: repeat(3, minmax(0, 1fr)); gap: 6px; "
                            "padding: 8px; box-sizing: border-box; width: 240px; max-width: calc(100vw - 24px);"
                    ):
                        self.buttons[None] = ui.button(
                            icon="format_color_reset", color="grey-4", on_click=lambda: self.select(None),
                        ).props('flat type=button aria-label="No color"').tooltip("No color")
                        for color_id, (_, pie_hex, name) in self.colors.items():
                            self.buttons[color_id] = ui.button(
                                icon="check", on_click=lambda selected=color_id: self.select(selected),
                            ).props(
                                f'unelevated type=button aria-label="{name}"'
                            ).style(f"background-color: {pie_hex};").tooltip(name)
                        for _ in range(unused_cells):
                            ui.element("span").props("aria-hidden=true")
        self.menu.on_value_change(
            lambda event: self.trigger.props(f"aria-expanded={'true' if event.value else 'false'}")
        )
        self.update_selection()

    def select(self, color: int | None) -> None:
        """Pick or clear a color and retain the value in the form draft.

        Args:
            color: Offered color ID, or ``None`` for no color.
        """
        available_colors = [(color_id, row_hex, pie_hex, name)
                            for color_id, (row_hex, pie_hex, name) in self.colors.items()]
        self.value = normalize_subcategory_color(color, available_colors)
        self.update_selection()
        self.menu.close()
        self.on_change(self.value)

    def update_selection(self) -> None:
        """Update the selected cell, preview, and color-control text."""
        for color, button in self.buttons.items():
            selected = color == self.value
            button.props(f"aria-pressed={'true' if selected else 'false'}").style(
                "width: 100%; aspect-ratio: 1; min-width: 0; min-height: 0; padding: 0; border-radius: 5px; "
                f"background-color: {self.colors[color][1] if color is not None else '#353535'} !important; "
                f"color: {'white' if selected or color is None else 'transparent'} !important; "
                f"box-shadow: {'inset 0 0 0 2px white' if selected else 'none'};"
            )
        if self.value is not None and self.value in self.colors:
            has_color = True
            _, pie_hex, name = self.colors[self.value]
        else:
            has_color = False
            pie_hex, name = "", "No color"
        self.preview.style(
            f"background-color: {pie_hex if has_color else 'transparent'}; "
            f"border: 1px {'solid transparent' if has_color else 'dashed #94a3b8'};"
        )
        self.trigger.set_text(name)
        self.tooltip.set_text(name)
