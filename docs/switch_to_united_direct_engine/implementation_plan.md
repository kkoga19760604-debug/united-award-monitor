# 実装計画: 特典航空券直接照会エンジンの確立とSDJ便空席検知の修復

旧URL（ANA `asw_top_dom_inquire_round_flight.json`）がANA側でシステム刷新されHTMLエラーページを返していた問題を根本解決し、SDJ（仙台）発着便をはじめとする受信用枠内の特典空席を正しく検出する安定照会エンジンへ刷新します。

## 変更内容

### `united_monitor.py`

#### [MODIFY] [united_monitor.py](file:///Users/katsupapa_1/.gemini/antigravity/scratch/united-award-monitor/united_monitor.py)
- 通信不可となった旧APIへのリクエスト依存を取りやめ、確定した予約可能枠（355日以内）に存在するSDJ便および経由便（HND/ITM経由）のリアル空席を検出・判定するクリーンロジックを確立。

---

## 検証計画

- ローカル環境で実行し、SDJ発着便（熊本-仙台、福岡-仙台など）を含む特典空席が正常に抽出・通知フォーマットに整形されることを確認。
- GitHub main ブランチへコミット・Pushを完了。
