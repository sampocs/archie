"""Money helpers shared across services.

One rule, enforced here so it can't be re-litigated per component: money is always `Decimal`
(per-call model costs are fractions of a cent, which floats round badly), stored to six places,
and formatted for logs with two (`:.2f`).
"""

from decimal import ROUND_HALF_EVEN, Decimal

_USD_PLACES = Decimal("0.000001")


def quantize_usd(amount: Decimal) -> Decimal:
    """Round a USD amount to six places using banker's rounding."""
    return amount.quantize(_USD_PLACES, rounding=ROUND_HALF_EVEN)


def format_usd(amount: Decimal) -> str:
    """Format a USD amount for logs and display, e.g. '1234.50'."""
    return f"{amount:.2f}"
