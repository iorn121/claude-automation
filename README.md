# claude-automation

Notion × Claude Code (CLI) × Google カレンダー × Google Tasks（マイタスク）による毎朝の自動スケジューリング。

- **朝 7:00** — Notion のタスクを取得 → ローカル Claude Code が見積もり＆配置 → Google カレンダーに `🤖` 付きイベントを追加 → さらに全未完了タスクを Google Tasks（マイタスク）にも登録（notes に Notion page ID を埋め込む）
- **夜 22:00** — マイタスクのチェック状態を確認し、ユーザーがチェックしたタスクに対応する Notion を「完了」に更新

完了判定はユーザーの**明示的なチェック**を根拠にする（Claude による推測ではない）。マイタスクにはモバイル / ウェブ / カレンダー画面右側のタスクパネル等から手軽にチェックを入れられる。

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
| `GOOGLE_TASKLIST_ID` | （任意）マイタスクのリストID。未設定なら `@default` |

### 5. Notion 側の準備

DB に以下のプロパティが存在すること:
- `タスク名` (Title)
- `ステータス` (Select, オプション: `未着手` / `進行中` / `完了`)
- `期限` (Date, 任意)

作成した Integration を該当 DB の「Connections」で接続する。

### 6. Google OAuth トークンを取得

Google Cloud Console で以下の API を有効化:

- **Google Calendar API**
- **Google Tasks API**

OAuth クライアント (デスクトップアプリ) を作成し、`credentials.json` をプロジェクトルートに置く。

```bash
python scripts/auth_google.py
```

ブラウザで認証 → `token.json` が生成される。スコープは `calendar` と `tasks` の2つ。

> 既存の `token.json` がある場合（カレンダーのみ対応の古い版）は、`auth_google.py` を再実行するとスコープ不足を検出して再認証を促す。

### 7. ローカルで動作確認

まず疎通だけ確認（書き込みなし）:

```bash
python scripts/check.py
```

`✨ すべてOK!` が出たら本実行:

```bash
python scripts/schedule.py
```

完了レビュー（更新なしで確認）:

```bash
python scripts/review.py --dry-run
```

問題なければ本実行:

```bash
python scripts/review.py
```

### 8. 毎日の自動実行（launchd）

**朝のスケジュール（7:00）**

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

**夜の完了レビュー（22:00）**

```bash
cp launchd/com.iorn.claude-automation-review.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.iorn.claude-automation-review.plist
```

手動実行:

```bash
launchctl start com.iorn.claude-automation-review
```

ログ:

```bash
tail -f launchd/review-stdout.log launchd/review-stderr.log
```

**注意:** plist 内の Python パス・プロジェクトパス・PATH は環境に合わせて編集してください（`which python3` / `which claude` で確認）。

## ファイル構成

```
claude-automation/
├── .env.example
├── .gitignore
├── README.md
├── launchd/
│   ├── com.iorn.claude-automation.plist        # 毎朝 7:00
│   └── com.iorn.claude-automation-review.plist # 毎夜 22:00
├── requirements.txt
└── scripts/
    ├── auth_google.py   # 初回のみ: Google OAuth トークン生成（calendar + tasks）
    ├── check.py         # セットアップ確認（read-only）
    ├── schedule.py      # 朝: Notion → Claude → Calendar + マイタスク登録
    └── review.py        # 夜: マイタスクのチェック状態 → Notion 完了に同期
```

## 仕組み（マイタスク連携）

- `schedule.py` がマイタスクを作成する際、`notes` 欄の先頭に `notion_id: <Notion page id>` を埋め込む
- 既にマイタスクに同じ `notion_id` が存在すれば作り直さない（再実行しても重複しない）
- `review.py` は `notes` から `notion_id` を読み取り、マイタスクが `completed` 状態のものに対応する Notion タスクを「完了」に更新する
- マイタスクに残っている（未チェック）タスクは触らない

## ⚠️ セキュリティ

`token.json` / `credentials.json` / `.env` は **絶対にコミットしない**（`.gitignore` で除外済み）。

## ライセンス

Private use.
