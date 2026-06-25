# AI向け引き継ぎ説明書

この文書は、他のAIや自動化ツールがこのリポジトリを扱うときの前提をまとめたものです。
実装の詳細よりも、何を正とし、どこを触るべきかを優先して書いています。

## 目的

このツールは、ローカル動画から字幕を作り、無音や不要区間を削り、最終的に `SRT` と動画を出力するためのものです。

主な処理は次の順で進みます。

1. 動画を読み込む
2. 音声を抽出する
3. Whisper で字幕本文を作る
4. 必要なら無音区間を検出する
5. 編集案 JSON を作る
6. プレビューまたは最終出力を作る

## このリポジトリの考え方

- 元動画は直接破壊しない
- 中心データは `edit_plan.json`
- 字幕本文は Whisper が担当
- 区間判定は無音検出や VAD を補助的に使う
- 最終的な編集結果は編集案を経由する
- 配布と復旧をしやすくするため、BAT と CLI を残している

## いまの安定した入口

- 初回セットアップ: `setup.bat`
- ランタイム取得: `download-runtime.bat`
- FFmpeg 取得: `download-ffmpeg.bat`
- サーバー起動: `launch.bat`
- 全体処理: `process-video*.bat`
- 外部プログラム向けCLI: `python -m backend --help`

## 外部プログラムから使う時の基本

最も安定なのは `run-pipeline --config` です。

```powershell
python -m backend run-pipeline --config docs/cli-run-pipeline.sample.json --report logs/report.json
```

細かく分けるなら以下の順です。

1. `new-project`
2. `extract-audio`
3. `transcribe`
4. `detect-silence`
5. `create-edit-plan`
6. `preview`
7. `export`

## 現在の既定

- Whisper エンジン: `whisper.cpp`
- GPU/CPU 切替: `compute_profile`
- 無音検出: `silencedetect`
- 初回セットアップ: `setup.bat`

## 重要な設定の扱い

- `compute_profile=gpu`
  - Whisper.cpp の GPU 経路を狙う
  - CPU が必要な段は止める、または明示的に失敗させる運用がある
- `compute_profile=cpu`
  - CPU 実行を狙う
- `voice_isolation_enabled`
  - BGM が強いときに補助になる
- `detection_mode`
  - `silencedetect` / `vad` / `hybrid`

## ログの場所

- グローバル監査ログ: `logs/app_audit.jsonl`
- プロジェクト監査ログ: `projects/<project_id>/temp/logs/audit.jsonl`
- 処理ログ: `projects/<project_id>/temp/logs/processing.jsonl`
- Whisper.cpp ログ: `projects/<project_id>/temp/logs/whisper_cpp.log`

## 失敗した時の見方

まず次を確認します。

1. `logs/server-<port>.log`
2. `logs/app_audit.jsonl`
3. `projects/<project_id>/temp/logs/processing.jsonl`
4. `projects/<project_id>/temp/logs/whisper_cpp.log`

よくある原因:

- FFmpeg / FFprobe が見つからない
- Python 依存関係が未導入
- Whisper モデルが未ダウンロード
- GPU メモリ不足
- 古いサーバーが残っていて、修正が反映されていない

## AIが触るときの注意

- 設定項目を減らすなら、UI と CLI と README を同時に揃える
- パスはプロジェクト外に出さない
- 既存プロジェクトは壊さない
- 実行結果は JSON で返す方が外部連携しやすい
- 迷ったら `docs/外部CLI連携.md` を優先する

## 変更前に見るべきもの

- `README.md`
- `docs/外部CLI連携.md`
- `docs/配布仕様書_GPLv3.md`
- `docs/spec-checklist.md`
- `docs/実装フローチャート.md`

## AI向けの要約

このプロジェクトは「ローカル動画を対象に、Whisperで文字起こしし、必要なら無音区間を除去し、字幕と動画を作る」ツールです。
修正は小さく、入口は `setup.bat` / `launch.bat` / `python -m backend` に寄せるのが基本です。
