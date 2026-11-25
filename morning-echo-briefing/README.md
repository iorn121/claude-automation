# 朝の Echo ブリーフィング

毎朝、Google カレンダー・Google タスク・ニュースを短い台本にまとめ、Amazon Echo Dot から聞かせる。

Podcast と同じ並びです。定時ジョブが材料を集め、Gemini で口語の台本にし、VOICEVOX で mp3 にし、GitHub Pages の HTTPS URL に置く。違いが一つあります。Podcast はアプリが取りにくるだけですが、Echo には「この URL の音声を、この端末で、この時刻に再生する」公式の単体 API がありません。そこだけ別の仕組みを足しています。

## 調べた結果

Amazon は、任意の文章を指定した Echo で指定時刻に読み上げる個人向け API を公開していません。使える経路は次のとおりです。

**Flash Briefing（公式・取りにくる方式）**  
開発者コンソールで Flash Briefing スキルを作り、フィード URL を登録する。Alexa は約15分おきにフィードを取り、反映まで最大30分ほど見る。Echo 側は定刻ルーティンで「フラッシュブリーフィング」を再生する。開発中スキルは、その開発者アカウントでログインしている Echo で試せる。テキストなら Alexa が日本語で読む。音声ならこちらで作った mp3（256kbps、11秒以上、10分以内）を再生する。フィードは認証なしの HTTPS でなければならない。

**Voice Monkey（プッシュ）**  
認定スキル経由の HTTP API で、その場で Echo にアナウンスできる。`audio` に mp3 の URL を渡すと VOICEVOX の声で再生し、無ければ `speech` を Polly の日本語音声（`Mizuki`）で読む。ジョブの終了時刻を 7:00 に合わせられる。スキルを日本のアカウントで有効化できない場合は、Flash Briefing に切り替える。

**向かないもの**

- いつもの Podcast 配信のまま「最新回を再生」するルーティン。Amazon Music への収録遅れがあり、今朝作った回が 7:00 に間に合わない。
- Proactive Events（黄色リングの通知）。文面が定型で、自由な朝の台本は送れない。ユーザーが通知を開くまで読まれない。
- 非公式の Alexa 遠隔操作。Amazon の内部 API 依存で、朝になって突然壊れる。

このフォルダは Flash Briefing 用フィードの生成を本線にし、Voice Monkey が設定されているときだけ 7:00 にプッシュする。

## プライバシー

カレンダーとタスクは個人情報です。GitHub Pages は認証を付けられないので、URL を知っていれば誰でも読めます。対策は次の二つです。

1. パスに長い秘密トークンを入れる（`/briefing/<トークン>/`）。ディレクトリ一覧は出ない。トークンはリポジトリに書かない。
2. それでも公開したくない場合は、Variable `PUBLISH_TO_PAGES` を `false` にする。mp3 は載せず、台本だけを Voice Monkey が Echo に読む。この場合、文章は Voice Monkey のサーバを経由する。

「続きを読む」リンクは番組トップに向け、秘密パスは Alexa アプリに出さない。音声フィードの説明文は空にする。テキストフィードには台本そのものが入る。

過去の mp3 は残さない。毎回その朝のファイルだけを置き、ブランチの履歴も force push で捨てる（Podcast と同じ）。

## 時刻

| 時刻 (JST) | 何が起きるか |
|---|---|
| 6:00まで | ニュース Podcast の公開が終わる（定時は 0:17 JST） |
| 6:40 | このブリーフィングの生成が始まる |
| 7:00 | Voice Monkey を設定していれば、ここで Echo が鳴る |
| 7:30 | Flash Briefing だけを使う場合のルーティン推奨時刻（キャッシュ待ち） |

鳴る時刻を変えるときは `.github/workflows/morning_echo_briefing.yml` の cron と `ANNOUNCE_AT` をセットで変える。cron は `ANNOUNCE_AT` の約20分前（UTC で書く。JST は UTC+9）。例: 7:30 に鳴らすなら、開始は 7:10 JST なので cron は `10 22 * * *`、`ANNOUNCE_AT` は `07:30`。

Flash Briefing と Voice Monkey を両方有効にすると、同じ内容が2回流れます。どちらか一方にしてください。

## セットアップ

Podcast 側の GitHub Pages（ブランチ `podcast-data`、Variable `PODCAST_BASE_URL`）が先に有効である必要があります。手順は `daily-digest-podcast/README.md` のとおりです。

### 1. Google のトークン

リポジトリ直下で、まだなら認証する。

```bash
python scripts/auth_google.py
```

できた `token.json` の中身を、Actions の Secret `GOOGLE_TOKEN_JSON` に貼る。

OAuth 同意画面が「テスト」のままだと、リフレッシュトークンは7日で切れ、以前の自動実行が止まっていたのと同じ `invalid_grant` になります。同意画面を本番に公開し、警告を自分で通過しておく。カレンダーとタスクはセンシティブなスコープなので、未検証アプリの警告が出る。自分のアカウントで使う分には、詳細設定から続行できる。

このジョブは予定とタスクを読むだけで、書き戻さない。

### 2. 秘密パス

```bash
openssl rand -hex 16
```

出た文字列を Secret `BRIEFING_PATH_TOKEN` にする。

### 3. 任意の Secret / Variable

| 名前 | 種類 | 役割 |
|---|---|---|
| `GEMINI_API_KEY` | Secret | 台本を口語にする。空なら定型文 |
| `GOOGLE_CALENDAR_ID` | Variable | 省略時は `primary` |
| `GOOGLE_TASKLIST_ID` | Variable | 省略時は `@default` |
| `PUBLISH_TO_PAGES` | Variable | `false` で公開しない |

### 4-A. Echo に 7:00 ちょうどで鳴らす（Voice Monkey）

1. [Voice Monkey](https://voicemonkey.io/) で API トークンを発行する。
2. Alexa アプリで Voice Monkey スキルを有効にし、アカウントを連携する。
3. 対象にする Echo Dot のデバイス ID を作る。
4. Secret `VOICE_MONKEY_TOKEN` と `VOICE_MONKEY_DEVICE` に入れる。

有効化できない場合は 4-B に進み、この2つの Secret は空のままにする。

### 4-B. 公式だけで鳴らす（Flash Briefing）

1. [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask) で Flash Briefing スキルを作る。言語は日本語。
2. フィードは JSON、URL は次のどちらか。
   - VOICEVOX の声: `https://<PODCAST_BASE_URL>/briefing/<トークン>/flashbriefing-audio.json`
   - Alexa の声: `https://<PODCAST_BASE_URL>/briefing/<トークン>/flashbriefing.json`
3. 同じ Amazon アカウントの Echo でスキルを有効にする。Alexa アプリの「設定 → ニュース → フラッシュブリーフィング」に出す。
4. ルーティンを作る。時刻はフィード更新の30分後（既定の生成時刻なら 7:30）。アクションはフラッシュブリーフィング。
5. Voice Monkey の Secret は入れない。

フィードの中身は Actions を1回成功させたあとでないと 404 になる。先に「Run workflow」する。

## ローカル確認

```bash
cd morning-echo-briefing
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m unittest tests/test_briefing.py
python src/run_all.py --dry-run
```

`--dry-run` はサンプルの予定で台本と `docs/` のフィードだけ作る。通信しない。

本物の予定で試すときは、リポジトリ直下の `token.json` を使って `python src/run_all.py --skip-audio` を実行する。台本は `data/script.txt`（git 対象外）。予定の中身はログに出さない。

音声まで作るときは VOICEVOX を起動してから `--skip-audio` を外す。

```bash
docker run -d -p 50021:50021 voicevox/voicevox_engine:cpu-latest
python src/run_all.py
```

話者の初期値は Podcast と同じ 8（春日部つむぎ）。変えるときは `VOICEVOX_SPEAKER`。クレジット文は台本の末尾に入る。

ニュースの対象は `config/feeds.yaml`。

## ワークフローが失敗するとき

- `invalid_grant`: 同意画面がテストのまま7日過ぎたか、トークンを取り消した。`auth_google.py` をやり直して Secret を差し替える。
- Pages が 404 のまま: `podcast-data` ブランチを Pages のソースにしているか、`PODCAST_BASE_URL` が末尾スラッシュなしの本番 URL かを確認する。待ちきれないときは Voice Monkey がテキスト読み上げに切り替える。
- タスクだけ空: `token.json` がカレンダーだけの古いスコープ。`auth_google.py` を再実行する。
