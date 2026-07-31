"""Typed errors for the telemetry pipeline.

Every failure mode that a corrupt file or a missing channel can produce gets its
own type. The reason is the graceful-degradation requirement: the UI must be
able to disable one affected feature and keep running, which it can only do if
it can tell "this channel is not recorded" apart from "this file is unreadable".
A bare ValueError would force the caller to either catch everything or crash.
"""

from __future__ import annotations


class TelemetryError(Exception):
    """Base class for every error raised by this application."""


class SessionFileError(TelemetryError):
    """The session file cannot be opened, or is not a usable DuckDB database."""


class SchemaError(TelemetryError):
    """The file opened, but its structure is not what the reader expects.

    Raised for a missing catalog table (`channelsList`, `eventsList`,
    `metadata`) or a channel table whose columns match none of the four known
    layouts.
    """


class ChannelNotFoundError(TelemetryError):
    """A requested channel is not recorded in this session file.

    This is expected, not exceptional: which channels the game writes varies
    with car and session type. Callers are meant to catch this and disable the
    dependent feature with a visible message, never to let it reach the user as
    a crash.
    """

    def __init__(self, channel_name: str) -> None:
        super().__init__(f"Channel not present in session file: {channel_name!r}")
        self.channel_name = channel_name


class TimeBaseError(TelemetryError):
    """The implicit time base could not be built or validated.

    Typically a channel declaring a zero, negative or missing sample frequency,
    which would turn `t[i] = i / frequency` into a division by zero.
    """


class SessionNameError(TelemetryError):
    """The session file name does not follow the game's naming convention."""
