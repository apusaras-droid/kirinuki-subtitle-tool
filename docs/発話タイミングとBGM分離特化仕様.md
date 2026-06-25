# 発話タイミングとBGM分離特化仕様

この文書は、切り抜き字幕作成ツールの中でも「発話のタイミングをどのように取るか」「BGM と台詞をどう切り分けるか」に焦点を絞って整理したものです。

字幕本文の生成よりも、字幕をいつ表示するか、どの区間を残すかを安定させるための仕様として読むことを想定しています。

## 1. この機能の目的

目的は、BGM や効果音が入った動画でも、台詞の始まりと終わりをできるだけ安定して見つけることです。

やりたいことは次の 3 つです。

1. 台詞そのものは Whisper で文字起こしする
2. 喋っている区間は VAD で検出する
3. BGM が邪魔な場合は声抽出した音声を解析に使う

重要なのは、Whisper の segment 開始時刻を「正確な発話開始」とみなさないことです。

## 2. 役割分担

### Whisper

- 台詞本文を作る
- だいたいの時刻を出す
- 字幕の素案を作る

Whisper は言葉の内容に強いが、フレーム単位の発話開始検出は得意ではありません。

### VAD

- 喋っている区間を検出する
- 無音区間の反転から発話候補を作る
- 字幕の時刻補正に使う

VAD は「誰が何を言ったか」ではなく、「今は喋っているか」を見るために使います。

### 声抽出

- BGM や効果音が強い動画で、解析用音声を作る
- VAD の誤検出を減らす
- 必要なら Whisper 側にも渡せる

声抽出音声は、最終動画の音声としては使わず、解析用に使うのが基本です。

## 3. 推奨する解析順

推奨順は次の通りです。

1. 元動画から音声を抽出する
2. 必要なら声抽出を行う
3. VAD で speech 区間を出す
4. Whisper で字幕本文を作る
5. Whisper の字幕を VAD 区間に寄せる
6. 必要なら編集案 JSON に落とす

この順番にすると、BGM に引っ張られて字幕が長く伸びる事故を減らしやすくなります。

## 4. 使う音声

### 元音声

通常の基準音声です。

- Whisper の入力
- VAD の入力
- 最終出力音声の基準

### 声抽出音声

解析補助用の音声です。

- VAD の誤反応を減らしたいときに使う
- Whisper 用に切り替えることもできる

設定例:

- `voice_isolation_enabled`
- `use_isolated_voice_for_vad`
- `use_isolated_voice_for_whisper`
- `output_audio_mode`

## 5. 発話タイミングの決め方

### 5.1 基本ルール

字幕の開始・終了は、Whisper 単独ではなく VAD を参照して補正します。

考え方は次です。

- Whisper は本文と粗い時刻
- VAD は発話区間の境界
- 両方があるなら、VAD を優先して補正する

### 5.2 ハイブリッド方式

初期設定は `hybrid` を推奨します。

ルール:

- 対応する VAD 区間がある場合
  - `corrected_start = min(whisper_start, vad_start)`
  - `corrected_end = max(whisper_end, vad_end)`
- さらに余白を足す
  - `pre_margin_sec`
  - `post_margin_sec`
- VAD がない場合
  - Whisper の時刻にフォールバックする

### 5.3 タイミング補正の記録

内部データには次を残します。

- `whisper_start_sec`
- `whisper_end_sec`
- `vad_start_sec`
- `vad_end_sec`
- `corrected_start_sec`
- `corrected_end_sec`

これにより、あとで「Whisper が遅れたのか」「VAD が広く取ったのか」を追跡できます。

## 6. 典型的な失敗と対策

### 6.1 BGM に字幕が引っ張られる

症状:

- 喋っていないのに字幕が出る
- 台詞終了後も字幕が長く残る
- BGM の入りと字幕の開始が一致する

対策:

- `use_isolated_voice_for_vad = true`
- `detection_mode = vad` または `hybrid`
- `pre_margin_sec` と `post_margin_sec` を小さく見直す

### 6.2 Whisper の開始が遅い

症状:

- 台詞の頭が欠ける
- 「あ」「えー」の前に字幕が入らない

対策:

- Whisper の時刻をそのまま信じない
- VAD の開始時刻を使う
- `pre_margin_sec` を少し足す

### 6.3 無音に近い BGM で VAD が広がる

症状:

- ずっと喋っている判定になる
- 区間がつながりすぎる

対策:

- 声抽出音声を VAD に使う
- `vad_threshold` を見直す
- `merge_silence_gap_sec` を詰めすぎない

## 7. 設定項目

この機能で重要な設定は次です。

- `detection_mode`
  - `silencedetect`
  - `vad`
  - `hybrid`
- `voice_isolation_enabled`
- `voice_isolation_engine`
- `use_isolated_voice_for_vad`
- `use_isolated_voice_for_whisper`
- `pre_margin_sec`
- `post_margin_sec`
- `min_speech_duration_sec`
- `merge_silence_gap_sec`
- `silence_threshold_db`
- `vad_threshold`

## 8. 実装上の基準

### 8.1 字幕本文

字幕本文は Whisper の結果を使います。

### 8.2 字幕時刻

字幕時刻は VAD を優先して補正します。

### 8.3 切り抜き区間

切り抜き区間は、喋っている区間を基準に作ります。

### 8.4 最終出力

最終動画のカットは、Whisper の時刻ではなく、補正済みの発話区間を基準にします。

## 9. 解析ログ

トラブル調査のため、最低でも次を残します。

- Whisper の入力音声パス
- VAD の入力音声パス
- 検出した speech 区間
- 補正前字幕
- 補正後字幕
- keep segments

これがあると、BGM が原因なのか、Whisper が原因なのか、VAD の閾値設定なのかを分けて確認できます。

## 10. 他 AI への短い指示文

この機能は、Whisper で字幕本文を作り、VAD で発話区間を検出し、必要なら声抽出音声で VAD を補助する。
Whisper の segment 開始時刻を正確な発話開始として扱わず、字幕の表示時刻と切り抜き区間は VAD を優先して補正する。
解析ログには Whisper 時刻、VAD 時刻、補正後時刻を必ず残す。

