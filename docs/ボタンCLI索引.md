# ボタンCLI索引

この索引は、GUI のボタンから対応する CLI / API / 正本ファイルへ素早く辿るための一覧です。

## 1. 編集画面

| ボタン | CLI / API | 正本 |
|---|---|---|
| 動画を選択 / 読み込み | `new-project` | `project.json` |
| 動画情報取得 | `probe` | `project.json` |
| 音声を抽出 | `extract-audio` | `audio/source_range.wav` |
| 文字起こしを実行 | `transcribe` | `transcript/transcript.json` |
| 無音区間を検出 | `detect-silence` | `transcript/transcript.json` |
| カット案を作成 | `create-edit-plan` | `edit_plan.json` |
| 字幕を保存 | `save-subtitles` | `edit_plan.json` / `subtitles/edited.srt` |
| 英語字幕を日本語へ翻訳 | `translate-subtitles` / `POST /api/ai/gemini/translate-subtitles` | `transcript/transcript.json` / `edit_plan.json` / `subtitles/edited.srt` |
| 仮出力を作成 | `preview` | `preview/preview_low.mp4` |
| 手動カットを仮出力 | `preview` の前に `edit_plan.json` 更新 | `edit_plan.json` |
| 最終出力 | `export` | `output/final.*` |

## 2. 波形編集

| ボタン | CLI / API | 正本 |
|---|---|---|
| 開始位置に設定 | GUI 補助 | `edit_plan.json` |
| 終了位置に設定 | GUI 補助 | `edit_plan.json` |
| 現在の開始/終了を区間に反映 | GUI 補助 | `edit_plan.json` |
| 10分で分割 / 15分で分割 / 20分で分割 / 30分で分割 | GUI 補助 | `edit_plan.json` |
| カット開始 | GUI 補助 | `edit_plan.json.manual_cut_segments` |
| カット終了 | GUI 補助 | `edit_plan.json.manual_cut_segments` |
| 選択解除 | GUI 補助 | UI 状態 |
| 最後を削除 | GUI 補助 | `edit_plan.json.manual_cut_segments` |

## 3. プロジェクト一覧

| ボタン | CLI / API | 正本 |
|---|---|---|
| 再読込 | `GET /api/projects` | `projects/*/project.json` |
| 開く | `GET /api/projects/{id}` 相当 | 対象プロジェクト |
| 削除 | GUI 管理操作 | プロジェクトディレクトリ |

## 4. 設定画面

| ボタン / 項目 | CLI / API | 正本 |
|---|---|---|
| VADを使う | `transcribe` / `detect-vad` | `project.json.ui_state` / `transcript.json` |
| 声抽出を使う | `transcribe` の前処理 | `transcript.json` |
| 計算プロファイル | `--compute-profile` | `project.json.ui_state` |
| Whisper engine / model | `transcribe --engine --model` | `project.json.ui_state` |
| 出力プリセット | `export --output-profile` | `project.json.ui_state` |
| 字幕フォント / サイズ / 黒縁 | `export --burn-subtitles` の見た目 | `project.json.ui_state` |

## 5. デコレーション画面

| ボタン | CLI / API | 正本 |
|---|---|---|
| 字幕から生成 | `/api/projects/{id}/decoration` 生成 | `decoration/decoration_project.json` |
| 現在字幕からセット作成 | GUI 補助 | `decoration/decoration_project.json` |
| ASS出力 | `build_decoration_ass` / `/api/decoration/ass` | `decoration/decoration_project.json` |
| 保存 | `/api/projects/decoration` | `decoration/decoration_project.json` |
| JSON出力 | decoration export | `decoration/decoration_project.json` |

## 6. プレビュー点検ページ

| ボタン | CLI / API | 正本 |
|---|---|---|
| 480p/15秒点検プレビュー | `render_decoration_video` / `/api/decoration/render` | `preview/decorated_preview.mp4` |
| 現在字幕だけ480p | `render_decoration_video` / `/api/decoration/render` | `preview/decorated_preview.mp4` |
| 240p/3fps軽量プレビュー | `/api/decoration/render` (`max_height=240`, `fps=3`) | `preview/decorated_preview.mp4` |
| 再生 / 停止 | GUI 補助 | UI 状態 |
| デコレーションへ戻る | GUI 補助 | UI 状態 |

## 7. 出力ルート

| ボタン | CLI / API | 正本 |
|---|---|---|
| 仮出力を作成 | `preview` | `preview/preview_low.mp4` |
| 手動カットを仮出力 | `preview` へ manual cut を反映 | `edit_plan.json` |
| 最終出力 | `export` | `output/final.*` |
| 通常ASS / 装飾ASSを別ファイル | `export --subtitle-mode external --subtitle-format plain_ass/ass` | `output/final.ass` |
| 通常ASS / 装飾ASSを焼き込む | `export --subtitle-mode burn --subtitle-format plain_ass/ass` | `output/final.*` |
| ASS字幕トラックを埋め込む | `export --subtitle-mode embed --subtitle-format plain_ass/ass` | MKV (`ass`) |

## 8. 迷ったとき

1. ボタン名を見る
2. API 名を見る
3. CLI 名を見る
4. 正本ファイルを見る
5. それでも分からなければ `docs/相関関係メモ.md` を見る
6. 工程を分解したいなら `docs/部品単位工程管理ルール.md` を見る

## 9. いまGUI専用のもの

次の操作は、現時点では「確認・編集の便宜」であり、CLI へ直結していない。

- `プロジェクト一覧`
- `編集画面` / `設定画面` / `デコレーション画面` の画面切替
- `プレビュー点検` の画面切替
- `再生 / 停止`
- `開始位置に設定` / `終了位置に設定`
- `カット開始` / `カット終了`
- `選択解除`
- `最後を削除`
- `字幕の scene_id を再割当`
- `選択中字幕へ適用`
- `既定値に戻す`
- `装飾プレビュー` の再生操作

## 10. CLI化候補

将来的に core に寄せやすいのは次の操作。

- `保存` 系の細分化
- `字幕から生成`
- `現在字幕からセット作成`
- `ASS出力`
- `JSON出力`
- `手動カットを仮出力`
- `出力プリセット` の個別保存
- `共通へ保存`
- `プロジェクト保存` と `上書き保存` の差分整理

## 11. ルール補足

- GUI専用は UI の状態遷移に近い
- CLI化候補は core の入出力に落としやすい
- まずは「正本がどれか」を優先して分ける
- 1 ボタン 1 副作用を基本にして、複数副作用は工程分割する
- 不要要素は本体ではなく decoration / preset / optional 側へ寄せる
