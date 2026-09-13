# claude-automation

Notion × Claude Code (CLI) × Google カレンダー × Google Tasks（マイタスク）を使った、タスク自動スケジューリングの実験プロジェクト。

> **お知らせ（2026-09）:** 毎朝/毎夜の自動実行（`schedule.py` / `review.py` / launchd cron設定）は、Google OAuth トークン切れ（`invalid_grant`）で動作しなくなっていたため削除しました。現在はセットアップ・認証・疎通確認まわりのスクリプト（`auth_google.py` / `check.py` / `notify.py` / `status.py`）のみが残っています。自動スケジューリング自体を復活させる場合は、Google 再認証（`auth_google.py`）とスケジューリングロジックの再実装が必要です。

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

> 補足: `scripts/auth_google.py` はローカル初期認証用です。GitHub Secrets への格納案内は「将来クラウド運用する場合」の参考情報で、現状は不要です。

> 既存の `token.json` がある場合（カレンダーのみ対応の古い版）は、`auth_google.py` を再実行するとスコープ不足を検出して再認証を促す。

### 7. ローカルで動作確認

疎通だけ確認（書き込みなし）:

```bash
python scripts/check.py
```

> `schedule.py` / `review.py` / launchd による自動実行は削除済みです（上記のお知らせ参照）。

## ファイル構成

```
claude-automation/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
└── scripts/
    ├── auth_google.py   # 初回のみ: Google OAuth トークン生成（calendar + tasks）
    ├── check.py         # セットアップ確認（read-only）
    ├── notify.py        # macOS 通知センターへの通知ヘルパー（共通）
    └── status.py        # （旧）自動実行状況の確認。参照先の launchd/last-run.json は削除済みのため現状は使えません
```

## ⚠️ セキュリティ

`token.json` / `credentials.json` / `.env` は **絶対にコミットしない**（`.gitignore` で除外済み）。

## ライセンス

Private use.

---

## 改善点バックログ

> 2026-09 追記: 自動スケジューリング機能（`schedule.py` / `review.py` / launchd）の削除に伴い、それらに紐づく項目は整理済み。残っているのは認証・セットアップ確認まわりの改善案のみ。

- [ ] `[P1]` `.gitignore` に `token.json.bak` 追加
- [ ] `[P1]` リポジトリ履歴に秘密情報がないか確認手順を README に
- [ ] `[P2]` `auth_google.py` の GitHub Secrets 案内を「将来用」と明記（GHA なし）
- [ ] `[P2]` OAuth `credentials.json` の配置・権限・ローテーション手順
- [ ] `[P2]` OAuth トークンリフレッシュ失敗時の再認証フロー
- [ ] `[P3]` `.env` 各キーのバリデーションを `check.py` に
- [ ] `[P1]` `requirements.txt` の依存バージョンを pin
- [ ] `[P2]` 正式 LICENSE ファイル追加
- [ ] `[P2]` Dependabot（pip）導入
- [ ] `[P3]` pre-commit（ruff/mypy）+ 単体テスト整備
