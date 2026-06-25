from __future__ import annotations


def parse_timecode(value: str | float | int) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = value.strip()
    if not text:
        raise ValueError("時間が空です")
    parts = text.split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) != 3:
        raise ValueError("時間は HH:MM:SS.mmm 形式で入力してください")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def format_srt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def format_ui_time(seconds: float) -> str:
    return format_srt_time(seconds).replace(",", ".")
