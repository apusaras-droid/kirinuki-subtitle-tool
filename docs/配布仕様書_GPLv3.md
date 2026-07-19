# 切り抜き動画工房 配布仕様書

本書は、このリポジトリを GPLv3 系で配布するための実務仕様をまとめたものである。
法的助言ではなく、配布前の実装・同梱物・確認手順を定義する。

## 1. 配布方針

- 本プロジェクト本体は `GPL-3.0-or-later` で配布する。
- 配布物には、ソースコード、ビルド手順、第三者ライブラリのライセンス表記、必要なソース提供情報を含める。
- バイナリ配布を行う場合は、対応する完全なソースコードと、同一版を再現できる情報を同梱する。
- Windows などの「User Product」に該当する形で配布する場合は、必要なインストール情報も含める。

## 2. 本プロジェクトの対象範囲

### 2.1 GPLv3 対象

- `backend/`
- `frontend/`
- `README.md`
- `docs/`
- 配布用の起動スクリプト
- このツール固有の修正コード

### 2.2 第三者コンポーネント

- `tools/whisper.cpp/` の実行ファイル、DLL、モデル配置
- FFmpeg / FFprobe
- Python 依存パッケージ

第三者コンポーネントは本体とは別に、各ライセンス条件を満たす形で同梱または参照する。

## 3. 依存コンポーネントの扱い

### 3.1 whisper.cpp

- whisper.cpp は MIT License である。
- GPLv3 配布物に同梱可能。
- 配布時は upstream の著作権表示と MIT ライセンス文を含める。

### 3.2 FFmpeg / FFprobe

- FFmpeg は通常 LGPL で提供されるが、GPL 部品や最適化を有効にしたビルドでは GPL が適用される。
- 本プロジェクトは `--enable-gpl` を含むビルド環境を前提に扱うため、FFmpeg の同梱時は GPL 条件に従ったソース提供と通知を行う。
- 配布パッケージには、使用した FFmpeg の正確なビルド情報とソース入手方法を記録する。

### 3.3 モデルファイル

- `tools/whisper.cpp/models/*.bin` の再配布条件は、モデルごとに別確認とする。
- 配布対象に含める場合は、モデルの配布許諾、出典、バージョン、ハッシュを release note に記録する。
- 不明な場合は、本体パッケージから分離する。

### 3.4 Python パッケージ

- `requirements.txt` に列挙した依存は、各ライセンスを確認したうえで配布に含める。
- 依存のライセンス一覧は release note に追記する。

## 4. 配布物の構成

### 4.1 ソース配布物

```text
release/
  source/
    <project source tree>
  LICENSE
  licenses/
    README.md
    GPL-3.0-or-later.txt
    third_party_notices.txt
    source-offer.txt
    build-info/
      commit.txt
      environment.txt
      dependency-lock.txt
  docs/
    配布仕様書_GPLv3.md
  source.zip
```

### 4.2 バイナリ配布物

```text
release/
  app/
    backend/
    frontend/
    tools/
  LICENSE
  licenses/
    README.md
    GPL-3.0-or-later.txt
    third_party_notices.txt
    FFmpeg-notice.txt
    MIT-whisper.cpp.txt
    source-offer.txt
    build-info/
      commit.txt
      environment.txt
      dependency-lock.txt
  source-offer/
    source-url.txt
    source-checksum.txt
```

## 5. 必須ドキュメント

配布時には少なくとも以下を含める。

- GPLv3 本文またはその公式参照先
- 本体のライセンス表記
- whisper.cpp の MIT License 表記
- FFmpeg のライセンス情報
- 依存関係一覧
- ビルド方法
- ソースコード取得方法
- 問い合わせ先または保守先

## 6. 実装上の制約

- 元動画は破壊的に編集しない。
- 生成物は `projects/<project_id>/` に閉じる。
- `project.json` と `edit_plan.json` はプロジェクト内相対パスで保存する。
- 外部から受け取るパスは、プロジェクト配下かどうかを必ず検証する。
- 配布用ビルドでは、ソースコードと実行バイナリの版を一致させる。

## 7. 配布チェックリスト

1. `project.json` と `edit_plan.json` に絶対パスが残っていない。
2. `tools/whisper.cpp` の同梱物にライセンス通知が付いている。
3. FFmpeg のライセンス条件とソース提供方法が明記されている。
4. 依存パッケージのライセンス一覧が更新されている。
5. バイナリ配布時に、ソース取得方法が明記されている。
6. 再現ビルドに必要なバージョン情報が残っている。
7. モデルファイルの再配布条件を確認済みである。
8. `LICENSE` と `licenses/` のテンプレートが実配布用に埋められている。
9. 配布物に GPLv3 の正式な本文を含めている。
10. `scripts/package-release.ps1` で release 物を再現できる。

## 8. 公開前自動検査

正式公開前は次を実行する。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\preflight-release.ps1 -RunTests -BuildPackage
```

GitHubの `origin` 設定後は `-RequireRemote` も追加する。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\preflight-release.ps1 -RequireRemote -RunTests -BuildPackage
```

検査対象:

- GPLv3全文とライセンス複製の一致
- 公開必須文書と起動・セットアップBAT
- 追跡中の秘密設定、動画、モデル、実行バイナリ、アーカイブ
- Git全履歴の既知トークン形式と個人パス
- 10MiBを超えるGitオブジェクト
- PowerShell構文
- Python、Node、フロントエンド、依存整合性テスト
- `source.zip` と `app.zip` の作成
- 配布アーカイブへの非公開物混入

結果は `release/preflight-report.json` に保存する。検査失敗時はGitHub Releaseを作成しない。

## 8. 公式参照

- GPLv3: https://www.gnu.org/licenses/gpl-3.0.html
- GPLv3 速習ガイド: https://www.gnu.org/licenses/quick-guide-gplv3.html
- GPLv3 FAQ: https://www.gnu.org/licenses/gpl-faq.html
- whisper.cpp LICENSE: https://github.com/ggml-org/whisper.cpp/blob/master/LICENSE
- FFmpeg License and Legal Considerations: https://www.ffmpeg.org/legal.html
