# タスクリスト: Googleサービスアカウントによる非公開スプレッドシート統合

- [ ] `requirements.txt` に `gspread` および `google-auth` を追加
- [ ] `united_monitor.py` にサービスアカウント認証（`GCP_SERVICE_ACCOUNT_KEY`）による非公開スプレッドシート取得ロジックを追加
- [ ] `.github/workflows/run_monitor.yml` に `GCP_SERVICE_ACCOUNT_KEY` 環境変数を追加
- [ ] ドキュメント (`task.md`, `implementation_plan.md`, `walkthrough.md`) の保存
- [ ] ユーザーへGoogle Cloud Consoleでのサービスアカウント発行・スプレッドシート共有・GitHub Secret設定手順の案内
