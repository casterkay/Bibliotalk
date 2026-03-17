from __future__ import annotations

import json

from memory_service.adapters.youtube_transcript import (
    _select_caption,
    parse_json3,
    parse_ttml,
    parse_webvtt,
)


def test_parse_webvtt_strips_tags_and_collapses_ws() -> None:
    vtt = """WEBVTT

00:00.000 --> 00:01.500
Hello <b>world</b>!

00:01.500 --> 00:02.000
Line 1
Line 2
"""
    lines = parse_webvtt(vtt)
    assert [(l.text, l.start_ms, l.end_ms) for l in lines] == [
        ("Hello world!", 0, 1500),
        ("Line 1 Line 2", 1500, 2000),
    ]


def test_parse_ttml_extracts_text_and_times() -> None:
    ttml = """<?xml version="1.0" encoding="utf-8"?>
<tt xmlns="http://www.w3.org/ns/ttml">
  <body>
    <div>
      <p begin="00:00:01.000" end="00:00:02.500">Hello &amp; bye</p>
      <p begin="2.5s" end="3.0s">Later</p>
    </div>
  </body>
</tt>
"""
    lines = parse_ttml(ttml)
    assert [(l.text, l.start_ms, l.end_ms) for l in lines] == [
        ("Hello & bye", 1000, 2500),
        ("Later", 2500, 3000),
    ]


def test_parse_json3_builds_lines_from_events() -> None:
    payload = {
        "events": [
            {
                "tStartMs": 0,
                "dDurationMs": 1200,
                "segs": [{"utf8": "Hello "}, {"utf8": "world"}],
            },
            {"tStartMs": 1500, "dDurationMs": 500, "segs": [{"utf8": "\n"}]},
        ]
    }
    lines = parse_json3(json.dumps(payload))
    assert [(l.text, l.start_ms, l.end_ms) for l in lines] == [("Hello world", 0, 1200)]


def test_select_caption_prefers_manual_subtitles_then_auto() -> None:
    selection = _select_caption(
        subtitles={"en": [{"ext": "vtt", "url": "https://example.com/manual.vtt"}]},
        automatic_captions={"en": [{"ext": "vtt", "url": "https://example.com/auto.vtt"}]},
        preferred_languages=["en"],
        allow_auto=True,
    )
    assert selection is not None
    assert selection.is_auto is False
    assert selection.url.endswith("manual.vtt")

    selection = _select_caption(
        subtitles={},
        automatic_captions={"en": [{"ext": "vtt", "url": "https://example.com/auto.vtt"}]},
        preferred_languages=["en"],
        allow_auto=True,
    )
    assert selection is not None
    assert selection.is_auto is True
