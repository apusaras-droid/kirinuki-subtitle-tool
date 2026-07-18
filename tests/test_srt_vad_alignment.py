from backend.app.srt import apply_vad_subtitle_corrections, filter_repetitive_hallucinations, normalize_subtitle_durations


def _subtitle(subtitle_id: str, start: float, end: float, text: str, *, raw_end: float | None = None) -> dict:
    return {
        "id": subtitle_id,
        "enabled": True,
        "whisper_start_sec": start,
        "whisper_end_sec": end if raw_end is None else raw_end,
        "source_start_sec": start,
        "source_end_sec": end,
        "output_start_sec": start,
        "output_end_sec": end,
        "text": text,
    }


def test_vad_alignment_preserves_subtitle_units_when_one_vad_interval_overlaps_many() -> None:
    subtitles = [
        _subtitle("sub_0001", 10.0, 12.0, "一つ目"),
        _subtitle("sub_0002", 12.1, 14.1, "二つ目"),
        _subtitle("sub_0003", 14.2, 16.2, "三つ目"),
    ]
    vad = [{"speech_start_sec": 9.9, "speech_end_sec": 16.3}]

    result = apply_vad_subtitle_corrections(
        subtitles,
        vad,
        pre_margin_sec=0.0,
        post_margin_sec=0.0,
    )

    assert [item["id"] for item in result] == ["sub_0001", "sub_0002", "sub_0003"]
    assert [item["text"] for item in result] == ["一つ目", "二つ目", "三つ目"]
    assert all(len(item["whisper_segments"]) == 1 for item in result)


def test_vad_alignment_matches_normalized_timing_instead_of_long_raw_whisper_segment() -> None:
    subtitles = [_subtitle("sub_0001", 2.82, 4.82, "おやすみなさい", raw_end=29.98)]
    vad = [{"speech_start_sec": 2.64, "speech_end_sec": 29.77}]

    result = apply_vad_subtitle_corrections(
        subtitles,
        vad,
        pre_margin_sec=0.0,
        post_margin_sec=0.0,
    )

    assert len(result) == 1
    assert result[0]["whisper_end_sec"] == 29.98
    assert result[0]["normalized_end_sec"] == 4.82
    assert result[0]["output_end_sec"] == 4.82


def test_vad_alignment_applies_only_nearby_boundaries_and_margins() -> None:
    subtitles = [_subtitle("sub_0001", 10.0, 12.0, "テスト")]
    vad = [{"speech_start_sec": 9.7, "speech_end_sec": 12.4}]

    result = apply_vad_subtitle_corrections(
        subtitles,
        vad,
        pre_margin_sec=0.1,
        post_margin_sec=0.2,
    )

    assert result[0]["output_start_sec"] == 9.6
    assert result[0]["output_end_sec"] == 12.6
    assert result[0]["corrected_by_vad"] is True


def test_vad_alignment_falls_back_to_normalized_timing_without_match() -> None:
    subtitles = [_subtitle("sub_0001", 10.0, 12.0, "テスト")]
    vad = [{"speech_start_sec": 20.0, "speech_end_sec": 21.0}]

    result = apply_vad_subtitle_corrections(
        subtitles,
        vad,
        pre_margin_sec=0.0,
        post_margin_sec=0.0,
    )

    assert result[0]["output_start_sec"] == 10.0
    assert result[0]["output_end_sec"] == 12.0
    assert result[0]["vad_interval_index"] is None
    assert result[0]["corrected_by_vad"] is False


def test_repetitive_hallucinations_without_vad_support_are_removed() -> None:
    phrase = "この映像は、東京都の中心のアイデアによって作られました。"
    subtitles = [
        _subtitle("sub_0001", 0.0, 4.5, phrase),
        _subtitle("sub_0002", 10.0, 14.5, phrase),
        _subtitle("sub_0003", 15.0, 19.5, phrase),
        _subtitle("sub_0004", 20.0, 24.5, phrase),
        _subtitle("sub_0005", 34.0, 36.0, "本当の台詞"),
    ]
    vad = [
        {"speech_start_sec": 2.8, "speech_end_sec": 3.3},
        {"speech_start_sec": 34.0, "speech_end_sec": 36.0},
    ]

    kept, discarded = filter_repetitive_hallucinations(subtitles, vad)

    assert [item["id"] for item in kept] == ["sub_0005"]
    assert len(discarded) == 4
    assert all(item["reason"] == "repeated_text_without_vad_support" for item in discarded)


def test_repeated_dialogue_with_strong_vad_support_is_kept() -> None:
    subtitles = [
        _subtitle("sub_0001", 0.0, 1.0, "行け、行け"),
        _subtitle("sub_0002", 2.0, 3.0, "行け、行け"),
        _subtitle("sub_0003", 4.0, 5.0, "行け、行け"),
    ]
    vad = [
        {"speech_start_sec": 0.0, "speech_end_sec": 1.0},
        {"speech_start_sec": 2.0, "speech_end_sec": 3.0},
        {"speech_start_sec": 4.0, "speech_end_sec": 5.0},
    ]

    kept, discarded = filter_repetitive_hallucinations(subtitles, vad)

    assert len(kept) == 3
    assert discarded == []


def test_duration_normalization_never_truncates_recognized_speech() -> None:
    subtitles = [_subtitle("sub_0001", 55.0, 63.0, "長い台詞です")]

    result = normalize_subtitle_durations(subtitles)

    assert result[0]["output_start_sec"] == 55.0
    assert result[0]["output_end_sec"] == 63.0
    assert result[0]["whisper_end_sec"] == 63.0
    assert result[0]["selected_end_sec"] == 63.0


def test_vad_alignment_retains_independent_timing_candidates() -> None:
    subtitles = [_subtitle("sub_0001", 10.0, 12.0, "テスト")]
    vad = [{"speech_start_sec": 9.7, "speech_end_sec": 12.4}]

    result = apply_vad_subtitle_corrections(subtitles, vad, pre_margin_sec=0.1, post_margin_sec=0.2)

    item = result[0]
    assert item["whisper_start_sec"] == 10.0
    assert item["whisper_end_sec"] == 12.0
    assert item["vad_start_sec"] == 9.7
    assert item["vad_end_sec"] == 12.4
    assert item["auto_start_sec"] == 9.6
    assert item["auto_end_sec"] == 12.6
    assert item["start_timing_source"] == "auto"
    assert item["end_timing_source"] == "auto"
