"""Bound newline framing before SDK decoding; this module does not parse JSON-RPC."""

import sys

import anyio

MAX_FRAME_BYTES = 65536


class BoundedLines:
    def __init__(self, reader=None):
        self.reader = reader if reader is not None else sys.stdin.buffer

    def __aiter__(self):
        return self

    async def __anext__(self):
        # Idle between messages is legal. After the first byte, bound both the
        # incomplete-frame time and allocation, even without a terminating LF.
        first = await anyio.to_thread.run_sync(self.reader.read, 1, abandon_on_cancel=True)
        if not first:
            raise StopAsyncIteration
        if first == b"\n":
            return "\n"
        with anyio.fail_after(5):
            rest = await anyio.to_thread.run_sync(
                self.reader.readline, MAX_FRAME_BYTES, abandon_on_cancel=True
            )
        frame = first + rest
        if len(frame) > MAX_FRAME_BYTES or not frame.endswith(b"\n"):
            raise ValueError("Invalid or oversized MCP input frame")
        return frame.decode("utf-8", errors="strict")
