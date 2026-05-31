# claude-automation

Notion × Claude Code (CLI) × Google カレンダー × Google Tasks（マイタスク）による毎朝の自動スケジューリング。

- **朝 7:00** — Notion のタスクを取得 → ローカル Claude Code が見積もり＆配置 → Google カレンダーに `🤖` 付きイベントを追加 → **同じスケジュール対象のタスク**を Google Tasks（マイタスク）にも登録（notes に Notion page ID を埋め込む）
- **夜 22:00** — マイタスクのチェック状態を確認し、ユーザーがチェックしたタスクに対応する Notion を「完了」に更新

マイタスクには **Claude が今日スケジュールしたタスクのみ**が並ぶ。前日マイタスクに残っていた未スケジュールタスクは、その日のスケジュールに含まれていなければ自動削除される（チェック済みは触らない）。

完了判定はユーザーの**明示的なチェック**を根拠にする（Claude による推測ではない）。マイタスクにはモバイル / ウェブ / カレンダー画面右側のタスクパネル等から手軽にチェックを入れられる。

**Anthropic API キー / 課金は不要**（ローカル Claude Code を使うため）。代わりに **GitHub Actions では動かせない**（CLI と Claude Code セッションが Runner にないため）。

## セットアップ

### 1. リポジトリをクローン

```bash
git clone https://github.com/iorn121/claude-automation.git
cd claude-automation
```

### 2. Python 3.11+ と仮想環境を準備

```bash
python3.11 --version
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

`python3.11` がない場合は `python3` で代用可（3.11以上を推奨）。

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

> 補足: `scripts/auth_google.py` はローカル初期認証用です。GitHub Secrets への格納案内は「将来クラウド運用する場合」の参考情報で、現行のローカル/launchd 運用では不要です。

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
    ├── cleanup_today.py # 🤖イベント/当日マイタスクのクリーンアップ
    ├── schedule.py      # 朝: Notion → Claude → Calendar + マイタスク登録
    ├── review.py        # 夜: マイタスクのチェック状態 → Notion 完了に同期
    ├── notify.py        # macOS 通知センターへの通知ヘルパー（共通）
    └── status.py        # 今日の自動実行状況を確認
```

## 実行状況の確認

```bash
python scripts/status.py
```

`launchd/last-run.json` を読んで、当日の朝/夜ジョブが走ったか、何件処理したか、エラーがあったかを表示する。

`schedule.py` / `review.py` は完了時に macOS 通知センターに結果を出すので、見逃しにくい。初回実行時に「通知の許可」を求められたら許可しておく。

## Catch-up（実行漏れの救済）

`StartCalendarInterval` の時刻に Mac がスリープしてたり電源 OFF だったりすると、launchd の標準動作だけでは:

- **スリープ中** → 復帰時に自動で実行される（launchd の標準動作）
- **シャットダウン中** → 失われる ❌

これを救済するため、plist は `RunAtLoad=true` にしてあり、**Mac 起動直後（ジョブのロード時）にも一度走る**。多重実行を防ぐため、`schedule.py` / `review.py` は `last-run.json` を見て当日すでに `success` / `skipped` で終わっていればスキップする。

再実行前に、当日の 🤖 イベント/マイタスクを明示的に掃除したい場合:

```bash
python scripts/cleanup_today.py --all
```

そのうえで強制再実行:

```bash
python scripts/schedule.py --force
python scripts/review.py --force
```

## 仕組み（マイタスク連携）

- `schedule.py` がマイタスクを作成する際、`notes` 欄の先頭に `notion_id: <Notion page id>` を埋め込む
- マイタスクに登録するのは **Claude が今日スケジュールした Notion タスクのみ**（タイトル先頭に `⏰ HH:MM ` プレフィックス、サブタスク分割時は最早の開始時刻）
- **期限は常に当日固定**。マイタスクは毎日作り直す運用なので、Notion の `期限` プロパティは Claude スケジューラの優先度判定にだけ使い、マイタスク側の due には反映しない
- 既にマイタスクに同じ `notion_id` が存在すれば差分がある場合のみ patch で更新（タイトル/notes/期限）
- 既存マイタスク（notion_id 付き・未チェック）のうち今日のスケジュール対象外のものは **delete API で削除**。チェック済みは `showCompleted=False` で取得していないため触らない
- `review.py` は `notes` から `notion_id` を読み取り、マイタスクが `completed` 状態のものに対応する Notion タスクを「完了」に更新する
- マイタスクに残っている（未チェック）タスクは触らない（次回スケジュールから外れれば削除される）

> ⚠️ Google Tasks API は `due` の時刻部分を保存しないため、API 経由で時刻指定したタスクは作れません。代わりにタイトル先頭に `⏰ HH:MM` を付けることで「いつのタスクか」が一覧で見えるようにしています。

## ⚠️ セキュリティ

`token.json` / `credentials.json` / `.env` は **絶対にコミットしない**（`.gitignore` で除外済み）。

## ライセンス

Private use.

---

## 改善点バックログ

> 監査日: 2026-05-31。Tech: Python / launchd / Notion + Claude CLI + Google Calendar/Tasks。`.env.example` あり。CI・LICENSE なし。

### 機能 (Functionality)

- [ ] `[P1]` `schedule.py --force` 再実行で 🤖 カレンダーイベント重複 — upsert 化または自動 cleanup
- [ ] `[P1]` `cleanup_today.py` を README ファイル構成・運用手順に追加
- [ ] `[P2]` `schedule.py` に `--dry-run` 追加
- [ ] `[P2]` 夜の `review.py` 完了時に 🤖 イベント完了/削除オプション
- [ ] `[P2]` Notion プロパティ名を `.env` で設定可能に
- [ ] `[P2]` 未スケジュールタスクの通知強化
- [ ] `[P3]` 複数 Notion DB / カレンダー対応
- [ ] `[P3]` 週次レビュー・未チェックリマインド

### デザイン/UX (Design)

- [ ] `[P2]` `status.py` に `--json` 出力
- [ ] `[P2]` `check.py` をトラブルシュートガイド形式に拡張
- [ ] `[P3]` 通知メッセージの統一フォーマット
- [ ] `[P3]` `notify.py` 失敗時の stdout フォールバック

### セキュリティ (Security)

- [ ] `[P1]` `.gitignore` に `token.json.bak` / `launchd/last-run.json` 追加
- [ ] `[P1]` リポジトリ履歴に秘密情報がないか確認手順を README に
- [ ] `[P2]` `auth_google.py` の GitHub Secrets 案内を「将来用」と明記（GHA なし）
- [ ] `[P2]` OAuth `credentials.json` の配置・権限・ローテーション手順
- [ ] `[P3]` `.env` 各キーのバリデーションを `check.py` に

### システム設計 (System Design)

- [ ] `[P1]` `requirements.txt` の依存バージョンを pin
- [ ] `[P2]` `scripts/` を Python パッケージ化（`python -m` 実行に統一）
- [ ] `[P2]` JST を `TZ` 環境変数で設定可能に
- [ ] `[P2]` launchd plist をテンプレート化 + セットアップスクリプト
- [ ] `[P2]` OAuth トークンリフレッシュ失敗時の再認証フロー共通化
- [ ] `[P3]` Claude CLI 呼び出しのリトライ・タイムアウトを `.env` 化
- [ ] `[P3]` 構造化ログ（JSON Lines）出力モード

### ドキュメント/運用 (Docs & Ops)

- [ ] `[P1]` 推奨 Python バージョン（3.11+）と venv 手順を README に
- [ ] `[P1]` `.env.example` に `CLAUDE_BIN` 追記
- [ ] `[P2]` 正式 LICENSE ファイル追加
- [ ] `[P2]` Dependabot（pip）導入
- [ ] `[P2]` トラブルシューティング節（launchd 未実行、Claude 認証切れ等）
- [ ] `[P2]` 朝/夜フローのシーケンス図追加
- [ ] `[P3]` pre-commit（ruff/mypy）+ 単体テスト整備
