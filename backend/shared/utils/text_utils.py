def format_list_with_quotes(items, quote_char="'"):
    """
    Format a list of items with proper grammar and quotes.
    
    Args:
        items (list): List of items to format
        quote_char (str): Quote character to use (default: single quote)
    
    Returns:
        str: Formatted string with proper grammar
    
    Examples:
        format_list_with_quotes(['apple']) -> "'apple'"
        format_list_with_quotes(['apple', 'banana']) -> "'apple' and 'banana'"
        format_list_with_quotes(['apple', 'banana', 'cherry']) -> "'apple', 'banana', and 'cherry'"
    """
    if not items:
        return ""
    
    if len(items) == 1:
        return f"{quote_char}{items[0]}{quote_char}"
    elif len(items) == 2:
        return f"{quote_char}{items[0]}{quote_char} and {quote_char}{items[1]}{quote_char}"
    else:
        # For 3+ items: 'item1', 'item2', and 'item3'
        quoted_items = [f"{quote_char}{item}{quote_char}" for item in items[:-1]]
        return ", ".join(quoted_items) + f", and {quote_char}{items[-1]}{quote_char}"


def format_list_simple(items, separator=", ", final_separator=" and "):
    """
    Format a list of items with custom separators (without quotes).
    
    Args:
        items (list): List of items to format
        separator (str): Separator between items (default: ", ")
        final_separator (str): Separator before the last item (default: " and ")
    
    Returns:
        str: Formatted string with proper grammar
    
    Examples:
        format_list_simple(['apple']) -> "apple"
        format_list_simple(['apple', 'banana']) -> "apple and banana"
        format_list_simple(['apple', 'banana', 'cherry']) -> "apple, banana, and cherry"
    """
    if not items:
        return ""
    
    if len(items) == 1:
        return str(items[0])
    elif len(items) == 2:
        return f"{items[0]}{final_separator}{items[1]}"
    else:
        return separator.join(items[:-1]) + f",{final_separator}{items[-1]}"

def normalize_topics(value):
    """Accept stored topic arrays/JSON without treating a string as characters."""
    import json

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            raise ValueError("Topics must be a JSON array of text")
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(topic, str) for topic in value):
        raise ValueError("Topics must be an array of text")
    return list(dict.fromkeys(topic.strip() for topic in value if topic.strip()))
