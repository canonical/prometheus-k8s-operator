# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Functions for converting between units of measure."""

from decimal import Decimal
from typing import Union

from lightkube.utils.quantity import parse_quantity


def convert_k8s_quantity_to_legacy_binary_gigabytes(
    capacity: str, multiplier: Union[Decimal, float, str] = 1.0
) -> str:
    """Convert a K8s quantity string to legacy binary notation in GB, which prometheus expects.

    Args:
        capacity: a storage quantity in K8s notation.
        multiplier: an optional convenience argument for scaling capacity.

    Returns:
        The capacity, multiplied by `multiplier`, in Prometheus GB (legacy binary) notation.

    >>> convert_k8s_quantity_to_legacy_binary_gigabytes("1Gi")
    '1GB'
    >>> convert_k8s_quantity_to_legacy_binary_gigabytes("1Gi", 0.8)
    '0.8GB'
    >>> convert_k8s_quantity_to_legacy_binary_gigabytes("1G")
    '0.931GB'

    Raises:
        ValueError, if capacity or multiplier are invalid.
    """
    if not isinstance(multiplier, Decimal):
        try:
            multiplier = Decimal(multiplier)
        except ArithmeticError as e:
            raise ValueError("Invalid multiplier") from e

    if not multiplier.is_finite():
        raise ValueError("Multiplier must be finite")

    if not (capacity_as_decimal := parse_quantity(capacity)):
        raise ValueError(f"Invalid capacity value: {capacity}")

    # For simplicity, always communicate to prometheus in GiB
    storage_value = multiplier * capacity_as_decimal / 2**30  # Convert (decimal) bytes to GiB
    quantized = storage_value.quantize(Decimal("0.001"))
    as_str = str(quantized).rstrip("0").rstrip(".")
    return f"{as_str}GB"
