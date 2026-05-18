# claude-automation

Claude × Notion × Google Calendar による毎朝の自動スケジューリング。

毎朝 7:00 (JST) に GitHub Actions が起動し、Notion のタスクを取得 → Claude が見積もり＆配置 → Google カレンダーに `🤖` 付きイベントを追加する。

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

### 3. `.env` を作成

```bash
cp .env.example .env
# 各値を埋める
```

| 変数 | 説明 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic Console で発行 |
| `NOTION_API_KEY` | Notion インテグレーション (`secret_...`) |
| `NOTION_DATABASE_ID` | マイタスク DB の ID |
| `GOOGLE_CALENDAR_ID` | `primary` でOK |

### 4. Notion 側の準備

DB に以下のプロパティが存在すること:
- `タスク名` (Title)
- `ステータス` (Status, `完了` を含む)
- `期限` (Date, 任意)

作成した Integration を該当 DB の「Connections」で接続する。

### 5. Google OAuth トークンを取得

Google Cloud Console で OAuth クライアント (デスクトップアプリ) を作成し、`credentials.json` をプロジェクトルートに置く。

```bash
python scripts/auth_google.py
```

ブラウザで認証 → `token.json` が生成される。

### 6. ローカルで動作確認

```bash
python scripts/schedule.py
```

### 7. GitHub Secrets を設定

`Settings` → `Secrets and variables` → `Actions`:

| Secret 名 | 値 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic の API キー |
| `NOTION_API_KEY` | Notion の API キー |
| `NOTION_DATABASE_ID` | マイタスク DB の ID |
| `GOOGLE_CALENDAR_ID` | `primary` など |
| `GOOGLE_TOKEN_JSON` | `token.json` の中身（JSON 全体） |

### 8. コミット & プッシュ

```bash
git add .
git commit -m "feat: Claude自動スケジューリング初期セットアップ"
git push origin main
```

## 手動実行

GitHub の `Actions` タブ → `毎朝のスケジューリング` → `Run workflow`。

成功するとカレンダーに `🤖` 付きイベントが追加される。

## ファイル構成

```
claude-automation/
├── .env.example
├── .github/
│   └── workflows/
│       └── daily.yml
├── .gitignore
├── README.md
├── requirements.txt
└── scripts/
    ├── auth_google.py
    └── schedule.py
```

## ⚠️ セキュリティ

`token.json` / `credentials.json` / `.env` は **絶対にコミットしない**（`.gitignore` で除外済み）。

## ライセンス

Private use.
