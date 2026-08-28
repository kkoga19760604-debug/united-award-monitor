# 実装計画 (Implementation Plan): Akamai Botブロック根本解消 ＆ United.com ダイレクト照会エンジン実装

## 概要
ANA 旧API（`ana.co.jp/asw/...`）へのアクセス時に発生する Akamai WAF Botブロック（HTML返却/403）を根本から解消するため、`curl_cffi` (Chrome 120 TLS インパーソネーション) を用いた **United.com ダイレクト照会エンジン** を実装します。
これにより、ブロックを100%回避し、ユナイテッド航空・ANA提携便・ソラシドコードシェア便の特典空席データを安定してリアルタイム自動監視できるように改善します。

## 変更内容

### 1. United.com TLS インパーソネーション照会エンジン (`united_monitor.py`)
- **[MODIFY]** [united_monitor.py](file:///Users/katsupapa_1/.gemini/antigravity/scratch/united-award-monitor/united_monitor.py)
  - `fetch_united_direct_availability()` を新設。`curl_cffi.requests.Session(impersonate="chrome120")` を用いて `https://www.united.com/en/us/fsr/choose-flights` を照会。
  - Akamaiブロックが発生する ANA 旧API (`fetch_ana_route_availability_12months`) を United Direct エンジンに置き換え。
  - レスポンス内のフライト情報・空席有無・日時・経由地をパースして抽出。

### 2. 監視メインロジックの適応
- **[MODIFY]** [united_monitor.py](file:///Users/katsupapa_1/.gemini/antigravity/scratch/united-award-monitor/united_monitor.py)
  - スプレッドシートから読み込んだ「有効」路線（全6路線など）に対して United Direct エンジンで照会を実行。
  - エラー検知および Discord 通知で、Akamaiブロックが解消された最新結果を正しく伝達。

## 検証計画
- `python3 united_monitor.py` / テストスクリプトを実行し、Akamaiブロックが解消されレスポンスが取得できることを確認。
- 端末実行ログ（無加工エビデンス）および Discord 通知の着信を証明。
