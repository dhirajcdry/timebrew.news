from datetime import datetime


def normalize_delivery_time(time_str):
    """Normalize a delivery time to canonical 'HH:MM:SS'.

    Accepts 'HH:MM' (what the web client's <input type="time"> sends) or
    'HH:MM:SS', and treats '24:..' as midnight. Raises ValueError on anything
    else so callers can reject bad input.
    """
    value = str(time_str).strip()
    if value.startswith("24:"):
        value = "00:" + value[3:]
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value, fmt).strftime("%H:%M:%S")
        except ValueError:
            continue
    raise ValueError(f"Invalid delivery time '{time_str}' (expected HH:MM or HH:MM:SS)")


def format_time_ampm(time_str):
    """
    Convert 24-hour time format to 12-hour AM/PM format.

    Args:
        time_str (str): Time in 24-hour format ('19:30' or '19:30:00').

    Returns:
        str: Time string in 12-hour AM/PM format (e.g., "07:30 PM")
    """
    return datetime.strptime(normalize_delivery_time(time_str), "%H:%M:%S").strftime("%I:%M %p")
