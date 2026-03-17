from __future__ import annotations

from memory_service.domain.ids import build_group_id, build_message_id


def test_build_group_id() -> None:
    assert build_group_id(user_id="u1", platform="local", external_id="x") == "u1:local:x"


def test_build_message_id() -> None:
    assert (
        build_message_id(user_id="u1", platform="local", external_id="x", seq=7)
        == "u1:local:x:seg:7"
    )
