from __future__ import annotations


def build_youtube_group_id(*, user_id: str, video_id: str) -> str:
    return f"{user_id}:youtube:{video_id}"


def build_youtube_message_id(*, user_id: str, video_id: str, seq: int) -> str:
    return f"{user_id}:youtube:{video_id}:seg:{seq}"


def build_group_id(*, user_id: str, platform: str, external_id: str) -> str:
    if platform == "youtube":
        return build_youtube_group_id(user_id=user_id, video_id=external_id)
    return f"{user_id}:{platform}:{external_id}"


def build_message_id(*, user_id: str, platform: str, external_id: str, seq: int) -> str:
    if platform == "youtube":
        return build_youtube_message_id(user_id=user_id, video_id=external_id, seq=seq)
    return f"{user_id}:{platform}:{external_id}:seg:{seq}"
