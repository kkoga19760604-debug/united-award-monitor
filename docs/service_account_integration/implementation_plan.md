# 実装計画: Google サービスアカウントによる非公開スプレッドシート統合

スプレッドシートを**完全非公開（アクセス制限付き）**のまま運用できるように、Google サービスアカウント（認証キー）を用いた自動読み込み機能を実装します。

## 変更の要約
1. **`requirements.txt` の更新**: `gspread` および `google-auth` を依存関係に追加。
2. **`united_monitor.py` の改修**: 環境変数 `GCP_SERVICE_ACCOUNT_KEY`（JSON文字列）から認証情報を生成し、`gspread` 経由で非公開スプレッドシートのデータを安全にパースする処理を組み込み。
3. **`.github/workflows/run_monitor.yml` の改修**: GitHub Secrets (`GCP_SERVICE_ACCOUNT_KEY`) をステップ内の環境変数として渡す設定を追加。

---

## 提案する変更内容

### 依存関係

#### [MODIFY] [requirements.txt](file:///Users/katsupapa_1/.gemini/antigravity/scratch/united_award_monitor/requirements.txt)
- `gspread`
- `google-auth`

---

### プログラム・ワークフロー

#### [MODIFY] [united_monitor.py](file:///Users/katsupapa_1/.gemini/antigravity/scratch/united_award_monitor/united_monitor.py)
- `gspread` および `google.oauth2.service_account` のインポート処理（オプショナル）を追加。
- [`get_sheet_targets()`](file:///Users/katsupapa_1/.gemini/antigravity/scratch/united_award_monitor/united_monitor.py#L208) を拡張：
  - `GCP_SERVICE_ACCOUNT_KEY` が設定されている場合、JSONを読み込んでサービスアカウント認証を実施し、指定の `SPREADSHEET_ID` のワークシートから行データを取得。
  - 認証キーがない場合は従来通りウェブ公開CSV URL試行およびフォールバック処理を継続。

#### [MODIFY] [run_monitor.yml](file:///Users/katsupapa_1/.gemini/antigravity/scratch/united_award_monitor/.github/workflows/run_monitor.yml)
- `Run United Monitor Script` ステップの `env` に `GCP_SERVICE_ACCOUNT_KEY: ${{ secrets.GCP_SERVICE_ACCOUNT_KEY }}` を追加。

---

## ユーザー側での準備・設定手順（設定ガイド）

実装後、ユーザー様側で以下の3ステップを設定いただくことで完全非公開運用が開始されます：

1. **Google Cloud Console でサービスアカウント作成**:
   - サービスアカウントを作成し、JSON形式の秘密鍵ファイルをダウンロード。
2. **スプレッドシートへ権限付与**:
   - 発行されたサービスアカウントのメールアドレス（例: `xxx@xxx.iam.gserviceaccount.com`）を、スプレッドシートの「共有」に **閲覧者** として追加。
3. **GitHub Secrets への登録**:
   - GitHubリポジトリの `Settings` ➔ `Secrets and variables` ➔ `Actions` にて、Secret 名 `GCP_SERVICE_ACCOUNT_KEY` としてダウンロードしたJSONテキスト全文を登録。

---

## 検証計画

### 自動 / ローカルテスト
- `united_monitor.py` のパース処理および認証試行部分の単体実行テスト。
- `git status` およびコード構文チェック。
