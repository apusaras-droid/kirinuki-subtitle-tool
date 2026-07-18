from backend.app.services import merge_range_transcription_subtitles, offset_subtitle_timing_candidates


def subtitle(subtitle_id: str, start: float, end: float, text: str, **extra):
    return {
        "id": subtitle_id,
        "range_relative_start_sec": start,
        "range_relative_end_sec": end,
        "output_start_sec": start,
        "output_end_sec": end,
        "text": text,
        **extra,
    }


def test_timing_replacement_keeps_outside_and_inherits_caption_metadata():
    existing = [
        subtitle("before", 1.0, 2.0, "前"),
        subtitle("target", 5.0, 7.0, "誤字幕", frame_preset_id="frame_manga_round"),
        subtitle("after", 9.0, 10.0, "後"),
    ]
    replacement = [subtitle("generated", 5.2, 6.8, "正しい字幕")]

    result = merge_range_transcription_subtitles(existing, replacement, 5.0, 7.0, 100.0, "text_and_timing")

    assert result["affected_subtitle_ids"] == ["target"]
    assert [item["text"] for item in result["merged_subtitles"]] == ["前", "正しい字幕", "後"]
    replaced = result["merged_subtitles"][1]
    assert replaced["id"] == "target"
    assert replaced["frame_preset_id"] == "frame_manga_round"
    assert replaced["range_relative_start_sec"] == 5.2


def test_text_only_replacement_preserves_existing_timestamps():
    existing = [subtitle("target", 5.0, 7.0, "誤字幕")]
    replacement = [
        subtitle("generated_1", 5.1, 5.8, "正しい"),
        subtitle("generated_2", 5.8, 6.9, "字幕"),
    ]

    result = merge_range_transcription_subtitles(existing, replacement, 5.0, 7.0, 0.0, "text_only")

    updated = result["merged_subtitles"][0]
    assert updated["id"] == "target"
    assert updated["text"] == "正しい\n字幕"
    assert updated["output_start_sec"] == 5.0
    assert updated["output_end_sec"] == 7.0


def test_timing_replacement_can_remove_hallucinated_range_when_no_speech_is_found():
    existing = [
        subtitle("hallucination", 5.0, 7.0, "繰り返し誤字幕"),
        subtitle("after", 9.0, 10.0, "実際の発話"),
    ]

    result = merge_range_transcription_subtitles(existing, [], 5.0, 7.0, 0.0, "text_and_timing")

    assert result["affected_subtitle_ids"] == ["hallucination"]
    assert [item["id"] for item in result["merged_subtitles"]] == ["after"]


def test_range_candidate_times_are_offset_from_analysis_clip_to_source_range():
    local = {
        "whisper_start_sec": 0.62,
        "whisper_end_sec": 5.7,
        "vad_start_sec": 3.9,
        "vad_end_sec": 5.9,
        "auto_start_sec": 0.52,
        "auto_end_sec": 6.1,
        "selected_start_sec": 0.52,
        "selected_end_sec": 6.1,
    }

    shifted = offset_subtitle_timing_candidates(local, 32.5, 34.0, 38.6)

    assert shifted["whisper_start_sec"] == 33.12
    assert shifted["whisper_end_sec"] == 38.2
    assert shifted["vad_start_sec"] == 36.4
    assert shifted["vad_end_sec"] == 38.4
    assert shifted["auto_start_sec"] == 34.0
    assert shifted["auto_end_sec"] == 38.6
    assert shifted["selected_start_sec"] == 34.0
    assert shifted["selected_end_sec"] == 38.6
