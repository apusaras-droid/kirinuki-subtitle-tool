from __future__ import annotations

import os
from pathlib import Path
import re

from .timecode import format_srt_time


SENTENCE_BREAK_TOKENS = {"。", "！", "？", "!", "?", "…", "\n"}
WHITESPACE_TOKENS = {" ", "\t", "\r", "\n"}


def parse_srt(srt_text: str) -> list[dict]:
    text = str(srt_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    blocks = re.split(r"\n\s*\n", text)
    subtitles: list[dict] = []
    for idx, block in enumerate(blocks, start=1):
        lines = [line.rstrip() for line in block.split("\n") if line.strip() or len(block.split("\n")) == 1]
        if not lines:
            continue
        if re.fullmatch(r"\d+", lines[0].strip()):
            lines = lines[1:]
        if not lines:
            continue
        time_line = lines[0].strip()
        match = re.match(r"(?P<start>\d+:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?P<end>\d+:\d{2}:\d{2}[,.]\d{3})", time_line)
        if not match:
            continue

        def parse_time(value: str) -> float:
            hours, minutes, rest = value.replace(",", ".").split(":")
            seconds, millis = rest.split(".")
            return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis[:3].ljust(3, "0")) / 1000.0

        body = "\n".join(lines[1:]).strip()
        subtitles.append(
            {
                "id": f"sub_{idx:04}",
                "enabled": True,
                "start_sec": round(parse_time(match.group("start")), 3),
                "end_sec": round(parse_time(match.group("end")), 3),
                "output_start_sec": round(parse_time(match.group("start")), 3),
                "output_end_sec": round(parse_time(match.group("end")), 3),
                "text": body,
            }
        )
    return subtitles


def sanitize_srt_text(text: str, *, strict_burn: bool = False) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned_lines: list[str] = []
    for line in raw.split("\n"):
        filtered = []
        for ch in line:
            code = ord(ch)
            if ch == "\t":
                filtered.append(" ")
            elif strict_burn and ch == "[":
                filtered.append("［")
            elif strict_burn and ch == "]":
                filtered.append("］")
            elif strict_burn and ch == "\\":
                filtered.append("/")
            elif code >= 0x20:
                filtered.append(ch)
            else:
                filtered.append(" ")
        normalized = re.sub(r"[ \t]+", " ", "".join(filtered)).strip()
        if normalized:
            cleaned_lines.append(normalized)
    return "\n".join(cleaned_lines)


def write_srt(subtitles: list[dict], path: Path, *, strict_burn: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    index = 1
    for item in subtitles:
        if item.get("enabled", True) is False:
            continue
        text = sanitize_srt_text(item.get("text", ""), strict_burn=strict_burn)
        speaker_label = sanitize_srt_text(item.get("speaker_label", ""), strict_burn=strict_burn).replace("\n", " ").strip()
        if speaker_label and item.get("speaker_label_prefix", True):
            if not re.match(rf"^{re.escape(speaker_label)}(?:[:：\s]|$)", text):
                text = f"{speaker_label}: {text}" if text else speaker_label
        if not text:
            continue
        start = float(item.get("output_start_sec", item.get("start_sec", 0.0)))
        end = float(item.get("output_end_sec", item.get("end_sec", start)))
        lines.extend(
            [
                str(index),
                f"{format_srt_time(start)} --> {format_srt_time(end)}",
                *text.split("\n"),
                "",
            ]
        )
        index += 1
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text("\n".join(lines), encoding="utf-8")
    os.replace(temp_path, path)


def subtitles_from_whisper(result: dict) -> list[dict]:
    transcription = result.get("transcription")
    if isinstance(transcription, list) and any(isinstance(item, dict) and item.get("words") for item in transcription):
        return subtitles_from_word_timestamps(transcription)
    if isinstance(transcription, list) and any(isinstance(item, dict) and item.get("tokens") for item in transcription):
        return subtitles_from_whisper_tokens(transcription)

    subtitles: list[dict] = []
    for idx, segment in enumerate(result.get("segments", []), start=1):
        subtitles.append(
            {
                "id": f"sub_{idx:04}",
                "enabled": True,
                "whisper_start_sec": float(segment.get("start", 0.0)),
                "whisper_end_sec": float(segment.get("end", 0.0)),
                "source_start_sec": float(segment.get("start", 0.0)),
                "source_end_sec": float(segment.get("end", 0.0)),
                "range_relative_start_sec": float(segment.get("start", 0.0)),
                "range_relative_end_sec": float(segment.get("end", 0.0)),
                "output_start_sec": float(segment.get("start", 0.0)),
                "output_end_sec": float(segment.get("end", 0.0)),
                "text": str(segment.get("text", "")).strip(),
            }
        )
    return subtitles


def subtitles_from_word_timestamps(transcription: list[dict]) -> list[dict]:
    subtitles: list[dict] = []
    chunk_words: list[dict] = []
    chunk_start: float | None = None
    chunk_end: float | None = None
    chunk_has_text = False

    def flush() -> None:
        nonlocal chunk_words, chunk_start, chunk_end, chunk_has_text
        if chunk_start is None or chunk_end is None or not chunk_has_text:
            chunk_words = []
            chunk_start = None
            chunk_end = None
            chunk_has_text = False
            return
        text = "".join(
            w.get("word", "") if str(w.get("word", "")).startswith((" ", "\t")) else str(w.get("word", "")).strip()
            for w in chunk_words
        ).strip()
        if text:
            subtitles.append(
                {
                    "id": f"sub_{len(subtitles) + 1:04}",
                    "enabled": True,
                    "whisper_start_sec": round(chunk_start, 3),
                    "whisper_end_sec": round(chunk_end, 3),
                    "source_start_sec": round(chunk_start, 3),
                    "source_end_sec": round(chunk_end, 3),
                    "range_relative_start_sec": round(chunk_start, 3),
                    "range_relative_end_sec": round(chunk_end, 3),
                    "output_start_sec": round(chunk_start, 3),
                    "output_end_sec": round(chunk_end, 3),
                    "text": text,
                }
            )
        chunk_words = []
        chunk_start = None
        chunk_end = None
        chunk_has_text = False

    for item in transcription:
        words = item.get("words") or []
        for word in words:
            text = str(word.get("word", ""))
            if not text.strip():
                continue
            start = float(word.get("start", word.get("timestamps", {}).get("from", 0.0)) or 0.0)
            end = float(word.get("end", word.get("timestamps", {}).get("to", start)) or start)
            if chunk_start is None:
                chunk_start = start
            if chunk_end is not None and start - chunk_end > 0.55:
                flush()
                chunk_start = start
            chunk_words.append({"word": text, "start": start, "end": end})
            chunk_end = end
            chunk_has_text = True
            cleaned = text.strip()
            if (cleaned and cleaned[-1] in SENTENCE_BREAK_TOKENS) or (chunk_start is not None and chunk_end is not None and chunk_end - chunk_start >= 4.5):
                flush()
        flush()

    return subtitles


def subtitles_from_whisper_tokens(transcription: list[dict]) -> list[dict]:
    subtitles: list[dict] = []
    for item in transcription:
        tokens = item.get("tokens") or []
        item_text = str(item.get("text", "")).strip()
        start: float | None = None
        end: float | None = None
        for token in tokens:
            token_text = str(token.get("text", ""))
            if not token_text or token_text in WHITESPACE_TOKENS or token_text.startswith("[_") or token_text.endswith("_]"):
                continue
            token_start = float(token.get("offsets", {}).get("from", 0)) / 1000.0
            token_end = float(token.get("offsets", {}).get("to", 0)) / 1000.0
            start = token_start if start is None else min(start, token_start)
            end = token_end if end is None else max(end, token_end)
        if start is None:
            start = float(item.get("offsets", {}).get("from", 0)) / 1000.0
        if end is None:
            end = float(item.get("offsets", {}).get("to", 0)) / 1000.0
        if item_text and item_text not in SENTENCE_BREAK_TOKENS:
            subtitles.append(
                {
                    "id": f"sub_{len(subtitles) + 1:04}",
                    "enabled": True,
                    "whisper_start_sec": round(start, 3),
                    "whisper_end_sec": round(end, 3),
                    "source_start_sec": round(start, 3),
                    "source_end_sec": round(end, 3),
                    "range_relative_start_sec": round(start, 3),
                    "range_relative_end_sec": round(end, 3),
                    "output_start_sec": round(start, 3),
                    "output_end_sec": round(end, 3),
                    "text": item_text,
                }
            )
    return subtitles


def normalize_subtitle_durations(
    subtitles: list[dict],
    chars_per_second: float = 3.5,
    min_duration: float = 1.2,
    max_duration: float = 4.5,
    min_gap: float = 0.05,
) -> list[dict]:
    normalized: list[dict] = []
    ordered = list(subtitles)
    for idx, sub in enumerate(ordered):
        item = dict(sub)
        text = str(item.get("text", ""))
        visible_chars = len(re.sub(r"\s+", "", text))
        target = visible_chars / chars_per_second if visible_chars else min_duration
        target = max(min_duration, min(max_duration, target))
        start = float(item.get("output_start_sec", item.get("start_sec", 0.0)))
        end = float(item.get("output_end_sec", item.get("end_sec", start)))
        if end - start > target:
            end = start + target
        if end - start < min_duration:
            end = start + min_duration
        if idx + 1 < len(ordered):
            next_start = float(ordered[idx + 1].get("output_start_sec", ordered[idx + 1].get("start_sec", end)))
            end = min(end, max(start + 0.05, next_start - min_gap))
        item["source_start_sec"] = float(item.get("source_start_sec", start))
        item["source_end_sec"] = float(item.get("source_end_sec", end))
        item["range_relative_start_sec"] = float(item.get("range_relative_start_sec", start))
        item["range_relative_end_sec"] = float(item.get("range_relative_end_sec", end))
        item["output_start_sec"] = round(start, 3)
        item["output_end_sec"] = round(end, 3)
        normalized.append(item)
    return normalized

def _match_vad_interval(
    whisper_start: float,
    whisper_end: float,
    vad_intervals: list[dict],
    max_gap_sec: float = 1.5,
) -> tuple[int | None, dict | None]:
    best_overlap_idx: int | None = None
    best_overlap: float | None = None
    best_gap_idx: int | None = None
    best_gap: float | None = None
    best_gap_interval: dict | None = None
    for idx, interval in enumerate(vad_intervals):
        vad_start = float(interval.get("speech_start_sec", interval.get("start_sec", 0.0)))
        vad_end = float(interval.get("speech_end_sec", interval.get("end_sec", vad_start)))
        if vad_end <= vad_start:
            continue
        overlap = min(whisper_end, vad_end) - max(whisper_start, vad_start)
        if overlap >= 0:
            if best_overlap is None or overlap > best_overlap:
                best_overlap = overlap
                best_overlap_idx = idx
            continue
        gap = max(vad_start - whisper_end, whisper_start - vad_end)
        if gap <= max_gap_sec and (best_gap is None or gap < best_gap):
            best_gap = gap
            best_gap_idx = idx
            best_gap_interval = {
                "speech_start_sec": round(vad_start, 3),
                "speech_end_sec": round(vad_end, 3),
                "gap_sec": round(gap, 3),
                "overlap": False,
            }
    if best_overlap_idx is not None:
        interval = vad_intervals[best_overlap_idx]
        vad_start = float(interval.get("speech_start_sec", interval.get("start_sec", 0.0)))
        vad_end = float(interval.get("speech_end_sec", interval.get("end_sec", vad_start)))
        return best_overlap_idx, {
            "speech_start_sec": round(vad_start, 3),
            "speech_end_sec": round(vad_end, 3),
            "gap_sec": 0.0,
            "overlap": True,
        }
    if best_gap_idx is not None:
        return best_gap_idx, best_gap_interval
    return None, None


def apply_vad_subtitle_corrections(
    subtitles: list[dict],
    vad_intervals: list[dict],
    *,
    subtitle_start_strategy: str = "hybrid",
    pre_margin_sec: float = 0.3,
    post_margin_sec: float = 0.5,
    max_match_gap_sec: float = 1.5,
) -> list[dict]:
    corrected: list[dict] = []
    strategy = (subtitle_start_strategy or "hybrid").strip().lower()
    if strategy not in {"whisper", "vad", "hybrid"}:
        strategy = "hybrid"

    if strategy == "whisper":
        for idx, sub in enumerate(subtitles, start=1):
            item = dict(sub)
            whisper_start = float(
                item.get(
                    "whisper_start_sec",
                    item.get("source_start_sec", item.get("output_start_sec", 0.0)),
                )
            )
            whisper_end = float(
                item.get(
                    "whisper_end_sec",
                    item.get("source_end_sec", item.get("output_end_sec", whisper_start)),
                )
            )
            text = str(item.get("text", "")).strip()
            item["id"] = item.get("id") or f"sub_{idx:04}"
            item["whisper_start_sec"] = round(whisper_start, 3)
            item["whisper_end_sec"] = round(whisper_end, 3)
            item["vad_start_sec"] = None
            item["vad_end_sec"] = None
            item["corrected_start_sec"] = round(whisper_start, 3)
            item["corrected_end_sec"] = round(whisper_end, 3)
            item["source_start_sec"] = round(whisper_start, 3)
            item["source_end_sec"] = round(whisper_end, 3)
            item["range_relative_start_sec"] = round(whisper_start, 3)
            item["range_relative_end_sec"] = round(whisper_end, 3)
            item["output_start_sec"] = round(whisper_start, 3)
            item["output_end_sec"] = round(whisper_end, 3)
            item["subtitle_start_strategy"] = strategy
            item["whisper_segments"] = [
                {
                    "text": text,
                    "whisper_start_sec": round(whisper_start, 3),
                    "whisper_end_sec": round(whisper_end, 3),
                }
            ]
            corrected.append(item)
        return corrected

    grouped: list[dict] = []
    group_index_by_vad: dict[int, int] = {}

    for sub in subtitles:
        item = dict(sub)
        whisper_start = float(
            item.get(
                "whisper_start_sec",
                item.get("source_start_sec", item.get("output_start_sec", 0.0)),
            )
        )
        whisper_end = float(
            item.get(
                "whisper_end_sec",
                item.get("source_end_sec", item.get("output_end_sec", whisper_start)),
            )
        )
        match_index, matched = _match_vad_interval(whisper_start, whisper_end, vad_intervals, max_gap_sec=max_match_gap_sec)
        vad_start = float(matched["speech_start_sec"]) if matched else None
        vad_end = float(matched["speech_end_sec"]) if matched else None

        if match_index is None:
            group = {
                "group_key": f"unmatched_{len(grouped) + 1:04}",
                "vad_index": None,
                "vad_start_sec": None,
                "vad_end_sec": None,
                "whisper_start_sec": whisper_start,
                "whisper_end_sec": whisper_end,
                "segments": [],
            }
            grouped.append(group)
        else:
            if match_index not in group_index_by_vad:
                group = {
                    "group_key": f"vad_{match_index + 1:04}",
                    "vad_index": match_index,
                    "vad_start_sec": vad_start,
                    "vad_end_sec": vad_end,
                    "whisper_start_sec": whisper_start,
                    "whisper_end_sec": whisper_end,
                    "segments": [],
                }
                group_index_by_vad[match_index] = len(grouped)
                grouped.append(group)
            else:
                group = grouped[group_index_by_vad[match_index]]
                group["whisper_start_sec"] = min(float(group["whisper_start_sec"]), whisper_start)
                group["whisper_end_sec"] = max(float(group["whisper_end_sec"]), whisper_end)
                if vad_start is not None:
                    group["vad_start_sec"] = vad_start if group["vad_start_sec"] is None else min(float(group["vad_start_sec"]), vad_start)
                if vad_end is not None:
                    group["vad_end_sec"] = vad_end if group["vad_end_sec"] is None else max(float(group["vad_end_sec"]), vad_end)

        group["segments"].append(
            {
                "id": item.get("id"),
                "text": str(item.get("text", "")).strip(),
                "whisper_start_sec": round(whisper_start, 3),
                "whisper_end_sec": round(whisper_end, 3),
            }
        )

    for idx, group in enumerate(grouped, start=1):
        whisper_start = float(group["whisper_start_sec"])
        whisper_end = float(group["whisper_end_sec"])
        vad_start = group["vad_start_sec"]
        vad_end = group["vad_end_sec"]

        if strategy == "vad" and vad_start is not None and vad_end is not None:
            base_start = float(vad_start)
            base_end = float(vad_end)
        elif strategy == "hybrid" and vad_start is not None and vad_end is not None:
            base_start = min(whisper_start, float(vad_start))
            base_end = max(whisper_end, float(vad_end))
        else:
            base_start = whisper_start
            base_end = whisper_end

        corrected_start = max(0.0, base_start - float(pre_margin_sec))
        corrected_end = max(corrected_start + 0.05, base_end + float(post_margin_sec))
        combined_text = "\n".join(segment["text"] for segment in group["segments"] if segment["text"]).strip()
        if not combined_text:
            continue

        if vad_start is not None and whisper_end < float(vad_start):
            vad_gap_sec = float(vad_start) - whisper_end
        elif vad_end is not None and whisper_start > float(vad_end):
            vad_gap_sec = whisper_start - float(vad_end)
        else:
            vad_gap_sec = 0.0 if vad_start is not None or vad_end is not None else None

        corrected.append(
            {
                "id": f"sub_{idx:04}",
                "enabled": True,
                "whisper_start_sec": round(whisper_start, 3),
                "whisper_end_sec": round(whisper_end, 3),
                "vad_start_sec": round(float(vad_start), 3) if vad_start is not None else None,
                "vad_end_sec": round(float(vad_end), 3) if vad_end is not None else None,
                "corrected_start_sec": round(corrected_start, 3),
                "corrected_end_sec": round(corrected_end, 3),
                "source_start_sec": round(corrected_start, 3),
                "source_end_sec": round(corrected_end, 3),
                "range_relative_start_sec": round(corrected_start, 3),
                "range_relative_end_sec": round(corrected_end, 3),
                "output_start_sec": round(corrected_start, 3),
                "output_end_sec": round(corrected_end, 3),
                "subtitle_start_strategy": strategy,
                "vad_gap_sec": round(float(vad_gap_sec), 3) if vad_gap_sec is not None else None,
                "corrected_by_vad": True if (vad_start is not None or vad_end is not None) and (corrected_start != whisper_start or corrected_end != whisper_end) else False,
                "group_key": group["group_key"],
                "vad_interval_index": group["vad_index"],
                "whisper_segments": group["segments"],
                "text": combined_text,
            }
        )
    corrected.sort(key=lambda item: float(item.get("output_start_sec", 0.0)))
    for idx, item in enumerate(corrected):
        start = float(item.get("output_start_sec", 0.0))
        end = float(item.get("output_end_sec", start))
        if idx + 1 < len(corrected):
            next_start = float(corrected[idx + 1].get("output_start_sec", end))
            end = min(end, max(start + 0.05, next_start - 0.05))
        if end <= start:
            end = start + 0.05
        item["corrected_end_sec"] = round(end, 3)
        item["source_end_sec"] = round(end, 3)
        item["range_relative_end_sec"] = round(end, 3)
        item["output_end_sec"] = round(end, 3)
    return corrected
