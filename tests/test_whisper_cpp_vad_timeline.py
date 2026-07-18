from backend.app.services import normalize_whisper_cpp_vad_transcription


def test_vad_token_offsets_are_anchored_to_source_segment_without_accumulating_silence():
    raw = [
        {
            "text": "最初",
            "offsets": {"from": 2180, "to": 7540},
            "tokens": [
                {"text": "最", "offsets": {"from": 0, "to": 230}},
                {"text": "初", "offsets": {"from": 5000, "to": 5080}},
            ],
        },
        {
            "text": "次",
            "offsets": {"from": 7540, "to": 12450},
            "tokens": [
                {"text": "次", "offsets": {"from": 5240, "to": 5400}},
                {"text": "です", "offsets": {"from": 9760, "to": 10240}},
            ],
        },
        {
            "text": "末尾",
            "offsets": {"from": 763500, "to": 766370},
            "tokens": [
                {"text": "末", "offsets": {"from": 466820, "to": 467200}},
                {"text": "尾", "offsets": {"from": 468530, "to": 469240}},
            ],
        },
    ]

    normalized = normalize_whisper_cpp_vad_transcription(raw)

    assert normalized[0]["tokens"][0]["offsets"] == {"from": 2180, "to": 2410}
    assert normalized[1]["tokens"][0]["offsets"] == {"from": 7540, "to": 7700}
    assert normalized[1]["tokens"][1]["offsets"] == {"from": 12060, "to": 12450}
    assert normalized[2]["tokens"][0]["offsets"] == {"from": 763500, "to": 763880}
    assert normalized[2]["tokens"][1]["offsets"] == {"from": 765210, "to": 765920}
    assert normalized[-1]["tokens"][-1]["offsets"]["to"] <= raw[-1]["offsets"]["to"]
