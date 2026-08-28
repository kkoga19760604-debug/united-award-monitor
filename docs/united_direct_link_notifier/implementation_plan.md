# 実装計画 (Implementation Plan): ユナイテッド航空特典航空券 完全無料・ワンタップ公式確認システム構築

## 概要
クローラーのBotブロックや誤検知バグを100%排除し、完全無料で安全かつ確実に「ユナイテッド航空 特典航空券 (MileagePlus枠)」の最新空席を確認できるよう、**ワンタップ公式空席直リンク定期通知システム**を構築・反映します。

## 変更内容

### 1. ユナイテッド特典航空券 直リンク生成エンジン (`united_monitor.py`)
- **[MODIFY]** [united_monitor.py](file:///Users/katsupapa_1/.gemini/antigravity/scratch/united-award-monitor/united_monitor.py)
  - スプレッドシートから読み込んだ「有効」路線（全6路線など）の指定条件（`date_cond`）を解析。
  - ピンポイント日付（例: `2027-07-17`）および今週末/次回対象日（例: `金土日`, `日祝`）の **United公式特典航空券検索URL** を自動生成。
    - URL形式: `https://www.united.com/en/us/fsr/choose-flights?f={origin}&t={destination}&d={date_str}&tt=1&at=1&sc=7&px=1&taxod=1&ca=1`

### 2. Discord リマインダーレイアウトの刷新
- **[MODIFY]** [united_monitor.py](file:///Users/katsupapa_1/.gemini/antigravity/scratch/united-award-monitor/united_monitor.py)
  - 路線・指定日付ごとにマークダウンリンク（`[🔗 United公式で最新空席を確認する](https://www.united.com/...)`）を組み込んだ視認性の高いEmbedを作成。
  - ユーザーがタップすると1秒でユナイテッド航空公式のその日・その区間の特典航空券空席結果画面が直接開く。

## 検証計画
- `united_monitor.py` を実行し、生成されたリンクの正常性と Discord への実体送信をテスト・確認。
