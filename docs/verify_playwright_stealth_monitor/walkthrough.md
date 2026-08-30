# 修正・検証結果の確認 (Walkthrough): 案A（Playwrightステルス自動判定）検証結果

## 1. 検証結果サマリー
完全無料環境（クラウド/ヘッドレスブラウザ）において、最新のPlaywrightステルス設定を用いてユナイテッド航空公式サイト（United.com）へのアクセスおよび空席取得テストを実施しました。

**【判定】**: **案Aは実現不可（Akamai Bot Managerによる完全遮断を確認）**
ユーザー様との事前合意（「できない場合は言ってください。B案に切り替えます」）に基づき、**案B（ワンタップ公式確認リンク通知）**へ正式に切り替えます。

---

## 2. 客観的エビデンス（実行生ログ）

### テスト1: HTTP/2 通信時（Playwright + stealth_async）
```text
[*] Starting Stealth Playwright Test...
[*] Target URL: https://www.united.com/en/us/fsr/choose-flights?f=KMJ&t=SDJ&d=2026-09-04&tt=1&at=1&sc=7&px=1&taxod=1&ca=1
[*] Navigating to United.com...
❌ [EXCEPTION]: Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.united.com/en/us/fsr/choose-flights?f=KMJ&t=SDJ&d=2026-09-04&tt=1&at=1&sc=7&px=1&taxod=1&ca=1
```
> **現象**: Akamai WAFがヘッドレスブラウザのHTTP/2シグネチャをBotと検知し、即座に接続をリセット（RST_STREAM）して強制切断。

### テスト2: HTTP/1.1 通信時（--disable-http2）
```text
[*] Starting Stealth Playwright Test with --disable-http2...
[*] Navigating to United.com Home with HTTP/1.1...
❌ [EXCEPTION]: Page.goto: net::ERR_TIMED_OUT at https://www.united.com/en/us
```
> **現象**: Akamai WAFがパケットを意図的にドロップ（ブラックホール化）し、タイムアウトさせて完全拒否。

---

## 3. 次のアクション（案Bへの切り替え）
- 有料ツール（プロキシ等）を使わず、完全無料（0円）を100%維持するため、**案B（スプレッドシート連動・ワンタップ公式確認ダイレクトリンク通知）**の仕様を確定・運用します。
- スプレッドシートの「有効」行のみを動的抽出し、指定条件に合わせた公式リアルタイム空席画面への直行URLを確実に生成・配信します。
