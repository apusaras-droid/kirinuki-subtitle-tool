# 切り抜き動画工房 工程分割UI適用方針

この文書は `工程分割型UI_AI実装仕様書_圧縮版_v2.2` を、本アプリへ適用するための固定契約です。

## 1. アプリ定義

```yaml
app_id: kirinuki-video-studio
name: 切り抜き動画工房
purpose: ローカル動画を入力し、字幕、カット案、装飾を確認して動画と字幕を出力する
user: 動画編集ソフトに不慣れな利用者を含むローカルPC利用者
input: ローカル動画、保存済みプロジェクト
output: MP4またはMKV、SRTまたはASS、edit_plan.json、プロジェクトJSON
non_goals: クラウド処理、SNS投稿、複数動画のGUI一括処理
steps: [STEP_PROJECT, STEP_TRANSCRIBE, STEP_AI_SUBTITLE, STEP_CUT, STEP_SUBTITLE_EDIT, STEP_DECORATION, STEP_PREVIEW, STEP_EXPORT]
recommended_preset: PRESET_STANDARD
side_effects: プロジェクト作成、解析成果物保存、プレビュー生成、最終出力
persistence: local
network: optional (Gemini文字起こし・校正・作品DB検索を使う場合のみ)
environment: local_web
display:
  monitor: 21-inch
  resolution: 1920x1080
  orientation: landscape
  os_scale: 100%
  browser_zoom: 100%
  compatibility_viewport: 1536x864
```

## 2. 工程契約

```text
STEP_PROJECT | SCREEN_PROJECT | 動画選択または作業再開 | 常時 | project_idとsource_videoが有効 | STEP_TRANSCRIBE以降
STEP_TRANSCRIBE | SCREEN_TRANSCRIBE | 字幕と初期カット案の生成 | 有効なプロジェクト | transcriptとedit_planが有効 | STEP_AI_SUBTITLE以降
STEP_AI_SUBTITLE | SCREEN_AI_SUBTITLE | Geminiによる字幕校正・カット提案 | 字幕が存在 | 提案を採用または工程をスキップ | STEP_CUT以降
STEP_CUT | SCREEN_CUT | 字幕を見ながら不要区間を編集 | edit_planと字幕が存在 | カット後のedit_planとチャプターが保存済み | STEP_SUBTITLE_EDIT以降
STEP_SUBTITLE_EDIT | SCREEN_SUBTITLE_EDIT | カット後タイムラインの字幕本文と発話時刻を確定 | カット済みedit_planが存在 | edited subtitlesが保存済み | STEP_DECORATION以降
STEP_DECORATION | SCREEN_DECORATION | テキスト・枠・効果の確定 | 編集対象字幕が存在 | decoration_projectが保存済み | STEP_PREVIEW以降
STEP_PREVIEW | SCREEN_PREVIEW | 軽量動画による最終点検 | edit_planが有効 | 現在の入力に対するpreviewが生成済み | STEP_EXPORT
STEP_EXPORT | SCREEN_EXPORT | 出力形式を確定して書き出す | edit_planが有効 | outputが正常終了 | なし
```

## 3. 画面契約

```text
SCREEN_PROJECT | project list, file input | project.json | プロジェクトを作成 | 動画形式と読込可否 | empty/loading/ready/error | 字幕・装飾設定
SCREEN_TRANSCRIBE | project, source range, analysis preset | transcript/edit_plan | 字幕とカット案を作成 | 音声、範囲、実行環境 | empty/loading/ready/error | 装飾・最終出力
SCREEN_AI_SUBTITLE | audio, subtitles, knowledge base | Gemini proposal | 任意校正を採用またはスキップ | API設定、提案内容 | empty/loading/ready/error | 元動画の破壊的変更
SCREEN_SUBTITLE_EDIT | edit_plan subtitles | edit_plan/edited.srt | 編集内容を確定 | 時刻順序、本文、範囲 | empty/ready/invalid/success | Whisper実行設定
SCREEN_CUT | edit_plan, source video, confirmed subtitles | edit_plan/project scenes | カットを確定 | カット範囲、保護範囲、時間再計算 | empty/ready/invalid/success | 字幕本文・装飾
SCREEN_DECORATION | subtitles, shared presets | decoration_project.json | 装飾を確定 | 字幕イベントとの対応 | empty/ready/invalid/success | 文字起こし再実行
SCREEN_PREVIEW | edit_plan, decoration snapshot | preview video | 軽量プレビューを作成 | 入力の有効性 | empty/loading/success/error | 正本の直接変更
SCREEN_EXPORT | confirmed snapshot, output preset | output files | 最終出力を実行 | 出力先、形式、スナップショット | ready/loading/success/error | 字幕・装飾の直接編集
```

## 4. 状態と正本

- `project.json`: プロジェクト情報、UI設定、`workflow`。
- `edit_plan.json`: 字幕、カット、保護区間、時間変換の正本。
- `decoration/decoration_project.json`: テキスト、枠、文字連動、画面効果の正本。
- `workflow`: 工程状態と実行スナップショットのメタデータ。業務データを複製しない。
- 画面は正本から再構築し、DOMだけに確定値を保持しない。

標準工程状態は `not_started`, `current`, `valid`, `invalidated`, `completed`, `blocked`, `error` とする。

## 5. 無効化規則

| 変更 | 無効化する工程 |
|---|---|
| プロジェクト名 | なし |
| 元動画、対象範囲、Whisper/VAD設定 | `STEP_TRANSCRIBE` 以降 |
| 手動カット、保護区間 | `STEP_CUT` 以降 |
| 字幕本文、字幕時刻、手動カット、保護区間 | `STEP_DECORATION` 以降 |
| 装飾設定 | `STEP_PREVIEW` 以降 |
| プレビュー方式 | `STEP_PREVIEW` のみ |
| 出力形式 | `STEP_EXPORT` のみ |

後工程のファイルは即時削除しない。状態だけを `invalidated` にし、再実行可能な形で保持する。

## 6. 実行スナップショット

最終出力開始時に次をJSON互換データとして固定する。

- project_idと元動画識別情報
- source_range
- edit_planのrevisionまたは署名
- decoration_projectのrevisionまたは署名
- 出力モードと出力プロファイル
- 実行開始日時（タイムゾーン付きISO 8601）

実行中に画面値が変わっても、開始済み処理の引数は変更しない。

## 7. 移行方針

1. 既存の処理関数を維持したまま、工程状態ストアと工程ナビゲーションを追加する。
2. プロジェクト作成と出力を独立画面へ移す。
3. `app.js` から工程ごとにcontrollerとvalidationを分離する。
4. GUIとCLIが同じcore関数を呼ぶことを工程単位で確認する。
5. 一工程ごとに受入確認してコミットする。全面書き換えは行わない。

## 8. 記録済み仮定

- 設定画面とプロジェクト一覧は補助画面であり工程ではない。
- 廃止済みの独立シーン編集工程は復活させない。
- 字幕一件を装飾上の一シーンとして扱う既存仕様を維持する。
- 標準プレビューは既存の軽量レンダーを使い、最終出力と同じ正本を入力にする。
- 既存プロジェクトは成果物の有無から初期工程状態を復元する。
