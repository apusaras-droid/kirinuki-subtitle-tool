# 外部CLI連携

このツールは `python -m backend` からCLI実行できます。
他のプログラムからは、JSON設定をファイルに出して `run-pipeline` を呼ぶのが最も安定です。
CLI は GUI の別実装ではなく、同じ core 処理を部品単位で呼ぶ入口です。

## 入口

```powershell
python -m backend --help
```

利用可能な主なコマンド:

- `probe`
- `new-project`
- `extract-audio`
- `transcribe`
- `detect-silence`
- `create-edit-plan`
- `save-subtitles`
- `preview`
- `export`
- `cleanup`
- `run-pipeline`

## 推奨フロー

1. `new-project` でプロジェクトを作る
2. `extract-audio` で音声を切り出す
3. `transcribe` で字幕本文を作る
4. `detect-silence` で無音区間を取る
5. `create-edit-plan` でカット案を作る
6. `preview` で仮出力を作る
7. `export` で最終出力を作る

## 設計の前提

- GUI は実行結果のビューア兼編集器
- CLI は自動化向けの部品実行器
- core が唯一の業務ロジック
- `edit_plan.json` と `decoration_project.json` を正本にする
- 画面装飾は GUI 専用表現と export 反映用表現を分けて管理する

外部プログラムからまとめて回すなら `run-pipeline` を使います。
ドラッグ&ドロップ用の preset 定義は `scripts/process-video.presets.json` にあります。

## 例1: 動画情報取得

```powershell
python -m backend probe --video "input.mp4"
```

返り値は JSON です。

## 例2: プロジェクト作成

```powershell
python -m backend new-project --video "input.mp4" --name "sample"
```

## 例3: 音声抽出

```powershell
python -m backend extract-audio --project-id "project_xxx" --video-path "input.mp4" --start 0 --end 600 --compute-profile gpu
```

## 例4: 文字起こし

```powershell
python -m backend transcribe --project-id "project_xxx" --audio-path "projects/project_xxx/audio/source_range.wav" --language ja --model large-v3 --engine whisper.cpp --compute-profile gpu
```

## 例5: 無音検出

```powershell
python -m backend detect-silence --project-id "project_xxx" --audio-path "projects/project_xxx/audio/source_range.wav" --threshold-db -35 --min-silence-duration 0.7 --compute-profile gpu
```

## 例6: カット案作成

```powershell
python -m backend create-edit-plan --project-id "project_xxx" --source-start 0 --source-end 600 --settings-json "{\"auto_cut\":true}"
```

## 例7: 字幕保存

```powershell
python -m backend save-subtitles --project-id "project_xxx" --subtitles-json "subtitles.json"
```

## 例8: 仮出力 / 最終出力

```powershell
python -m backend preview --project-id "project_xxx"
python -m backend export --project-id "project_xxx" --burn-subtitles
python -m backend cleanup --project-id "project_xxx" --keep-preview
```

## 例9: 一括実行

```powershell
python -m backend run-pipeline --config "docs/cli-run-pipeline.sample.json" --report "logs/report.json" --auto-cleanup
```

`run-pipeline` の設定は JSON ファイルで渡すのが推奨です。

主なキー:

- `video`
- `name`
- `start`
- `end`
- `language`
- `model`
- `engine`
- `compute_profile`
- `detection_mode`
- `voice_isolation_enabled`
- `use_isolated_voice_for_vad`
- `use_isolated_voice_for_whisper`
- `auto_cut`
- `burn_subtitles`
- `subtitles`
- `auto_cleanup`
- `keep_audio`
- `keep_preview`
- `keep_analysis`
- `keep_raw_subtitles`

## 出力

処理結果は主に次へ保存されます。

- `projects/<project_id>/project.json`
- `projects/<project_id>/edit_plan.json`
- `projects/<project_id>/subtitles/original.srt`
- `projects/<project_id>/subtitles/edited.srt`
- `projects/<project_id>/preview/preview_low.mp4`
- `projects/<project_id>/output/final.mp4`
- `projects/<project_id>/output/final.srt`

## ログ

- `logs/app_audit.jsonl`
- `projects/<project_id>/temp/logs/audit.jsonl`
- `projects/<project_id>/temp/logs/processing.jsonl`

外部プログラムは `run-pipeline` の標準出力 JSON を読めば、各段の結果をそのまま扱えます。
