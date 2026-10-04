import asyncio
import sys
import types

from allycompanion import deckyfix


def test_socket_read_waits_at_eof_instead_of_spinning(monkeypatch):
    class UnixSocket:
        async def _read_single_line(self, reader):
            return "line"

    module = types.ModuleType("localplatform.localsocket")
    module.UnixSocket = UnixSocket
    monkeypatch.setitem(sys.modules, "localplatform.localsocket", module)
    assert deckyfix.park_reader_at_eof() and deckyfix.park_reader_at_eof()

    async def scenario():
        open_reader = asyncio.StreamReader()
        open_reader.feed_data(b"x\n")
        assert await UnixSocket()._read_single_line(open_reader) == "line"
        closed = asyncio.StreamReader()
        closed.feed_eof()
        read = asyncio.ensure_future(UnixSocket()._read_single_line(closed))
        await asyncio.sleep(0.05)
        assert not read.done()
        read.cancel()

    asyncio.run(scenario())


def test_without_decky_nothing_is_patched(monkeypatch):
    for name in deckyfix.MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    assert not deckyfix.park_reader_at_eof()
