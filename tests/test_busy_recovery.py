"""Regression tests for busy-state recovery (no DB/FastAPI needed).

Run:  python tests/test_busy_recovery.py

Covers the bug where a call that ended abnormally (e.g. a network drop where
the client never reached /end) kept a number permanently "busy", so the next
attempt got HTTP 409 line_busy.

The call-registry functions are loaded straight from voipcall.py and run
against a fake LiveKit API, so no server or credentials are required.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import pathlib
import sys
import types

SRC = pathlib.Path(__file__).resolve().parents[1] / "apis" / "call" / "voipcall.py"

WANTED_CONSTANTS = (
    "ROOM_CHECK_GRACE_SECONDS",
    "BOT_IDENTITY_PREFIX",
)

WANTED_FUNCTIONS = (
    "_room_has_callers",
    "_delete_room",
    "drop_call",
    "find_busy_room",
)

CALLER = "+2347000000001"
CALLEE = "+2347000000002"


class Harness:
    """Loads the functions with fakes that we can steer from the tests."""

    def __init__(self) -> None:
        self.presence: dict[str, list[str]] = {}
        self.deleted: list[str] = []
        self.stopped: list[str] = []
        self.api_should_fail = False

        source = SRC.read_text(encoding="utf-8")
        self.source = source
        tree = ast.parse(source)

        namespace: dict = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                name = getattr(node.targets[0], "id", "")
                if name in WANTED_CONSTANTS:
                    namespace[name] = ast.literal_eval(node.value)

        harness = self

        class _Participant:
            def __init__(self, identity: str) -> None:
                self.identity = identity

        class _ListResponse:
            def __init__(self, participants) -> None:
                self.participants = participants

        class _RoomService:
            async def list_participants(self, request):
                if harness.api_should_fail:
                    raise RuntimeError("livekit unreachable")
                return _ListResponse(
                    [
                        _Participant(i)
                        for i in harness.presence.get(request.room, [])
                    ]
                )

            async def delete_room(self, request):
                harness.deleted.append(request.room)
                harness.presence.pop(request.room, None)

        class _LiveKitAPI:
            def __init__(self, *a, **k) -> None:
                self.room = _RoomService()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        async def fake_stop_transcription(room: str) -> None:
            harness.stopped.append(room)

        namespace.update(
            {
                "lk": types.SimpleNamespace(
                    LiveKitAPI=_LiveKitAPI,
                    ListParticipantsRequest=lambda room: types.SimpleNamespace(
                        room=room
                    ),
                    DeleteRoomRequest=lambda room: types.SimpleNamespace(room=room),
                ),
                "log": logging.getLogger("busy-test"),
                "time": __import__("time"),
                "calls": {},
                "stop_transcription": fake_stop_transcription,
            }
        )

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in WANTED_FUNCTIONS:
                    exec(ast.get_source_segment(source, node), namespace)

        self.ns = namespace
        self.calls: dict = namespace["calls"]
        self.time = namespace["time"]

    # ---- helpers -------------------------------------------------------- #

    def register(self, room: str, age_seconds: float) -> None:
        self.calls[room] = {
            "caller": CALLER,
            "callee": CALLEE,
            "created_at": self.time.monotonic() - age_seconds,
        }

    async def busy(self, number: str):
        return await self.ns["find_busy_room"](number)

    async def drop(self, room: str) -> None:
        await self.ns["drop_call"](room)


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"{'PASS' if condition else 'FAIL'}: {label}{f' -> {detail}' if detail else ''}")
    return condition


async def main() -> int:
    ok = True

    print("\n[1] a real live call still blocks a second call")
    h = Harness()
    h.register("call-live", age_seconds=30)
    h.presence["call-live"] = [CALLER, CALLEE]
    ok &= check("live room -> busy", await h.busy(CALLEE) == "call-live")
    ok &= check("registration kept", "call-live" in h.calls)

    print("\n[2] the reported bug: dead room releases the number")
    h = Harness()
    h.register("call-dead", age_seconds=30)
    h.presence["call-dead"] = []  # everyone gone after a network drop
    ok &= check("dead room -> not busy", await h.busy(CALLEE) is None)
    ok &= check("registration removed", "call-dead" not in h.calls)
    ok &= check("stale transcription stopped", h.stopped == ["call-dead"], str(h.stopped))
    ok &= check("room force-deleted", h.deleted == ["call-dead"], str(h.deleted))

    print("\n[3] only the bot left -> still treated as dead")
    h = Harness()
    h.register("call-bot", age_seconds=30)
    h.presence["call-bot"] = [f"{h.ns['BOT_IDENTITY_PREFIX']}call-bot"]
    ok &= check("bot-only room -> not busy", await h.busy(CALLER) is None)
    ok &= check("registration removed", "call-bot" not in h.calls)

    print("\n[4] a ringing call lasts as long as the caller is still in the room")
    h = Harness()
    h.register("call-ring", age_seconds=600)  # 10 minutes, no time limit applies
    h.presence["call-ring"] = [CALLER]  # caller still ringing, callee not in yet
    ok &= check("still ringing -> busy", await h.busy(CALLEE) == "call-ring")
    ok &= check("nothing deleted", h.deleted == [])

    print("\n[5] a ringing call is released once the caller leaves")
    h = Harness()
    h.register("call-gone", age_seconds=600)
    h.presence["call-gone"] = []  # caller's client left / dropped off
    ok &= check("caller gone -> not busy", await h.busy(CALLEE) is None)
    ok &= check("registration removed", "call-gone" not in h.calls)
    ok &= check("room force-deleted", h.deleted == ["call-gone"])

    print("\n[6] a young call is NOT released just because the room is empty")
    h = Harness()
    h.register("call-young", age_seconds=1)
    h.presence["call-young"] = []  # caller has not joined yet
    ok &= check("within grace -> still busy", await h.busy(CALLEE) == "call-young")
    ok &= check("nothing deleted", h.deleted == [])

    print("\n[7] LiveKit API outage fails safe (never falsely frees a number)")
    h = Harness()
    h.register("call-outage", age_seconds=30)
    h.api_should_fail = True
    ok &= check("API error -> still busy", await h.busy(CALLEE) == "call-outage")
    ok &= check("nothing deleted", h.deleted == [])

    print("\n[8] explicit end/decline also force-deletes the room")
    h = Harness()
    h.register("call-end", age_seconds=5)
    h.presence["call-end"] = [CALLER, CALLEE]
    await h.drop("call-end")
    ok &= check("registration removed", "call-end" not in h.calls)
    ok &= check("room force-deleted", h.deleted == ["call-end"])

    print("\n[9] an unrelated call is left alone")
    h = Harness()
    h.calls["call-other"] = {
        "caller": "+2347000000009",
        "callee": "+2347000000010",
        "created_at": h.time.monotonic() - 30,
    }
    h.presence["call-other"] = ["+2347000000009"]
    ok &= check("unrelated number not busy", await h.busy(CALLEE) is None)
    ok &= check("unrelated call untouched", "call-other" in h.calls)

    print()
    if ok:
        print("ALL TESTS PASSED")
        return 0
    print("SOME TESTS FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
