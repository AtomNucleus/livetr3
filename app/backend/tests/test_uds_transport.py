from __future__ import annotations

import asyncio
import json
import struct

from transport import FRAME_BINARY, FRAME_TEXT, HEADER, UnixSocketTransport


def frame(frame_type: int, payload: bytes) -> bytes:
    return HEADER.pack(frame_type, len(payload)) + payload


def test_header_codec_round_trip() -> None:
    encoded = frame(FRAME_TEXT, b'{"type":"start"}')
    frame_type, length = HEADER.unpack(encoded[: HEADER.size])
    assert frame_type == FRAME_TEXT
    assert length == len(b'{"type":"start"}')
    assert encoded[HEADER.size :] == b'{"type":"start"}'


def test_unix_socket_transport_receive_text_and_binary() -> None:
    async def run() -> None:
        reader = asyncio.StreamReader()
        writer = _MemoryWriter()
        transport = UnixSocketTransport(reader, writer, {"session": "abc"})
        reader.feed_data(frame(FRAME_TEXT, b'{"type":"start"}'))
        reader.feed_data(frame(FRAME_BINARY, b"\x00\x01"))
        assert await transport.receive() == {"text": '{"type":"start"}'}
        assert await transport.receive() == {"bytes": b"\x00\x01"}
        await transport.send_json({"type": "status", "state": "ready"})
        assert writer.payloads
        out_type, out_length = HEADER.unpack(writer.payloads[0][: HEADER.size])
        assert out_type == FRAME_TEXT
        payload = writer.payloads[0][HEADER.size :]
        assert out_length == len(payload)
        assert json.loads(payload) == {"type": "status", "state": "ready"}

    asyncio.run(run())


class _MemoryWriter:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.payloads.append(data)

    async def drain(self) -> None:
        return
