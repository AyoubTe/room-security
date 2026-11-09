"""Push notifications: delivery, and a clear reason when nothing is delivered."""

import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from sentinel.api import build_app
from sentinel.main import Sentinel
from sentinel.notify import Notifier
from sentinel.store import Store
from test_service import AUTH, FakeZ2M, make_cfg

TOKEN = "ExponentPushToken[abc123]"


async def fake_expo(tickets):
    async def handler(request):
        await request.json()
        return web.json_response({"data": tickets})

    app = web.Application()
    app.router.add_post("/send", handler)
    server = TestServer(app)
    await server.start_server()
    return server


def test_delivery_and_the_reason_when_it_fails(tmp_path):
    async def run():
        store = Store(tmp_path / "s.db")
        server = await fake_expo([{"status": "ok"}])
        n = Notifier(store, url=str(server.make_url("/send")))
        try:
            assert await n.send("info", "t", "b") == 0 and n.last_error == "no_devices"      # nothing registered yet

            store.add_token(TOKEN)
            assert await n.send("alarm", "t", "b") == 1 and n.last_error is None
            assert n.sent[-1]["channelId"] == "intrusion" and n.sent[-1]["priority"] == "high"
        finally:
            await server.close()

        bad = await fake_expo([{"status": "error", "message": "no key", "details": {"error": "InvalidCredentials"}}])
        n2 = Notifier(store, url=str(bad.make_url("/send")))
        try:
            assert await n2.send("info", "t", "b") == 0 and n2.last_error == "InvalidCredentials"
        finally:
            await bad.close()

        gone = await fake_expo([{"status": "error", "details": {"error": "DeviceNotRegistered"}}])
        n3 = Notifier(store, url=str(gone.make_url("/send")))
        try:
            assert await n3.send("info", "t", "b") == 0
            assert store.tokens() == []                                                     # the dead token is dropped
        finally:
            await gone.close()

        down = Notifier(store, url="http://127.0.0.1:9/send")                               # nothing listens there
        store.add_token(TOKEN)
        assert await down.send("info", "t", "b") == 0 and down.last_error == "pi_offline"
        store.db.close()

    asyncio.run(run())


def test_test_push_endpoint_explains_itself(tmp_path):
    async def run():
        S = Sentinel(make_cfg(tmp_path), asyncio.get_running_loop(), mqtt=False)
        S.z2m = FakeZ2M()
        client = TestClient(TestServer(build_app(S)))
        await client.start_server()
        try:
            r = await (await client.post("/api/test-push", headers=AUTH)).json()
            assert r == {"ok": False, "delivered": 0, "devices": 0, "error": "no_devices"}

            S.store.add_token(TOKEN)
            expo = await fake_expo([{"status": "ok"}])
            S.notifier.url = str(expo.make_url("/send"))
            r = await (await client.post("/api/test-push", headers=AUTH)).json()
            assert r == {"ok": True, "delivered": 1, "devices": 1}
            await expo.close()
        finally:
            await client.close()
            S.store.db.close()

    asyncio.run(run())
