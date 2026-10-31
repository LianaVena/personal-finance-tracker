"""Sorting and validation helpers for database-backed subcategory colors."""

from collections.abc import Iterable

DEFAULT_SUBCATEGORY_COLOR: int | None = None
ColorRow = tuple[int, str, str, str]


def sort_subcategory_colors(colors: Iterable[ColorRow]) -> list[ColorRow]:
    """Sort stored colors by hue, placing muted neutrals after vivid colors.

    Args:
        colors: Database rows containing ID, row hex, pie hex, and name.

    Returns:
        Colors ordered by hue, saturation, brightness, and name.
    """

    def color_key(row: ColorRow) -> tuple[bool, float, float, float, str]:
        """Calculate the sortable HSV key for one database row.

        Args:
            row: Color ID, row hex, pie hex, and display name.

        Returns:
            Neutral status, hue, inverse saturation, inverse brightness, and name.
        """
        _, _, pie_hex, name = row
        red, green, blue = (int(pie_hex[index:index + 2], 16) / 255 for index in (1, 3, 5))
        high, low = max(red, green, blue), min(red, green, blue)
        delta = high - low
        saturation = delta / high if high else 0.0
        if delta == 0:
            hue = 0.0
        elif high == red:
            hue = ((green - blue) / delta) % 6
        elif high == green:
            hue = (blue - red) / delta + 2
        else:
            hue = (red - green) / delta + 4
        hue *= 60
        return saturation < 0.2, hue, -saturation, -high, name.casefold()

    return sorted(colors, key=color_key)


def normalize_subcategory_color(value: int | str | None, colors: Iterable[ColorRow]) -> int | None:
    """Validate a selected color ID against rows loaded from the database.

    Args:
        value: Color ID from a form, blank value, or ``None`` for no color.
        colors: Available color rows loaded from the finance database.

    Returns:
        A valid color ID, or ``None`` when no color is selected.

    Raises:
        ValueError: The selected ID does not exist in the available colors.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if type(value) is int and any(color_id == value for color_id, _, _, _ in colors):
        return value
    raise ValueError("Choose a subcategory color from the available colors")
