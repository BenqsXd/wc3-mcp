"""Little-endian binary reading/writing shared by the map file codecs."""
import struct


class FormatError(ValueError):
    pass


class Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = bytes(data), 0

    def _take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise FormatError(f"unexpected end of data at offset {self.pos} (need {n} bytes)")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def i32(self) -> int:
        return struct.unpack("<i", self._take(4))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self._take(4))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self._take(4))[0]

    def u8(self) -> int:
        return self._take(1)[0]

    def raw(self, n: int) -> bytes:
        return self._take(n)

    def cstr(self) -> str:
        end = self.data.find(b"\0", self.pos)
        if end < 0:
            raise FormatError(f"unterminated string at offset {self.pos}")
        value = self.data[self.pos:end].decode("utf-8", "surrogateescape")
        self.pos = end + 1
        return value

    def count(self, item_size: int = 1) -> int:
        """An i32 element count, rejected if its items could not fit in the remaining data."""
        n = self.i32()
        if n < 0 or n * item_size > len(self.data) - self.pos:
            raise FormatError(f"implausible count {n} at offset {self.pos - 4}")
        return n

    def peek_u8(self) -> int:
        return self.data[self.pos] if self.pos < len(self.data) else -1

    def rest(self) -> bytes:
        chunk = self.data[self.pos:]
        self.pos = len(self.data)
        return chunk


class Writer:
    def __init__(self):
        self.buf = bytearray()

    def i32(self, v: int) -> None:
        self.buf += struct.pack("<i", v)

    def u32(self, v: int) -> None:
        self.buf += struct.pack("<I", v)

    def f32(self, v: float) -> None:
        self.buf += struct.pack("<f", v)

    def u8(self, v: int) -> None:
        self.buf.append(v)

    def raw(self, b: bytes) -> None:
        self.buf += b

    def cstr(self, s: str) -> None:
        self.buf += s.encode("utf-8", "surrogateescape") + b"\0"

    def getvalue(self) -> bytes:
        return bytes(self.buf)
