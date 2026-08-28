# 実装計画 (Implementation Plan): 全自動高速監視システム 厳格遵守・不整合解消

## 概要
「ユナイテッド＆ソラシド統合特典航空券 全自動高速監視システム」の開発運用指示プロンプトで定められた【絶対禁止事項】および【動作仕様】に基づき、コード内の既存の不整合・偽装ロジック・エラー隠蔽コードを完全に排除します。

## 修正対象コンポーネント

### 1. スプレッドシート取得エンジン (`united_monitor.py` - `get_sheet_targets`)
- **[MODIFY]** [united_monitor.py](file:///Users/katsupapa_1/.gemini/antigravity/scratch/united-award-monitor/united_monitor.py)
  - 公開CSV URLおよびpubhtmlの試行コード（優先度2・3）を完全削除。
  - GCPサービスアカウント（`GCP_SERVICE_ACCOUNT_KEY`）認証のみを使用。
  - 認証失敗・シート取得失敗時にハードコードの予備データ（6路線）へ勝手に切り替える誤魔化しロジックを完全削除。失敗時は明確なエラーを出力して終了。
  - 「ステータス: 有効」の路線のみを抽出・動的カウント。

### 2. 空席照会エンジン ＆ エラー追跡 (`united_monitor.py` - `fetch_ana_route_availability_12months`, `check_united_seats_free`)
- **[MODIFY]** [united_monitor.py](file:///Users/katsupapa_1/.gemini/antigravity/scratch/united-award-monitor/united_monitor.py)
  - 通信エラー（`__COMM_ERROR__`）およびAkamaiブロック（`__AKAMAI_BLOCKED__`）の戻り値を各路線ごとのステータスとして完全に保持。
  - 照会失敗が一度でも発生した路線には「API照会エラー/ブロック検知」フラグを設定。

### 3. レポート生成・Discord通知エンジン (`united_monitor.py` - `send_discord_summary_notification`)
- **[MODIFY]** [united_monitor.py](file:///Users/katsupapa_1/.gemini/antigravity/scratch/united-award-monitor/united_monitor.py)
  - 通信エラーやAkamaiブロックが発生した路線を「空席 0 件」と偽って報告することを100%防止。
  - エラー路線は「⚠️ 照会エラー (Akamaiブロック/通信失敗)」と正しくログおよびDiscord通知に出力。
  - ユナイテッド 337日前ルール（本日+337日先）およびソラシド確定枠上限（2026-10-24まで）を超えた指定日は「未発売枠 (予約開始前)」と表示。

## 検証計画
- `python united_monitor.py` を実行し、無加工の端末出力ログ（客観的エビデンス）を収集・検証。
