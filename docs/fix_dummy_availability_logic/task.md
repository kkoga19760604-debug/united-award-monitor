# タスクリスト: 特典航空券空席判定ロジックのダミーコード完全撤去と100%精度化

## 概要
`united_monitor.py` において、通信エラー時や未発売期間中に全日付・全土日を強制的に「空席あり（True）」にする危険なハードコード（ダミー判定）が残存していた問題を解決する。

## タスク
- [ ] `united_monitor.py` の `fetch_ana_route_availability_12months` から強制 `month_map[d_fmt] = True` を完全削除
- [ ] `united_monitor.py` の `fetch_solaseed_route_availability_12months` における土日強制 `True` 設定の完全削除と、実空席データのみ判定するクリーンロジックへの置き換え
- [ ] 予約発売開始前期間（ダイヤ未確定期間）および受信用枠外の厳格除外
- [ ] ローカル環境での動作テストと検出件数（リアル件数）の検証
- [ ] GitHub リポジトリ（main ブランチ）へ修正内容をコミット・Push
