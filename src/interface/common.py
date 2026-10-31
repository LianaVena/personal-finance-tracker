"""Shared formatting and parsing helpers for the interface pages."""

from decimal import Decimal, InvalidOperation
from typing import Any


def notify(ui_client: Any, *args: Any, **kwargs: Any) -> None:
    """Send a NiceGUI notification without inheriting its Literal false positive.

    Args:
        ui_client: NiceGUI UI object or compatible test double.
        *args: Positional notification arguments forwarded to ``notify``.
        **kwargs: Notification options forwarded unchanged.
    """
    ui_client.notify(*args, **kwargs)


_CURRENCY_SYMBOLS = {
    "EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥", "CNY": "¥",
    "CZK": "Kč", "PLN": "zł", "HUF": "Ft", "CHF": "CHF",
    "CAD": "C$", "AUD": "A$", "NZD": "NZ$", "SEK": "kr", "NOK": "kr",
    "DKK": "kr",
}


def currency_symbol(currency: str | None) -> str:
    """Return the display symbol for a currency code, or the code if unknown.

    Args:
        currency: ISO currency code, or ``None`` when no currency is set.

    Returns:
        Display symbol, uppercase unknown code, or an empty string.
    """
    if not currency:
        return ""
    return _CURRENCY_SYMBOLS.get(currency.upper(), currency.upper())


def format_money(amount_minor: int, currency: str | None, *, absolute: bool = False) -> str:
    """Format an integer minor-unit amount with its currency symbol.

    Args:
        amount_minor: Signed amount in integer minor units.
        currency: ISO currency code, or ``None`` when unavailable.
        absolute: Whether to omit the amount's negative sign.

    Returns:
        The formatted amount followed or prefixed by its currency symbol.
    """
    negative = amount_minor < 0 and not absolute
    amount = Decimal(abs(amount_minor)) / 100
    formatted = f"{amount:.2f}"
    symbol = currency_symbol(currency)
    if not symbol:
        return f"{'-' if negative else ''}{formatted}"
    if currency and currency.upper() in {"USD", "GBP", "JPY", "CNY", "CAD", "AUD", "NZD"}:
        return f"{'-' if negative else ''}{symbol}{formatted}"
    return f"{'-' if negative else ''}{formatted} {symbol}"


def currency_options(current: str | None = None) -> dict[str, str]:
    """Build select options for supported currencies and an unknown current code.

    Args:
        current: Currency code already selected, if any.

    Returns:
        Mapping of currency codes to their display labels.
    """
    options = {code: symbol for code, symbol in _CURRENCY_SYMBOLS.items()}
    if current and current.upper() not in options:
        options[current.upper()] = current.upper()
    return options


def money_to_minor_units(value) -> int | None:
    """Parse a nonzero decimal amount with at most two places into cents.

    Args:
        value: User-entered decimal value, or a blank value.

    Returns:
        Signed integer minor units, or ``None`` when the input is blank.

    Raises:
        ValueError: The input is invalid, non-finite, zero, or has excess precision.
    """
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Enter a valid amount") from error
    if not parsed.is_finite():
        raise ValueError("Enter a finite amount in euros")
    amount = parsed * 100
    if amount != amount.to_integral_value() or amount == 0:
        raise ValueError("Amount must be non-zero and have at most two decimal places")
    return int(amount)
