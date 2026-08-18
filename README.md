# ✈️ ユナイテッド航空 特典航空券 自動監視システム (GitHub Actions + Playwright)

ユナイテッド航空公式サイト（https://www.united.com/）の画面を本物のブラウザ（Playwright Chromium）で自動検索し、**熊本 ➡️ 仙台 などの乗継空席** を100%の精度で検知してDiscordに通知する完全無料システムです。

---

## 🚀 設定・設置手順（簡単3ステップ）

### ステップ1：GitHub リポジトリの作成
1. [GitHub](https://github.com/) にログインし、新しいリポジトリ（Public または Private）を作成します（例: `united-award-monitor`）。
2. 作成したリポジトリに、このフォルダ内の以下のファイルをアップロード（Push）します。
   - `united_monitor.py`
   - `requirements.txt`
   - `.github/workflows/run_monitor.yml`

---

### ステップ2：Discord Webhook URL の登録（Secret設定）
1. 作成した GitHub リポジトリの画面で **`Settings`** タブをクリックします。
2. 左メニューの **`Secrets and variables`** ➔ **`Actions`** を選択します。
3. **`New repository secret`** ボタンをクリックし、以下を設定します：
   - **Name**: `DISCORD_WEBHOOK_URL`
   - **Secret**: ご自身のDiscord Webhook URL
4. **`Add secret`** をクリックして保存します。

---

### ステップ3：動作確認（手動実行）
1. GitHub リポジトリの **`Actions`** タブを開きます。
2. 左メニューの **`United Award Flight Monitor`** を選択します。
3. 右側の **`Run workflow`** ボタンをクリックして実行します。
4. 数分後、ユナイテッド公式サイトを自動操作して空席が判定され、Discordに通知が届きます！

---

## ⏰ 自動実行について
- デフォルトで **1時間に1回、24時間自動実行** されます（GitHub Actions 無料枠内で完全0円で動作します）。
- スプレッドシート（`有効` になっている行）を自動で読み込み、指定された条件（例: `金土日`）に従って空席を判定します。
