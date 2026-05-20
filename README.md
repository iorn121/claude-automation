# claude-automation

Notion × Claude Code (CLI) × Google Calendar による毎朝の自動スケジューリング。

毎朝 7:00 (JST) に Mac の launchd が起動し、Notion のタスクを取得 → ローカル Claude Code が見積もり＆配置 → Google カレンダーに `🤖` 付きイベントを追加する。

**Anthropic API キー / 課金は不要**（ローカル Claude Code を使うため）。代わりに **GitHub Actions では動かせない**（CLI と Claude Code セッションが Runner にないため）。

## セットアップ

### 1. リポジトリをクローン

```bash
git clone https://github.com/iorn121/claude-automation.git
cd claude-automation
```

### 2. 依存関係をインストール

```bash
pip install -r requirements.txt
```

### 3. Claude Code を準備

```bash
claude --version
```

入っていない場合は [https://docs.claude.com/en/docs/claude-code](https://docs.claude.com/en/docs/claude-code) を参照。Pro/Max サブスクで `claude login` してあれば API キー不要。

### 4. `.env` を作成

```bash
cp .env.example .env
# 各値を埋める
```

| 変数 | 説明 |
|---|---|
| `NOTION_API_KEY` | Notion インテグレーション (`ntn_...` または `secret_...`) |
| `NOTION_DATABASE_ID` | Tasks DB の ID |
| `GOOGLE_CALENDAR_ID` | `primary` でOK |

### 5. Notion 側の準備

DB に以下のプロパティが存在すること:
- `タスク名` (Title)
- `ステータス` (Select, オプション: `未着手` / `進行中` / `完了`)
- `期限` (Date, 任意)

作成した Integration を該当 DB の「Connections」で接続する。

### 6. Google OAuth トークンを取得

Google Cloud Console で OAuth クライアント (デスクトップアプリ) を作成し、`credentials.json` をプロジェクトルートに置く。

```bash
python scripts/auth_google.py
```

ブラウザで認証 → `token.json` が生成される。

### 7. ローカルで動作確認

まず疎通だけ確認（書き込みなし）:

```bash
python scripts/check.py
```

`✨ すべてOK!` が出たら本実行:

```bash
python scripts/schedule.py
```

### 8. 毎朝の自動実行（launchd）

`launchd/com.iorn.claude-automation.plist` を `~/Library/LaunchAgents/` にコピーして起動する。

```bash
cp launchd/com.iorn.claude-automation.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.iorn.claude-automation.plist
```

手動で1回流したい時:

```bash
launchctl start com.iorn.claude-automation
```

ログ:

```bash
tail -f launchd/stdout.log launchd/stderr.log
```

アンインストール:

```bash
launchctl unload ~/Library/LaunchAgents/com.iorn.claude-automation.plist
rm ~/Library/LaunchAgents/com.iorn.claude-automation.plist
```

**注意:** plist 内の Python パス・プロジェクトパス・PATH は環境に合わせて編集してください（`which python3` / `which claude` で確認）。

## ファイル構成

```
claude-automation/
├── .env.example
├── .gitignore
├── README.md
├── launchd/
│   └── com.iorn.claude-automation.plist  # 毎朝の自動実行設定
├── requirements.txt
└── scripts/
    ├── auth_google.py   # 初回のみ: Google OAuth トークン生成
    ├── check.py         # セットアップ確認（read-only）
    └── schedule.py      # メイン: Notion → Claude → Calendar
```

## ⚠️ セキュリティ

`token.json` / `credentials.json` / `.env` は **絶対にコミットしない**（`.gitignore` で除外済み）。

## ライセンス

Private use.
