from __future__ import annotations

from copy import deepcopy


DEFAULT_SETTINGS = {
    "silence_threshold_db": -35.0,
    "min_silence_duration": 0.7,
    "pre_speech_padding": 1.0,
    "post_speech_padding": 1.5,
    "min_keep_segment_duration": 1.0,
    "merge_gap_duration": 0.5,
    "detection_mode": "silencedetect",
    "pre_margin_sec": 0.3,
    "post_margin_sec": 0.5,
    "min_speech_duration_sec": 0.2,
    "min_silence_duration_sec": 0.5,
    "merge_silence_gap_sec": 0.5,
    "subtitle_font_name": "Meiryo",
    "subtitle_font_size": 42,
    "subtitle_outline_width": 2,
}


def invert_silences(silences: list[dict], duration: float) -> list[tuple[float, float]]:
    cursor = 0.0
    speech: list[tuple[float, float]] = []
    for silence in sorted(silences, key=lambda x: float(x["start_sec"])):
        start = max(0.0, float(silence["start_sec"]))
        end = min(duration, float(silence["end_sec"]))
        if start > cursor:
            speech.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        speech.append((cursor, duration))
    return [(s, e) for s, e in speech if e > s]


def pad_and_merge_segments(
    speech_ranges: list[tuple[float, float]],
    duration: float,
    pre_padding: float,
    post_padding: float,
    merge_gap: float,
    min_keep_duration: float,
) -> list[tuple[float, float]]:
    padded = [
        (max(0.0, start - pre_padding), min(duration, end + post_padding))
        for start, end in speech_ranges
        if end > start
    ]
    if not padded:
        return [(0.0, duration)] if duration > 0 else []
    padded.sort()
    merged: list[list[float]] = [[padded[0][0], padded[0][1]]]
    for start, end in padded[1:]:
        prev = merged[-1]
        if start - prev[1] <= merge_gap:
            prev[1] = max(prev[1], end)
        else:
            merged.append([start, end])
    result = [(s, e) for s, e in merged if e - s >= min_keep_duration]
    return result or [(0.0, duration)]


def _setting_float(settings: dict, key: str, fallback: float) -> float:
    value = settings.get(key, fallback)
    if value is None:
        return float(fallback)
    return float(value)


def _clamp_interval(start: float, end: float, duration: float) -> tuple[float, float] | None:
    start = max(0.0, min(duration, float(start)))
    end = max(0.0, min(duration, float(end)))
    if end <= start:
        return None
    return (round(start, 3), round(end, 3))


def _normalize_intervals(intervals: list[dict], duration: float, range_start: float = 0.0) -> list[tuple[float, float]]:
    normalized: list[tuple[float, float]] = []
    for item in intervals or []:
        start = item.get("src_start")
        end = item.get("src_end")
        if start is None or end is None:
            start = item.get("start_sec", item.get("start", item.get("source_start_sec", 0.0)))
            end = item.get("end_sec", item.get("end", item.get("source_end_sec", start)))
            start = float(start) - range_start
            end = float(end) - range_start
        interval = _clamp_interval(start, end, duration)
        if interval is not None:
            normalized.append(interval)
    return _merge_intervals(normalized)


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged: list[list[float]] = [[ordered[0][0], ordered[0][1]]]
    for start, end in ordered[1:]:
        prev = merged[-1]
        if start <= prev[1]:
            prev[1] = max(prev[1], end)
        else:
            merged.append([start, end])
    return [(round(start, 3), round(end, 3)) for start, end in merged]


def _subtract_intervals(base: list[tuple[float, float]], cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not base or not cuts:
        return list(base)
    cuts = _merge_intervals(cuts)
    result: list[tuple[float, float]] = []
    for start, end in base:
        cursor = start
        for cut_start, cut_end in cuts:
            if cut_end <= cursor:
                continue
            if cut_start >= end:
                break
            if cut_start > cursor:
                result.append((round(cursor, 3), round(min(cut_start, end), 3)))
            cursor = max(cursor, cut_end)
            if cursor >= end:
                break
        if cursor < end:
            result.append((round(cursor, 3), round(end, 3)))
    return [(s, e) for s, e in result if e > s]


def _subtract_many_intervals(base: list[tuple[float, float]], removals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result = list(base)
    for removal in removals:
        result = _subtract_intervals(result, [removal])
    return _merge_intervals(result)


def assign_speaker_labels_to_subtitles(
    subtitles: list[dict],
    speaker_segments: list[dict],
    *,
    speaker_roster: list[dict] | None = None,
    max_gap_sec: float = 0.75,
) -> list[dict]:
    if not subtitles:
        return []
    roster_map = {str(item.get("speaker_id", "")).strip(): str(item.get("display_name", item.get("speaker_id", ""))).strip() for item in (speaker_roster or []) if item.get("speaker_id")}
    ordered_segments = sorted(
        [
            {
                "start_sec": float(seg.get("start_sec", 0.0)),
                "end_sec": float(seg.get("end_sec", 0.0)),
                "speaker_id": str(seg.get("speaker_id", seg.get("speaker_label", ""))).strip(),
                "speaker_label": str(seg.get("speaker_label", seg.get("speaker_id", ""))).strip(),
            }
            for seg in speaker_segments
            if float(seg.get("end_sec", 0.0)) > float(seg.get("start_sec", 0.0))
        ],
        key=lambda item: (item["start_sec"], item["end_sec"]),
    )
    if not ordered_segments:
        return [dict(sub) for sub in subtitles]
    assigned: list[dict] = []
    for sub in subtitles:
        item = dict(sub)
        original_start = float(item.get("original_start_sec", item.get("source_start_sec", item.get("whisper_start_sec", item.get("output_start_sec", 0.0)))))
        original_end = float(item.get("original_end_sec", item.get("source_end_sec", item.get("whisper_end_sec", item.get("output_end_sec", original_start)))))
        if original_end <= original_start or (item.get("speaker_label") and item.get("speaker_id")):
            assigned.append(item)
            continue
        best_id = None
        best_label = None
        best_overlap = 0.0
        best_gap = None
        for seg in ordered_segments:
            overlap = min(original_end, seg["end_sec"]) - max(original_start, seg["start_sec"])
            if overlap > best_overlap:
                best_overlap = overlap
                best_id = seg["speaker_id"]
                best_label = seg["speaker_label"] or roster_map.get(seg["speaker_id"], seg["speaker_id"])
            elif overlap <= 0:
                gap = max(seg["start_sec"] - original_end, original_start - seg["end_sec"])
                if gap <= max_gap_sec and (best_gap is None or gap < best_gap):
                    best_gap = gap
                    best_id = seg["speaker_id"]
                    best_label = seg["speaker_label"] or roster_map.get(seg["speaker_id"], seg["speaker_id"])
        if best_id:
            item["speaker_id"] = best_id
            item["speaker_label"] = roster_map.get(best_id, best_label or best_id)
            item["speaker_confidence"] = round(max(0.0, best_overlap) / max(0.001, original_end - original_start), 3)
        assigned.append(item)
    return assigned


def build_speaker_roster(subtitles: list[dict]) -> list[dict]:
    roster: list[dict] = []
    seen: set[str] = set()
    for sub in subtitles:
        speaker_id = str(sub.get("speaker_id", "")).strip()
        if not speaker_id or speaker_id in seen:
            continue
        seen.add(speaker_id)
        roster.append(
            {
                "speaker_id": speaker_id,
                "display_name": str(sub.get("speaker_label", speaker_id)).strip() or speaker_id,
            }
        )
    return roster


def output_time_for_source(relative_sec: float, segments: list[dict]) -> float | None:
    elapsed = 0.0
    for seg in segments:
        if not seg.get("enabled", True):
            continue
        start = float(seg["range_relative_start_sec"])
        end = float(seg["range_relative_end_sec"])
        if start <= relative_sec <= end:
            return elapsed + (relative_sec - start)
        elapsed += end - start
    return None


def source_time_to_output(relative_sec: float, segments: list[dict]) -> float | None:
    return output_time_for_source(relative_sec, segments)


def _subtitle_relative_time(item: dict, start_keys: tuple[str, ...], source_range_start: float, source_range_end: float | None) -> float:
    for key in start_keys:
        if key not in item or item.get(key) is None:
            continue
        value = float(item.get(key))
        if key.startswith("range_relative") or key in {"start_sec", "end_sec", "output_start_sec", "output_end_sec", "corrected_start_sec", "corrected_end_sec"}:
            return value
        if key.startswith("source_") or key.startswith("original_"):
            if source_range_end is not None and source_range_start <= value <= source_range_end:
                return value - source_range_start
            return value
        return value
    return 0.0


def map_subtitles_to_output(subtitles: list[dict], segments: list[dict], source_range_start: float, source_range_end: float | None = None) -> list[dict]:
    mapped: list[dict] = []
    for idx, sub in enumerate(subtitles, start=1):
        item = deepcopy(sub)
        rel_start = _subtitle_relative_time(
            item,
            ("selected_start_sec", "range_relative_start_sec", "corrected_start_sec", "start_sec", "output_start_sec", "source_start_sec", "original_start_sec"),
            source_range_start,
            source_range_end,
        )
        rel_end = _subtitle_relative_time(
            item,
            ("selected_end_sec", "range_relative_end_sec", "corrected_end_sec", "end_sec", "output_end_sec", "source_end_sec", "original_end_sec"),
            source_range_start,
            source_range_end,
        )
        if rel_end <= rel_start:
            continue
        item["id"] = item.get("id") or f"sub_{idx:04}"
        item["range_relative_start_sec"] = rel_start
        item["range_relative_end_sec"] = rel_end
        item["source_start_sec"] = round(source_range_start + rel_start, 3)
        item["source_end_sec"] = round(source_range_start + rel_end, 3)
        item["original_start_sec"] = round(source_range_start + rel_start, 3)
        item["original_end_sec"] = round(source_range_start + rel_end, 3)
        item["original_start"] = item["original_start_sec"]
        item["original_end"] = item["original_end_sec"]
        item["whisper_start_sec"] = float(item.get("whisper_start_sec", rel_start))
        item["whisper_end_sec"] = float(item.get("whisper_end_sec", rel_end))
        item["selected_start_sec"] = rel_start
        item["selected_end_sec"] = rel_end
        pieces: list[dict] = []
        for seg_idx, seg in enumerate(segments):
            if not seg.get("enabled", True):
                continue
            seg_rel_start = float(seg["range_relative_start_sec"])
            seg_rel_end = float(seg["range_relative_end_sec"])
            overlap_start = max(rel_start, seg_rel_start)
            overlap_end = min(rel_end, seg_rel_end)
            if overlap_end <= overlap_start:
                continue
            out_start = float(seg["output_start_sec"]) + (overlap_start - seg_rel_start)
            out_end = float(seg["output_start_sec"]) + (overlap_end - seg_rel_start)
            pieces.append(
                {
                    "piece_index": len(pieces) + 1,
                    "segment_id": seg["id"],
                    "original_start_sec": round(source_range_start + overlap_start, 3),
                    "original_end_sec": round(source_range_start + overlap_end, 3),
                    "edited_start_sec": round(out_start, 3),
                    "edited_end_sec": round(out_end, 3),
                }
            )
        if not pieces:
            item["enabled"] = False
            item["original_start_sec"] = round(source_range_start + rel_start, 3)
            item["original_end_sec"] = round(source_range_start + rel_end, 3)
            item["original_start"] = item["original_start_sec"]
            item["original_end"] = item["original_end_sec"]
            item["edited_start_sec"] = None
            item["edited_end_sec"] = None
            item["edited_start"] = None
            item["edited_end"] = None
            item["output_start_sec"] = 0.0
            item["output_end_sec"] = 0.0
            item["split_pieces"] = []
            mapped.append(item)
            continue
        out_item = deepcopy(item)
        out_item["segment_id"] = pieces[0]["segment_id"]
        out_item["source_start_sec"] = pieces[0]["original_start_sec"]
        out_item["source_end_sec"] = pieces[-1]["original_end_sec"]
        out_item["original_start_sec"] = pieces[0]["original_start_sec"]
        out_item["original_end_sec"] = pieces[-1]["original_end_sec"]
        out_item["original_start"] = out_item["original_start_sec"]
        out_item["original_end"] = out_item["original_end_sec"]
        out_item["edited_start_sec"] = pieces[0]["edited_start_sec"]
        out_item["edited_end_sec"] = pieces[-1]["edited_end_sec"]
        out_item["edited_start"] = out_item["edited_start_sec"]
        out_item["edited_end"] = out_item["edited_end_sec"]
        out_item["output_start_sec"] = out_item["edited_start_sec"]
        out_item["output_end_sec"] = max(out_item["edited_end_sec"], out_item["edited_start_sec"] + 0.05)
        out_item["split_piece_index"] = 1
        out_item["split_piece_total"] = len(pieces)
        out_item["split_original_id"] = item["id"]
        out_item["split_pieces"] = pieces
        out_item["text"] = str(item.get("text", "")).strip()
        mapped.append(out_item)
    return mapped


def build_edit_plan(
    source_video: str,
    source_range: dict,
    silences: list[dict],
    transcript: dict,
    settings: dict,
) -> dict:
    merged_settings = {**DEFAULT_SETTINGS, **(settings or {})}
    range_start = float(source_range["start_sec"])
    range_end = float(source_range["end_sec"])
    duration = max(0.0, range_end - range_start)
    detection_mode = str(merged_settings.get("detection_mode", "silencedetect")).strip().lower()
    vad_intervals = transcript.get("vad_intervals") or transcript.get("speech_intervals") or []
    speech: list[tuple[float, float]] = []
    if detection_mode in {"vad", "hybrid"} and vad_intervals:
        for item in vad_intervals:
            start = float(item.get("speech_start_sec", item.get("start_sec", 0.0)))
            end = float(item.get("speech_end_sec", item.get("end_sec", start)))
            if end > start:
                speech.append((max(0.0, start), min(duration, end)))
    if not speech and detection_mode in {"silencedetect", "hybrid"}:
        speech = invert_silences(silences or [], duration)
    keep_ranges = pad_and_merge_segments(
        speech,
        duration,
        _setting_float(merged_settings, "pre_margin_sec", float(merged_settings["pre_speech_padding"])),
        _setting_float(merged_settings, "post_margin_sec", float(merged_settings["post_speech_padding"])),
        _setting_float(merged_settings, "merge_silence_gap_sec", float(merged_settings["merge_gap_duration"])),
        _setting_float(merged_settings, "min_keep_segment_duration", float(merged_settings["min_keep_segment_duration"])),
    )
    manual_cut_segments = _normalize_intervals(merged_settings.get("manual_cut_segments") or [], duration, range_start)
    protected_segments = _normalize_intervals(merged_settings.get("protected_segments") or [], duration, range_start)
    effective_manual_cuts = _subtract_many_intervals(manual_cut_segments, protected_segments)
    keep_ranges = _subtract_intervals(keep_ranges, effective_manual_cuts)
    keep_ranges = _merge_intervals(keep_ranges + protected_segments)

    segments: list[dict] = []
    output_cursor = 0.0
    for idx, (rel_start, rel_end) in enumerate(keep_ranges, start=1):
        length = rel_end - rel_start
        segments.append(
            {
                "id": f"seg_{idx:04}",
                "enabled": True,
                "type": "speech",
                "source_start_sec": round(range_start + rel_start, 3),
                "source_end_sec": round(range_start + rel_end, 3),
                "range_relative_start_sec": round(rel_start, 3),
                "range_relative_end_sec": round(rel_end, 3),
                "output_start_sec": round(output_cursor, 3),
                "output_end_sec": round(output_cursor + length, 3),
            }
        )
        output_cursor += length

    subtitles = transcript.get("subtitles") or []
    if not subtitles and transcript.get("segments"):
        from .srt import subtitles_from_whisper

        subtitles = subtitles_from_whisper(transcript)
    subtitles = map_subtitles_to_output(subtitles, segments, range_start, range_end)
    speaker_diarization = transcript.get("speaker_diarization") or {}
    speaker_segments = speaker_diarization.get("speaker_segments") or transcript.get("speaker_segments") or []
    speaker_roster = speaker_diarization.get("speaker_roster") or transcript.get("speaker_roster") or []
    subtitles = assign_speaker_labels_to_subtitles(subtitles, speaker_segments, speaker_roster=speaker_roster)
    speaker_roster = build_speaker_roster(subtitles) or speaker_roster

    return {
        "project_version": "1.0",
        "source_video": source_video,
        "source_range": {"start_sec": range_start, "end_sec": range_end},
        "settings": merged_settings,
        "manual_cut_segments": [
            {"src_start": round(range_start + start, 3), "src_end": round(range_start + end, 3)}
            for start, end in effective_manual_cuts
        ],
        "protected_segments": [
            {"src_start": round(range_start + start, 3), "src_end": round(range_start + end, 3)}
            for start, end in protected_segments
        ],
        "keep_segments": [
            {
                "src_start": round(rel_start, 3),
                "src_end": round(rel_end, 3),
            }
            for rel_start, rel_end in keep_ranges
        ],
        "segments": segments,
        "subtitles": subtitles,
        "speaker_roster": speaker_roster,
        "speaker_diarization": speaker_diarization,
    }
