# ユナイテッド航空 ＆ ソラシドエア 特典航空券 統合自動監視システムの構築計画

Googleスプレッドシートのプルダウン管理（対象航空会社・時間帯・対象期間・曜日）に対応し、ユナイテッド航空（ANA便）およびソラシドエアの特典空席を12ヶ月通年で全自動監視し、Discordへ分かりやすく一括通知するシステムへ機能拡張します。

## User Review Required

> [!IMPORTANT]
> スプレッドシートのレイアウトに **「対象航空会社」** 列と **「希望時間帯」** 列の2列を追加いたします。
> プルダウン（選択肢）で手軽かつミスなく設定を選べるようになります。

## Proposed Changes

### 1. スプレッドシートパース・条件判定機能の強化

#### [MODIFY] [united_monitor.py](file:///Users/katsupapa_1/.gemini/antigravity/scratch/united_award_monitor/united_monitor.py)

- **プルダウン項目に対応したパース機能の追加**:
  - `対象航空会社`: `すべて` / `ユナイテッド` / `ソラシド`
  - `希望時間帯`: `全時間帯` / `午前便` (〜12:00) / `午後便` (12:00〜) / `夕方以降` (17:00〜) / `夜便` (19:00〜)
  - `対象条件`: `金土日`, `日祝`, `土日祝`, `全日`, `YYYY-MM-DD`, `◯月以降` など
- **時間帯判定関数 `matches_time_condition(time_str, condition)` の実装**:
  - 出発時刻を取得し、指定された時間帯に一致する場合のみ空席として抽出。

### 2. ソラシドエア照会エンジンの追加・統合

#### [NEW] [solaseed_checker.py](file:///Users/katsupapa_1/.gemini/antigravity/scratch/united_award_monitor/solaseed_checker.py) または モジュール統合
- ソラシドエア公式照会API / ANAコードシェア照会を利用し、ソラシド運航便（SNJ/SNA）の12ヶ月通年空席データを全自動取得。

### 3. Discord Embed 通知の強化

- ユナイテッド航空とソラシドエアの空席レポートをそれぞれ分かりやすいデザインで発行：
  - ✈️ **【United特典空席 12ヶ月全レポート】**
  - 🥑 **【ソラシド特典空席 12ヶ月全レポート】**
- 時間帯（例: `[18:15発]`）や便名を正確に表示。

---

## Verification Plan

### Automated / Local Tests
- ローカル環境で `python3 united_monitor.py` を実行し、ユナイテッドおよびソラシドの照会・時間帯フィルタリング・Discord通知が正常に完了するか検証。

### Manual Verification
- GitHub への Push 完了後、GitHub Actions で手動実行（Run workflow）をキックし、エラーなく終了するかおよび Discord チャンネルへ正常通知されるか確認。
