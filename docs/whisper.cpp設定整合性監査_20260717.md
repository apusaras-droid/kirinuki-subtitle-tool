# whisper.cpp設定整合性監査 2026-07-17

## 対象

- 元ビルド: `D:/AI/whisper.cpp`
- アプリ同梱先: `tools/whisper.cpp/bin`
- GPU: AMD Radeon RX 7800 XT / Vulkan
- 音声入力: 16kHz、モノラル、PCM 16bit WAV

## 確認結果

1. 元ビルドは公式安定版 `v1.9.1`（commit `f049fff`）だった。
2. アプリ同梱バイナリは2026-03-25生成で、元ビルドとハッシュが不一致だった。
3. アプリ独自の `-nf`、`-et 2.80`、`-nth 0.35` は公式既定値から外れ、温度フォールバックを無効化していたため撤去済み。
4. `-mc 0` は長尺処理で過去字幕をデコード文脈へ持ち越さず、反復ループを抑える目的で維持する。
5. `-nfa` はRX 7800 XTとlarge-v3でFlash Attention使用時に発生したメモリ確保失敗を避けるため維持する。
6. JSON Full出力 `-ojf` はトークン時刻の監査に必要なため維持する。
7. VAD閾値は公式既定の0.50へ統一した。
8. whisper.cpp内蔵VADには最大発話長30秒を設定し、極端に長いチャンクを分割する。
9. whisper.cpp内蔵VADモデルを公式v1.9.1文書推奨のSilero v6.2.0へ更新した。
10. Python VADは `silero-vad==6.2.1` を優先し、未導入時のTorch Hubも同じタグへ固定した。
11. 45秒の実機比較で、VADなしは旧来の反復誤文を再現し、Silero v6.2.0内蔵VADでは冒頭の誤文を除去できた。
12. GUIの4プリセットは `whisper.cpp-vad` を標準とし、外部Silero VADによる字幕境界確認も継続する。

## 現在の基本CLI

```text
whisper-cli.exe
  -m <model>
  -f <16kHz mono PCM16 WAV>
  -l ja
  -sow
  -ojf
  -mc 0
  -nfa
  -of <output-base>
```

CPU指定時のみ `-ng` を追加する。内蔵VADエンジンではさらに以下を追加する。

```text
--vad -vm ggml-silero-v6.2.0.bin
-vt 0.50 -vspd <ms> -vsd <ms> -vmsd 30 -vp <ms>
```

## 出力後の防御

whisper.cppだけでは無音・BGM上の反復ハルシネーションを完全には防げない。したがって、同一文が30秒以内に3回以上出現し、Silero VADとの重複率が35%未満の場合のみ字幕から除外する。除外前字幕と理由は `transcript.json` と監査ログに残す。

## 一次情報

- https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.1
- https://github.com/ggml-org/whisper.cpp/blob/v1.9.1/examples/cli/README.md
- https://github.com/ggml-org/whisper.cpp/blob/v1.9.1/README.md
- https://github.com/ggml-org/whisper.cpp/issues/3744
- https://github.com/snakers4/silero-vad/releases/tag/v6.2.1
