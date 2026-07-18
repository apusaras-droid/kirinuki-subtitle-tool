# Third-Party Notices

この文書は、切り抜き動画工房が直接利用する主な第三者コンポーネントを示します。最終的な配布確認では、配布対象に実際に含まれる全依存と推移的依存をロックファイルまたはSBOMから再確認してください。

## Python dependencies

| Component | Pinned version | License | Upstream |
|---|---:|---|---|
| FastAPI | 0.115.6 | MIT | https://github.com/fastapi/fastapi |
| Uvicorn | 0.34.0 | BSD-3-Clause | https://github.com/encode/uvicorn |
| python-multipart | 0.0.20 | Apache-2.0 | https://github.com/Kludex/python-multipart |
| Pydantic | 2.12.5 | MIT | https://github.com/pydantic/pydantic |
| faster-whisper | 1.2.1 | MIT | https://github.com/SYSTRAN/faster-whisper |
| WhisperX | 3.8.6 | BSD-2-Clause | https://github.com/m-bain/whisperX |
| Demucs | 4.0.1 | MIT (code) | https://github.com/facebookresearch/demucs |
| SpeechBrain | 1.1.0 | Apache-2.0 | https://github.com/speechbrain/speechbrain |
| silero-vad | 6.2.1 | MIT | https://github.com/snakers4/silero-vad |
| Google Gen AI SDK | 2.12.1 | Apache-2.0 | https://github.com/googleapis/python-genai |

`requirements.txt` は直接依存だけを固定しています。`requirements-dev.txt` はテスト用依存を追加します。Pythonパッケージ自体は配布ZIPへ同梱せず、利用者の専用 `.venv` へセットアップ時にインストールします。

## External tools

### whisper.cpp

- License: MIT
- Upstream: https://github.com/ggml-org/whisper.cpp
- Notice: [licenses/MIT-whisper.cpp.txt](licenses/MIT-whisper.cpp.txt)

自前ビルドした実行ファイルを配布する場合は、使用したコミット、ビルドオプション、Vulkanランタイム依存、SHA-256をReleaseへ記録します。

### FFmpeg / FFprobe

- Upstream: https://ffmpeg.org/
- Notice: [licenses/FFmpeg-notice.txt](licenses/FFmpeg-notice.txt)

FFmpegのライセンスはビルド構成によって変わります。通常のソース配布ではバイナリを同梱せず、固定した公式配布元からセットアップ時に取得します。バイナリを同梱するReleaseでは `ffmpeg -buildconf`、正確な配布元、SHA-256、対応ソースの入手方法を記録します。Non-freeコンポーネントを含むビルドは同梱しません。

## Models

Whisper、Silero VAD、Demucs、WhisperX、SpeechBrainが取得するモデルは、実装コードとは別の配布条件を持つ場合があります。既定の公開パッケージにはモデルを同梱しません。

モデルを同梱する場合は、モデルごとに次を記録します。

- 正式名称とバージョン
- 配布元URL
- ライセンスまたは利用条件
- SHA-256
- 変更・量子化の有無
- 論文や作者の表示条件

条件を確認できないモデルは配布しません。特にDemucsの学習済みモデルはコードのMITライセンスと分けて確認します。

## Fonts

配布対象の日本語フォントはSIL Open Font License 1.1です。フォントごとのOFL本文は [licenses/fonts/](licenses/fonts/) に収録しています。フォント本体を配布する場合は対応するOFL本文を同じ配布物へ含めます。

## Optional network service

Gemini APIはGoogleが提供する外部サービスです。本プロジェクトのGPLライセンスは、APIサービス、生成結果、利用規約を置き換えません。利用者が自身のAPIキーを設定し、送信データと適用条件を確認します。
