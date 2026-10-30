"""Small helpers for the words the app shows to the user."""

from __future__ import annotations


def count_text(count: int, singular: str, plural: str = "") -> str:
    """Write a number with the right form of a word, such as "1 photo" or "3 photos".

    Args:
        count: The number.
        singular: The word for one thing, such as "photo".
        plural: The word for more than one; the singular with an "s" when empty.

    Returns:
        The number and the word.
    """
    many = plural or f"{singular}s"
    word = singular if count == 1 else many
    return f"{count} {word}"
