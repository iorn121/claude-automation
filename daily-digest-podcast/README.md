# 毎日のAI・プログラミング・セキュリティ ダイジェストPodcast（無料構成）

RSSで技術ニュースを収集 → Gemini API（無料枠）で要約・台本化 → VOICEVOX（無料・商用利用可）で音声化 →
GitHub Pages + Podcast RSSで配信、を毎日自動実行する仕組みです。月額コストはほぼ0円で運用できます。

構成の詳細・比較検討の経緯は同梱の設計調査ドキュメントを参照してください。

## 使う無料サービス

| 役割 | サービス | 無料枠 |
|---|---|---|
| 要約・台本生成 | Gemini API (gemini-3.6-flash。混雑時は 3.5 / 2.5 Flash に自動切替) | 1日1,500リクエストまで無料（1日1回の実行なら余裕） |
| 音声合成 | VOICEVOX ENGINE | 完全無料・商用利用可（要クレジット表記） |
| 実行基盤 | GitHub Actions | Publicリポジトリなら無制限 / Privateなら月2,000分無料 |
| ホスティング | GitHub Pages | 無料 |

## セットアップ手順（既存リポジトリのサブフォルダとして追加する場合）

このプロジェクトを既存の `claude-automation` リポジトリの中に `daily-digest-podcast/` というサブフォルダとして追加する前提の手順です。GitHub Pagesは「サブフォルダ配下のdocs」を直接は選べない仕様なので、生成物（mp3・podcast.xml）だけは専用の `podcast-data` ブランチに分けて配信します（ワークフローが自動でやってくれます）。仕組みの詳細は `.github/workflows/daily_podcast.yml` の先頭コメント参照。

1. **既存リポジトリのサブフォルダとして配置する**
   ```bash
   # claude-automationリポジトリのローカルクローンの中で実行
   cd /path/to/claude-automation
   cp -r /path/to/daily-digest-podcast ./daily-digest-podcast
   mkdir -p .github/workflows
   cp daily-digest-podcast/.github/workflows/daily_podcast.yml .github/workflows/daily_podcast.yml
   rm -rf daily-digest-podcast/.github   # リポジトリ直下に置いたので中の.githubは不要
   git add daily-digest-podcast .github/workflows/daily_podcast.yml
   git commit -m "add daily-digest-podcast"
   git push
   ```

2. **Gemini APIキーを取得する（無料・クレジットカード不要）**
   - https://aistudio.google.com/ にアクセスし、「Get API key」からAPIキーを発行。
   - もし429エラー（prepayment credits are depleted）が出た場合は、Google Cloud Consoleでそのプロジェクトの請求(billing)アカウントを外して無料枠に戻してください（本チャットで一度対応済みのはずです）。

3. **リポジトリにSecret/Variableを設定する（Settings > Secrets and variables > Actions）**
   - `Secrets` タブ → `GEMINI_API_KEY` を追加（発行したキーを貼り付け）
   - `Variables` タブ → `PODCAST_BASE_URL` を追加
     - 値は `https://<GitHubユーザー名>.github.io/<リポジトリ名>` （末尾スラッシュなし）
     - 例: `https://iori-xxx.github.io/claude-automation`

4. **ワークフローを一度手動実行して `podcast-data` ブランチを作らせる**
   - GitHubの「Actions」タブ → 「Daily AI/Programming/Security Digest Podcast」→ 「Run workflow」
   - 数分待つと、リポジトリに新しく `podcast-data` ブランチが自動で作られます。

5. **GitHub Pagesを有効化する（Settings > Pages）**
   - Source: `Deploy from a branch`
   - Branch: `podcast-data` / フォルダ: `/ (root)`
     - 手順4を先にやっておかないと、このブランチが選択肢に出てきません。
   - 保存すると、しばらくして上記の `PODCAST_BASE_URL` でアクセスできるようになります（`https://.../podcast.xml` で中身が見えればOK）。

6. **収集対象サイトを調整する（任意）**
   - `tools/feeds_editor.py` のブラウザUI、または `config/feeds.yaml` を直接編集。まずはデフォルトのままで試してOKです。

7. **スマホのPodcastアプリに登録する**
   - `https://<PODCAST_BASE_URL>/podcast.xml` をコピー
   - Overcast: 「Add URL」からペースト
   - Apple Podcasts: 「ライブラリ」→「番組を追加」→ URLを貼り付け
   - 以降、毎朝6:00(JST)に新しいエピソードが自動追加されます。

## ローカルでの動作確認

APIキーは `.env` ファイルに1回貼り付けておけば、以降は`export`不要でそのまま実行できます。

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 初回だけ: .envを作ってGEMINI_API_KEYの行にキーを貼り付けて保存
cp .env.example .env

# VOICEVOX ENGINEをローカルで起動（別ターミナル）
docker run -d -p 50021:50021 voicevox/voicevox_engine:cpu-latest

cd src
python run_all.py
```

`.env` は `.gitignore` 済みなのでGitHubには上がりません。GitHub Actionsで動かす場合はこの`.env`は使われず、リポジトリのSecrets/Variables（上記手順3）がそのまま使われます。

## 収集フィードをブラウザで編集する

`config/feeds.yaml` を直接編集する代わりに、ブラウザから収集対象サイトの追加・削除・一時停止（無効化）ができる簡単なUIを用意しています。

```bash
source .venv/bin/activate
pip install -r requirements.txt   # Flaskが追加されたので再インストールが必要です
python tools/feeds_editor.py
```

ブラウザで http://127.0.0.1:8787 を開くと、フィード一覧を編集できます。「有効」のチェックを外すと、削除せずに一時的に収集対象から外せます（`enabled: false`として保存されます）。保存すると即座に `config/feeds.yaml` が更新され、次回の実行から反映されます。

## 話者（声）を変更したい場合

`GET http://127.0.0.1:50021/speakers` で話者一覧とIDが取得できます。
環境変数 `VOICEVOX_SPEAKER` に好きなIDを設定してください（デフォルトは8=春日部つむぎ ノーマル）。

**VOICEVOXの利用規約により、使用したキャラクターのクレジット表記が必要です。**
`src/publish.py` の `VOICE_CREDIT` を、実際に使う話者名に書き換えてください。

## 読み上げマスタ（誤読対策）

VOICEVOX は英字の固有名詞を誤読することがあります（例: `Qiita` →「ちーた」）。
`config/reading_dict.yaml` に表記と読み（カタカナ）の対応を書いておくと、音声合成の直前に自動で置換されます。

```yaml
readings:
  - surface: Qiita
    reading: キータ
  - surface: GitHub
    reading: ギットハブ
```

- 英字の `surface` は大文字小文字を区別しません。
- 長い表記から先に置換します（`GitHub Actions` が `GitHub` より優先）。
- 台本ファイル（`data/script.txt`）自体は元表記のまま残し、合成時だけ読みを適用します。
- ユニットテスト: `cd daily-digest-podcast && python -m unittest tests.test_reading_dict -v`

## 既知の制限・今後の改善候補

- 記事本文が取得できないサイトがある（ペイウォール・JS描画のみのサイトなど）→ `config/feeds.yaml` から除外するか、個別に本文抽出ロジックを足す必要あり。
- Gemini無料枠は1分あたり15リクエストが上限。1日1回の実行なら問題にならない想定。
- `gemini-3.6-flash` が 503 (high demand) を返し続けることがある。同一モデルを2回試したあと `gemini-3.5-flash`、続いて `gemini-2.5-flash` に切り替える。切り替え先は環境変数 `GEMINI_FALLBACK_MODELS`（カンマ区切り。空なら切り替えなし）で変更できる。
- 音質・自然さを上げたくなったら、`synthesize.py` をOpenAI TTSやGoogle Cloud TTSに差し替える（設計調査ドキュメントの比較表を参照）。
- より自然な聴き心地にしたい場合、1人語りではなく2話者の対話形式にすると聞き疲れしにくいと言われています（将来的な改善候補）。
- 読み上げマスタに無い語は従来どおり VOICEVOX 任せです。気になる誤読があれば `config/reading_dict.yaml` に追記してください。
