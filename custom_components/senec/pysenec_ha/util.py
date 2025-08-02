import copy
import logging
from struct import unpack, pack

_LOGGER = logging.getLogger(__name__)

_MASKED_VALUES = ["host", "username", "password", "street", "email", "phonenumber", "housenumber", "website",
                  "app_token", "access_token", "refresh_token", "id_token",
                  "maincontrollerserial", "serial", "serialnumber", "dserial",
                  "device_id", "controllerid", "systemid", "app_master_plant_id"]

def mask_map(d: dict) -> dict:
    if not isinstance(d, dict):
        _LOGGER.info(f"mask_map expects a dictionary, got '{type(d).__name__}'")
        return d
    else:
        return mask_map_internal(copy.deepcopy(d))

def mask_map_internal(d: dict) -> dict:
    for k, v in d.copy().items():
        if isinstance(v, dict):
            d.pop(k)
            d[k] = v
            mask_map_internal(v)
        elif isinstance(v, list):
            d.pop(k)
            d[k] = [mask_map_internal(item) if isinstance(item, dict) else
                    ("<MASKED>" if isinstance(item, str) and k.lower() in _MASKED_VALUES else item)
                    for item in v]
        else:
            if k.lower() in _MASKED_VALUES:
                v = "<MASKED>"
            d.pop(k)
            d[k] = v
    return d

def mask_string(text: str, show_chars: int = 6) -> str:
    """Return a masked string showing only first and last characters with dots in between"""
    if text is None or len(text) <= show_chars * 2:
        if show_chars > 3:
            return mask_string(text, show_chars=show_chars-1)
        else:
            return text
    return f"{text[:show_chars]}…{text[-show_chars:]}"

def parse_value(value: str):
    """Parses numeric values, Senec supplies them as hex."""

    try:
        parts = value.split("_")
        key = parts[0]
        if len(parts) > 2:
            value = '_'.join(parts[1:])
        elif len(parts) > 1:
            value = parts[1]
        else:
            # looks like the value is 'not encoded' - no '_' present...
            return value

    except Exception as e:
        _LOGGER.error(f"Error parsing value: {value} - {e}")
        return value

    # if key == "u8":
    #    return unpack(">B", bytes.fromhex(value))[0]
    # el
    if key.startswith("u") or key.startswith("i"):
        # Unsigned and signed int
        return int(value, 16)
    elif key == "fl":
        # Float in hex IEEE 754
        # sample: value = 43E26188
        return unpack(">f", bytes.fromhex(value))[0]
    elif key == "st":
        # String
        return value
    return f"{key}_{value}"


def parse(raw: dict):
    for k, v in raw.items():
        if isinstance(v, str):
            raw[k] = parse_value(v)
        elif isinstance(v, dict):
            raw[k] = parse(v)
        elif isinstance(v, list):
            raw[k] = [parse_value(i) for i in v]
    return raw


def get_as_hex(input, length: int) -> str:
    out = f'{input:X}'
    while len(out) < length:
        out = '0' + out

    return out;


def get_float_as_IEEE754_hex(input: float) -> str:
    val = unpack('I', pack('f', input))[0]
    return get_as_hex(val, -1);
