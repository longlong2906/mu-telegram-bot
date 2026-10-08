class BotError(Exception):
    """A safe, user-facing error that contains no credentials or response bodies."""


class StateError(BotError):
    """Persistent state could not be read or written safely."""
