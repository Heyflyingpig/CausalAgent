from __future__ import annotations


def is_missing_checkpoint_foreign_key_error(exc: BaseException) -> bool:
    """Return True for MySQL 1216/1452 child-row foreign key failures."""
    errno = getattr(exc, "errno", None)
    if errno in {1216, 1452}:
        return True

    message = str(exc).lower()
    return (
        "foreign key constraint fails" in message
        or "cannot add or update a child row" in message
    )
