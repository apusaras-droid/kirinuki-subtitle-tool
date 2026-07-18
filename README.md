# 切り抜き字幕作成ツール MVP

ローカルブラウザで動画の指定範囲を処理し、音声抽出、文字起こし、無音削除案、字幕編集、ASS字幕、装飾、プレビュー、最終出力を工程別に行う動画編集支援ツールです。

文書の正本と用途は [docs/README.md](docs/README.md) に整理しています。実装変更時は、この索引から仕様、工程契約、CLI契約、検証項目を確認してください。

配布方針と必要な同梱物は [配布仕様書_GPLv3.md](docs/%E9%85%8D%E5%B8%83%E4%BB%95%E6%A7%98%E6%9B%B8_GPLv3.md) にまとめています。
配布向けの雛形は `licenses/` にあります。
第三者コンポーネントは [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、謝辞とAI支援開示は [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md)、脆弱性報告方針は [SECURITY.md](SECURITY.md) を参照してください。
実装フローは [実装フローチャート.md](docs/%E5%AE%9F%E8%A3%85%E3%83%95%E3%83%AD%E3%83%BC%E3%83%81%E3%83%A3%E3%83%BC%E3%83%88.md)、仕様準拠の確認は [仕様準拠チェックリスト.md](docs/%E4%BB%95%E6%A7%98%E6%BA%96%E6%8B%A0%E3%83%81%E3%82%A7%E3%83%83%E3%82%AF%E3%83%AA%E3%82%B9%E3%83%88.md) を参照してください。
構造定義とリスクの整理は [構造定義およびリスク評価報告.md](docs/%E6%A7%8B%E9%80%A0%E5%AE%9A%E7%BE%A9%E3%81%8A%E3%82%88%E3%81%B3%E3%83%AA%E3%82%B9%E3%82%AF%E8%A9%95%E4%BE%A1%E5%A0%B1%E5%91%8A.md) にまとめています。
対策の実施状況は [対策実施状況.md](docs/%E5%AF%BE%E7%AD%96%E5%AE%9F%E6%96%BD%E7%8A%B6%E6%B3%81.md) を参照してください。

## 前提

- Python 3.10〜3.12（64-bit。Python 3.13は現在未対応）
- FFmpeg / FFprobe がPATHから実行できること
- 同梱済みの `tools/whisper.cpp` AMD/Vulkanビルドを使う場合は追加インストール不要
- Python版Whisperを使う場合はどちらかを別途インストール
  - `pip install openai-whisper`
  - `pip install faster-whisper`

初回セットアップは `setup.bat` だけを起動してください。番号メニューから必要な構成を選択できます。

```bat
setup.bat
```

選択肢:

- `1 標準（推奨）`: Webアプリ、Gemini、FFmpeg、日本語フォント、Whisper/VADモデル
- `2 最小`: WebアプリとFFmpegのみ。AIモデルを取得しない
- `3 フル`: 標準構成にWhisperX、Demucs、話者分離などの重いPython AI機能を追加
- `4 モデルのみ`: Whisper/VADモデルの取得またはハッシュ再検証
- `5 導入状況`: 機能グループごとの導入状態を表示
- `6 アプリ起動`: `launch.bat` を呼び出す

`setup.bat` はプロジェクト専用の `.venv` を作成するため、既存のグローバルPython環境へ依存パッケージを混在させません。標準構成では数GBになるPython AI群を導入せず、AMD GPUでの文字起こしには同梱のwhisper.cpp Vulkan版を使用します。

依存関係は機能別に分離しています。

- `requirements-core.txt`: FastAPIなどWebアプリの必須依存
- `requirements-standard.txt`: CoreとGemini連携
- `requirements-full.txt`: StandardとWhisperX、Demucs、話者分離
- `requirements.txt`: 従来互換用。Fullを参照

標準構成で取得するモデル:

- Python依存関係
- `tools/whisper.cpp/models/ggml-large-v3.bin`
- `tools/whisper.cpp/models/ggml-silero-v6.2.0.bin`

モデルは固定したHugging Face配布URLから取得し、既存ファイルを含めてSHA-256を照合します。不一致の場合は処理を停止し、モデルを実行しません。

FFmpeg / FFprobe をローカルに入れる場合は `download-ffmpeg.bat` を使います。

```bat
download-ffmpeg.bat
```

取得先は BtbN の Windows ビルドです。既定では固定タグ `autobuild-2026-06-15-15-03` を使います。展開先は `tools/ffmpeg` です。
必要ならこのフォルダを PATH に追加してください。

別タグを指定する場合は `download-ffmpeg.bat release=タグ名` を使います。

フル構成はWhisperX、Demucs、SpeechBrain、Silero VADとCPU版Torchを含むため、約2GB以上の追加空き容量と長い導入時間を見込んでください。

`download-runtime.bat`、`download-ffmpeg.bat`、`download-japanese-fonts.bat` は `setup.bat` から呼ばれる内部入口です。個別復旧や開発時には直接実行できます。

自動セットアップで詰まった場合は [手動インストール案内.txt](docs/%E6%89%8B%E5%8B%95%E3%82%A4%E3%83%B3%E3%82%B9%E3%83%88%E3%83%BC%E3%83%AB%E6%A1%88%E5%86%85.txt) を参照してください。

## 起動

BAT で起動する場合:

```bat
launch.bat
```

引数を付ける場合:

```bat
launch.bat port=8001
launch.bat hidden
launch.bat nobrowser
```

PowerShell / 手動起動の場合:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-standard.txt
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

ブラウザで開く:

```text
http://127.0.0.1:8000
```

BAT 起動時はサーバー用のコンソールウィンドウを表示します。ログは `logs/server-<port>.log` に残ります。
起動時に既存サーバーの `/api/version` を確認し、古いビルドなら停止して現在のコードで立ち上げ直します。

動画をドラッグ＆ドロップして、そのまま全体を処理する場合は `process-video*.bat` を使います。

```bat
process-video.bat
```

使い方:

- 動画ファイルを `process-video.bat` にドラッグ＆ドロップする
- 動画のあるフォルダに `SRT\` フォルダが作られる
- `SRT\動画名.gpu_autocut.mp4` と `SRT\動画名.gpu_autocut.srt` が保存される
- `SRT\` には最終的に動画と字幕だけを残し、補助ファイルは片付ける
- `process-video.bat` は GPU + auto cut
- `process-video-gpu-nocut.bat` は GPU + no auto cut
- `process-video-cpu-autocut.bat` は CPU + auto cut（GUI既定に合わせて `whisper.cpp` + `large-v3`）
- `process-video-cpu-nocut.bat` は CPU + no auto cut（GUI既定に合わせて `whisper.cpp` + `large-v3`）
- 出力ファイル名には `gpu_autocut` / `gpu_nocut` / `cpu_autocut` / `cpu_nocut` の接尾辞が付く
- いずれの preset も GUI の `VADを使う` 設定に合わせて `detection_mode=vad` で動きます
- preset の本体は [scripts/process-video.presets.json](scripts/process-video.presets.json) にあります
- これらの BAT は複数ファイルを同時にドラッグ＆ドロップして順番に処理できます

必要なら `scripts/process-video.ps1` を直接呼んで `StartSec` / `EndSec` を指定できます。

## CLI モード

```powershell
python -m backend --help
```

GUI を使わずに一括処理したい場合は `run-pipeline` を使います。
監査ログは `logs/app_audit.jsonl` と各プロジェクトの `temp/logs/audit.jsonl` に残ります。
波形解析や字幕補正の詳細は `projects/<project_id>/temp/logs/processing.jsonl` に残ります。
JSON 設定で実行する例は [docs/cli-run-pipeline.sample.json](docs/cli-run-pipeline.sample.json) を参照してください。
`run-pipeline` は `subtitles` 配列を受け取れるので、AI や外部オーケストレータから文字起こしを省いて編集・出力だけ回すこともできます。
Whisper の既定エンジンは `whisper.cpp` です。Whisper は本文と大まかな時刻の取得に使い、編集は無音削除後のタイムラインに再マッピングします。
無音・非発話区間の検出はプリセットに応じて `silencedetect` または Silero VAD を使います。BGMが強い素材では、解析用の声抽出を併用できます。
`run-pipeline --auto-cleanup` で処理後の重い中間ファイルを自動整理できます。
仕様準拠の自動チェックは `scripts/verify-spec.ps1` で実行できます。フル経路のスモークテスト単体は `scripts/smoke-test.ps1` です。
外部プログラムからの呼び出し手順は [docs/外部CLI連携.md](docs/%E5%A4%96%E9%83%A8CLI%E9%80%A3%E6%90%BA.md) にまとめています。
AI向けの引き継ぎ前提は [docs/AI向け引き継ぎ説明書.md](docs/AI%E5%90%91%E3%81%91%E5%BC%95%E3%81%8D%E7%B6%99%E3%81%8E%E8%AA%AC%E6%98%8E%E6%9B%B8.md) を参照してください。
AI向けの紹介文は [docs/AI向けプレゼンテキスト.txt](docs/AI%E5%90%91%E3%81%91%E3%83%97%E3%83%AC%E3%82%BC%E3%83%B3%E3%83%86%E3%82%AD%E3%82%B9%E3%83%88.txt) にあります。
`cleanup` で重い中間ファイルだけ整理できます。

## 配布物の作成

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\make-release.ps1
```

モデルを同梱する場合は `-IncludeModels` を付けます。配布前に `docs/配布仕様書_GPLv3.md` を確認してください。

## 生成物

プロジェクトは `projects/<project_id>/` に保存されます。

- `source/input.*`
- `audio/source_range.wav`
- `transcript/transcript.json`
- `subtitles/original.srt`
- `subtitles/aligned.srt`
- `subtitles/edited.srt`
- `subtitles/final.ass` または出力先の通常ASS/装飾ASS
- `analysis/waveform.json`
- `analysis/waveform.png`
- `edit_plan.json`
- `preview/preview_low.mp4`
- `output/final.mp4`
- `output/final.ass`
- `output/edit_plan_final.json`

元動画は直接編集しません。処理の中心は `edit_plan.json` です。

SRTは文字起こし・編集互換用の内部形式として保持します。通常の配布字幕はASSを標準とし、外部ASS、動画への焼き込み、MKVへのASS字幕トラック埋め込みを選択できます。装飾を含めない通常ASSと、デコレーション設定を含む装飾ASSは別の出力です。

## License

このプロジェクト本体は `GPL-3.0-or-later` での配布を前提にしています。
配布時は `docs/配布仕様書_GPLv3.md` を確認してください。
`LICENSE` と `licenses/GPL-3.0-or-later.txt` にGNU GPL version 3の全文を収録しています。
第三者コンポーネント、モデル、フォント、FFmpeg、whisper.cppにはそれぞれのライセンスと配布条件が適用されます。

## Whisper engine

既定は `whisper.cpp AMD` です。
- `compute_profile=cpu` のときは `whisper.cpp --no-gpu` を使い、`processing_summary.whisper.device=cpu` として記録します。
- `compute_profile=gpu` のときは `whisper.cpp` の GPU 経路を使い、`processing_summary.whisper.device=vulkan` として記録します。

- 実行ファイル: `tools/whisper.cpp/bin/whisper-cli.exe`
- 既定モデル: `tools/whisper.cpp/models/ggml-large-v3.bin`
- UIのモデル欄には `large-v3` またはモデルファイルのフルパスを指定できます。
- 最終出力で字幕を焼き込む場合は GUI の「字幕を焼き込む」または CLI/API の `burn_subtitles=true` を使ってください。既定は無効です。
- 字幕フォント、サイズ、色、縁は通常ASSへ保存できます。SRTにはスタイル情報を保存できません。
