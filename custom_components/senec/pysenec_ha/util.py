from struct import unpack


def parse_value(value: str):
    """Parses numeric values, Senec supplies them as hex."""
    try:
        key, value = value.split("_")
    except ValueError:
        return value
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
