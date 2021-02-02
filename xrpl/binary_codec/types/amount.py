"""
Defines how to serialize and deserialize an amount field.
See `Amount Fields <https://xrpl.org/serialization.html#amount-fields>`_
"""
from __future__ import annotations

from decimal import Context, Decimal, getcontext, setcontext
from typing import Dict, Optional, Union

from typing_extensions import Final

from xrpl.binary_codec.binary_wrappers import BinaryParser
from xrpl.binary_codec.exceptions import XRPLBinaryCodecException
from xrpl.binary_codec.types.account_id import AccountID
from xrpl.binary_codec.types.currency import Currency
from xrpl.binary_codec.types.serialized_type import SerializedType

# Constants for validating amounts.
_MIN_IOU_EXPONENT: Final = -96
_MAX_IOU_EXPONENT: Final = 80
_MAX_IOU_PRECISION: Final = 16
_MIN_MANTISSA: Final = 10 ** 15
_MAX_MANTISSA: Final = 10 ** 16 - 1

# Configure Decimal
setcontext(
    Context(prec=_MAX_IOU_PRECISION, Emax=_MAX_IOU_EXPONENT, Emin=_MIN_IOU_EXPONENT)
)

_MAX_DROPS: Final = Decimal("1e17")
_MIN_XRP: Final = Decimal("1e-6")

# other constants:
_NOT_XRP_BIT_MASK: Final = 0x80
_POS_SIGN_BIT_MASK: Final = 0x4000000000000000
_ZERO_CURRENCY_AMOUNT_HEX: Final = 0x8000000000000000
_NATIVE_AMOUNT_BYTE_LENGTH: Final = 8
_CURRENCY_AMOUNT_BYTE_LENGTH: Final = 48


def _contains_decimal(string: str) -> bool:
    """Returns True if the given string contains a decimal point character.

    Args:
        string: The string to check.

    Returns:
        True if the string contains a decimal point character.
    """
    return string.find(".") == -1


def _is_valid_issued_currency_amount(value: Dict) -> bool:
    """
    Determines whether given dictionary represents a valid issued currency amount,
    which must contain exactly "currency", "issuer" and "value" keys.

    Args:
        value: A dictionary representing an issued currency amount.

    Returns:
        None, but raises if value is an invalid issued currency amount.

    Raises:
        XRPLBinaryCodecException: If value is an invalid issued currency amount.
    """
    if len(value.keys()) != 3:
        return False
    expected_keys = set(["currency", "issuer", "value"])
    if set(value.keys()) == expected_keys:
        return True
    return False


def verify_xrp_value(xrp_value: str) -> None:
    """
    Validates the format of an XRP amount.
    Raises if value is invalid.

    Args:
        xrp_value: A string representing an amount of XRP.

    Returns:
        None, but raises if xrp_value is not a valid XRP amount.

    Raises:
        XRPLBinaryCodecException: If xrp_value is not a valid XRP amount.
    """
    # Contains no decimal point
    if not _contains_decimal(xrp_value):
        raise XRPLBinaryCodecException("{} is an invalid XRP amount.".format(xrp_value))

    # Within valid range
    decimal = Decimal(xrp_value)
    # Zero is less than both the min and max XRP amounts but is valid.
    if decimal.is_zero():
        return
    if (decimal.compare(_MIN_XRP) == -1) or (decimal.compare(_MAX_DROPS) == 1):
        raise XRPLBinaryCodecException("{} is an invalid XRP amount.".format(xrp_value))


def verify_iou_value(issued_currency_value: Decimal) -> None:
    """
    Validates the format of an issued currency amount value.
    Raises if value is invalid.

    Args:
        issued_currency_value: A Decimal object representing the "value"
                                    field of an issued currency amount.

    Returns:
        None, but raises if issued_currency_value is not valid.

    Raises:
        XRPLBinaryCodecException: If issued_currency_value is invalid.
    """
    if issued_currency_value.is_zero():
        return None
    precision = getcontext().prec
    exponent = issued_currency_value.as_tuple().exponent
    if (
        (precision > _MAX_IOU_PRECISION)
        or (exponent > _MAX_IOU_EXPONENT)
        or (exponent < _MIN_IOU_EXPONENT)
    ):
        raise XRPLBinaryCodecException(
            "Decimal precision out of range for issued currency value."
        )
    _verify_no_decimal(issued_currency_value)


def _verify_no_decimal(decimal: Decimal) -> None:
    """
    Ensure that the value after being multiplied by the exponent
    does not contain a decimal.

    :param decimal: A Decimal object.
    """
    actual_exponent = decimal.as_tuple().exponent
    exponent = Decimal("1e" + str(-(int(actual_exponent) - 15)))
    # str(Decimal) uses sci notation by default... get around w/ string format
    int_number_string = "{:f}".format(decimal * exponent)
    if not _contains_decimal(int_number_string):
        raise XRPLBinaryCodecException("Decimal place found in int_number_str")


def _serialize_issued_currency_value(value: str) -> bytes:
    """
    Serializes the value field of an issued currency amount to its bytes representation.

    :param value: The value to serialize, as a string.
    :return: A bytes object encoding the serialized value.
    """
    decimal_value = Decimal(value)
    verify_iou_value(decimal_value)
    if decimal_value.is_zero():
        return _ZERO_CURRENCY_AMOUNT_HEX.to_bytes(8, byteorder="big")

    # Convert components to integers ---------------------------------------
    sign, digits, exp = decimal_value.as_tuple()
    mantissa = int("".join([str(d) for d in digits]))

    # Canonicalize to expected range ---------------------------------------
    while mantissa < _MIN_MANTISSA and exp > _MIN_IOU_EXPONENT:
        mantissa *= 10
        exp -= 1

    while mantissa > _MAX_MANTISSA:
        if exp >= _MAX_IOU_EXPONENT:
            raise XRPLBinaryCodecException(
                "Amount overflow in issued currency value {}".format(str(value))
            )
        mantissa //= 10
        exp += 1

    if exp < _MIN_IOU_EXPONENT or mantissa < _MIN_MANTISSA:
        # Round to zero
        _ZERO_CURRENCY_AMOUNT_HEX.to_bytes(8, byteorder="big", signed=False)

    if exp > _MAX_IOU_EXPONENT or mantissa > _MAX_MANTISSA:
        raise XRPLBinaryCodecException(
            "Amount overflow in issued currency value {}".format(str(value))
        )

    # Convert to bytes -----------------------------------------------------
    serial = _ZERO_CURRENCY_AMOUNT_HEX  # "Not XRP" bit set
    if sign == 0:
        serial |= _POS_SIGN_BIT_MASK  # "Is positive" bit set
    serial |= (exp + 97) << 54  # next 8 bits are exponents
    serial |= mantissa  # last 54 bits are mantissa

    return serial.to_bytes(8, byteorder="big", signed=False)


def _serialize_xrp_amount(value: str) -> bytes:
    """Serializes an XRP amount.

    Args:
        value: A string representing a quantity of XRP.

    Returns:
        The bytes representing the serialized XRP amount.
    """
    verify_xrp_value(value)
    # set the "is positive" bit (this is backwards from usual two's complement!)
    value_with_pos_bit = int(value) | _POS_SIGN_BIT_MASK
    return value_with_pos_bit.to_bytes(8, byteorder="big")


def _serialize_issued_currency_amount(value: Dict) -> bytes:
    """Serializes an issued currency amount.

    Args:
        value: A dictionary representing an issued currency amount

    Returns:
         The bytes representing the serialized issued currency amount.
    """
    amount_string = value["value"]
    amount_bytes = _serialize_issued_currency_value(amount_string)
    currency_bytes = Currency.from_value(value["currency"]).to_bytes()
    issuer_bytes = AccountID.from_value(value["issuer"]).to_bytes()
    return amount_bytes + currency_bytes + issuer_bytes


class Amount(SerializedType):
    """Defines how to serialize and deserialize an amount.
    See `Amount Fields <https://xrpl.org/serialization.html#amount-fields>`_
    """

    def __init__(self: Amount, buffer: bytes) -> None:
        """Construct an Amount from given bytes."""
        super().__init__(buffer)

    @classmethod
    def from_value(cls: Amount, value: Union[str, Dict]) -> Amount:
        """
         Construct an Amount from an issued currency amount or (for XRP),
        a string amount.

        See `Amount Fields <https://xrpl.org/serialization.html#amount-fields>`_

        Args:
            value: The value from which to construct an Amount.

        Returns:
            An Amount object.

        Raises:
            XRPLBinaryCodecException: if an Amount cannot be constructed.
        """
        if isinstance(value, str):
            return cls(_serialize_xrp_amount(value))
        if _is_valid_issued_currency_amount(value):
            return cls(_serialize_issued_currency_amount(value))

        raise XRPLBinaryCodecException("Invalid type to construct an Amount")

    @classmethod
    def from_parser(
        cls: Amount, parser: BinaryParser, length_hint: Optional[int] = None
    ) -> Amount:
        """Construct an Amount from an existing BinaryParser.

        Args:
            parser: The parser to construct the Amount object from.
            length_hint: Unused.

        Returns:
            An Amount object.
        """
        not_xrp = int(parser.peek()) & 0x80
        if not_xrp:
            num_bytes = _CURRENCY_AMOUNT_BYTE_LENGTH
        else:
            num_bytes = _NATIVE_AMOUNT_BYTE_LENGTH
        return cls(parser.read(num_bytes))

    def to_json(self: Amount) -> Union[str, Dict]:
        """Construct a JSON object representing this Amount.

        Returns:
            The JSON representation of this amount.
        """
        if self.is_native():
            sign = "" if self.is_positive() else "-"
            masked_bytes = (
                int.from_bytes(self.buffer, byteorder="big") & 0x3FFFFFFFFFFFFFFF
            )
            return "{}{}".format(sign, masked_bytes)
        parser = BinaryParser(self.to_string())
        value_bytes = parser.read(8)
        currency = Currency.from_parser(parser)
        issuer = AccountID.from_parser(parser)
        b1 = value_bytes[0]
        b2 = value_bytes[1]
        is_positive = b1 & 0x40
        sign = "" if is_positive else "-"
        exponent = ((b1 & 0x3F) << 2) + ((b2 & 0xFF) >> 6) - 97
        hex_mantissa = hex(b2 & 0x3F) + value_bytes[2:].hex()
        int_mantissa = int(hex_mantissa[2:], 16)
        value = Decimal("{}{}".format(sign, int_mantissa)) * Decimal(
            "1e{}".format(exponent)
        )

        verify_iou_value(value)
        if value.is_zero():
            value_str = "0"
        else:
            value_str = str(value).rstrip("0").rstrip(".")

        return {
            "value": value_str,
            "currency": currency.to_json(),
            "issuer": issuer.to_json(),
        }

    def is_native(self: Amount) -> bool:
        """Returns True if this amount is a native XRP amount.

        Returns:
            True if this amount is a native XRP amount, False otherwise.
        """
        # 1st bit in 1st byte is set to 0 for native XRP
        return (self.buffer[0] & 0x80) == 0

    def is_positive(self: Amount) -> bool:
        """Returns True if 2nd bit in 1st byte is set to 1 (positive amount).

        Returns:
            True if 2nd bit in 1st byte is set to 1 (positive amount),
            False otherwise.
        """
        return (self.to_bytes()[0] & 0x40) > 0