# AI向け引き継ぎ説明書

この文書は、他のAIや自動化ツールがこのリポジトリを扱うときの前提をまとめたものです。
実装の詳細よりも、何を正とし、どこを触るべきかを優先して書いています。

## 目的

このツールは、ローカル動画から字幕を作り、無音や不要区間を削り、通常ASSまたは装飾ASSと動画を出力するためのものです。SRTは文字起こし・編集互換用の内部形式として残します。

主な処理は次の順で進みます。

1. 動画を読み込む
2. 音声を抽出する
3. Whisperまたは任意のGeminiで字幕本文を作る
4. SilencedetectまたはSilero VADで発話・無音区間を解析する
5. AI校正（任意）、カット編集、字幕編集を行う
6. 編集案JSONと装飾設定を確定する
7. 軽量プレビューを確認する
8. ASSと動画を選択した形式で出力する

## このリポジトリの考え方

- 元動画は直接破壊しない
- 中心データは `edit_plan.json` と `decoration_project.json`
- 字幕本文は Whisper が担当
- 区間判定は無音検出や VAD を補助的に使う
- 最終的な編集結果は編集案を経由する
- 配布と復旧をしやすくするため、BAT と CLI を残している
- GUI はラッパー、CLI は部品実行器、core が唯一の正本
- 通常ASSは字幕スタイルだけ、装飾ASSは枠・文字連動・画面効果を含む
- 外部ASS、焼き込み、MKV字幕トラック埋め込みを別の出力モードとして扱う

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

`export` は `--subtitle-mode external|burn|embed` と `--subtitle-format plain_ass|ass|srt` を組み合わせます。新規利用では通常ASSに `plain_ass`、装飾ASSに `ass` を使い、`srt` は互換用途に限定します。

## 現在の工程

1. プロジェクト作成
2. 字幕作成・発話解析
3. Gemini AI編集（任意）
4. カット編集
5. 字幕編集
6. デコレーション編集
7. プレビュー点検
8. 動画出力

工程状態は `project.json` の `workflow`、字幕・カット・時間変換は `edit_plan.json`、装飾は `decoration/decoration_project.json` を正本にします。

## 現在の既定

- Whisper エンジン: `whisper.cpp`
- GPU/CPU 切替: `compute_profile`
- 無音・発話検出: プリセットにより `silencedetect` または Silero VAD
- 通常字幕出力: ASS
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
- 文書の優先順位は `docs/README.md` に従う
- 出力変更では通常ASSと装飾ASSの双方をテストする

## 変更前に見るべきもの

- `README.md`
- `docs/README.md`
- `docs/外部CLI連携.md`
- `docs/配布仕様書_GPLv3.md`
- `docs/spec-checklist.md`
- `docs/実装フローチャート.md`

## AI向けの要約

このプロジェクトは「ローカル動画を対象に、Whisperまたは任意のGeminiで字幕を作り、発話解析と手動編集を経て、カット済み動画とASS字幕を作る」ツールです。
修正は小さく、入口は `setup.bat` / `launch.bat` / `python -m backend` に寄せるのが基本です。
