"""
収集対象RSSフィード(config/feeds.yaml)と、記事を分類するジャンルのON/OFF(config/labels.yaml)を
ブラウザから編集するための、ごく簡単なローカルUI。

使い方:
    cd daily-digest-podcast
    source .venv/bin/activate   # 既存のvenvを使う場合
    pip install -r requirements.txt    # 初回のみ
    python tools/feeds_editor.py
    # ブラウザで http://127.0.0.1:8787 を開く

保存すると config/feeds.yaml / config/labels.yaml がこのツールの形式で書き直されます
（手で書いたコメントの位置などは失われますが、内容は保持されます）。

ジャンル(選べるカテゴリ・ラベル)の一覧そのものは config/label_mapping.yaml が
唯一のソース。ジャンルを増やしたい/減らしたい/分類ルールを変えたい場合は
そちらを直接編集してください(このツールを再起動すれば選択肢に反映されます)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from flask import Flask, redirect, render_template_string, request, url_for

ROOT = Path(__file__).resolve().parent.parent
FEEDS_PATH = ROOT / "config" / "feeds.yaml"
LABELS_PATH = ROOT / "config" / "labels.yaml"
LABEL_MAPPING_PATH = ROOT / "config" / "label_mapping.yaml"

sys.path.insert(0, str(ROOT / "src"))
import fetch_feeds  # noqa: E402  (ラベル関連のロジックはfetch_feeds.pyと共通化している)

app = Flask(__name__)

# ジャンル(選べるカテゴリ・ラベル)一覧は label_mapping.yaml が唯一のソース。
CATEGORIES = list(fetch_feeds.load_label_mapping(LABEL_MAPPING_PATH).keys())

# 起動時に labels.yaml をジャンル一覧と同期しておく(手動でスキャンする必要はない)。
if CATEGORIES:
    fetch_feeds.seed_labels(LABELS_PATH, LABEL_MAPPING_PATH)

HEADER_COMMENT = """\
# 収集対象のRSSフィード一覧
# このファイルは tools/feeds_editor.py (ブラウザUI) から編集・保存できます。
# 記事のジャンル分けはフィード単位ではなく、記事ごとに自動で判定されます
# (ジャンルの絞り込みは下の「ジャンルの絞り込み」セクション・config/labels.yaml)。
# enabled: false にすると、削除せずに一時的に収集対象から外せます。
"""


def load_feeds() -> dict:
    if not FEEDS_PATH.exists():
        return {"feeds": [], "lookback_hours": 26, "max_articles_per_feed": 6}
    with open(FEEDS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("feeds", [])
    data.setdefault("lookback_hours", 26)
    data.setdefault("max_articles_per_feed", 6)
    for feed in data["feeds"]:
        feed.setdefault("enabled", True)
    return data


def save_feeds(data: dict) -> None:
    body = {
        "feeds": data["feeds"],
        "lookback_hours": data["lookback_hours"],
        "max_articles_per_feed": data["max_articles_per_feed"],
    }
    yaml_text = yaml.safe_dump(body, allow_unicode=True, sort_keys=False)
    FEEDS_PATH.write_text(HEADER_COMMENT + "\n" + yaml_text, encoding="utf-8")


PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>収集フィード・ジャンル設定</title>
<style>
  body { font-family: -apple-system, "Hiragino Sans", sans-serif; max-width: 900px; margin: 2rem auto; color: #222; }
  h1 { font-size: 1.4rem; }
  h2 { font-size: 1.1rem; margin-top: 2.5rem; border-top: 1px solid #eee; padding-top: 1.5rem; }
  p.hint { color: #666; font-size: 0.85rem; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 1rem; }
  th, td { border: 1px solid #ddd; padding: 6px 8px; font-size: 0.9rem; }
  th { background: #f5f5f5; text-align: left; }
  input[type=text], select { width: 100%; box-sizing: border-box; padding: 4px; }
  .settings { display: flex; gap: 2rem; margin: 1rem 0; }
  .settings label { display: block; font-size: 0.85rem; color: #555; }
  .settings input { width: 100px; padding: 4px; }
  input[type=submit] {
    background: #2563eb; color: white; border: none; padding: 8px 16px;
    border-radius: 6px; cursor: pointer; font-size: 0.9rem;
  }
  .row-actions { white-space: nowrap; }
  .flash { background: #dcfce7; border: 1px solid #16a34a; padding: 8px 12px; border-radius: 6px; margin-bottom: 1rem; }
  .add-row td { background: #fafafa; }
  .labels-grid { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 1rem 0; }
  .labels-grid label { font-size: 0.9rem; white-space: nowrap; }
</style>
</head>
<body>
<h1>収集フィード・ジャンル設定</h1>
{% if saved %}<div class="flash">保存しました。次回の実行から反映されます。</div>{% endif %}

<form method="post" action="{{ url_for('save') }}">
  <div class="settings">
    <div>
      <label>対象期間(時間)</label>
      <input type="number" name="lookback_hours" value="{{ data.lookback_hours }}">
    </div>
    <div>
      <label>1フィードあたり最大記事数</label>
      <input type="number" name="max_articles_per_feed" value="{{ data.max_articles_per_feed }}">
    </div>
  </div>

  <table>
    <tr>
      <th style="width:60px">有効</th>
      <th>フィード名</th>
      <th>URL</th>
      <th style="width:60px">削除</th>
    </tr>
    {% for feed in data.feeds %}
    <tr>
      <td><input type="checkbox" name="enabled_{{ loop.index0 }}" {% if feed.enabled %}checked{% endif %}></td>
      <td><input type="text" name="name_{{ loop.index0 }}" value="{{ feed.name }}"></td>
      <td><input type="text" name="url_{{ loop.index0 }}" value="{{ feed.url }}"></td>
      <td class="row-actions"><label><input type="checkbox" name="delete_{{ loop.index0 }}"> 削除</label></td>
    </tr>
    {% endfor %}
    <tr class="add-row">
      <td><input type="checkbox" name="enabled_new" checked></td>
      <td><input type="text" name="name_new" placeholder="新しいフィード名"></td>
      <td><input type="text" name="url_new" placeholder="https://..."></td>
      <td>(新規追加)</td>
    </tr>
  </table>
  <input type="hidden" name="count" value="{{ data.feeds|length }}">
  <input type="submit" value="フィードの変更を保存">
</form>

<h2>ジャンルの絞り込み</h2>
<p class="hint">
  記事は本文のタグ・タイトルから自動でジャンルに分類されます(どれにも当てはまらなければ「その他」)。
  OFFにしたジャンルの記事は収集結果から除外されます。
  ジャンルの一覧・分類ルール自体は config/label_mapping.yaml で編集できます。
</p>

{% if labels %}
<form method="post" action="{{ url_for('save_labels') }}">
  <div class="labels-grid">
    {% for label, enabled in labels.items() %}
    <label><input type="checkbox" name="label_{{ loop.index0 }}" {% if enabled %}checked{% endif %}> {{ label }}</label>
    <input type="hidden" name="label_name_{{ loop.index0 }}" value="{{ label }}">
    {% endfor %}
  </div>
  <input type="hidden" name="count" value="{{ labels|length }}">
  <input type="submit" value="ジャンルの変更を保存">
</form>
{% else %}
<p class="hint">config/label_mapping.yaml にジャンルが定義されていません。</p>
{% endif %}

</body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    data = load_feeds()
    labels = fetch_feeds.load_labels(LABELS_PATH)
    saved = request.args.get("saved") == "1"
    return render_template_string(PAGE_TEMPLATE, data=data, labels=labels, saved=saved)


@app.route("/save", methods=["POST"])
def save():
    count = int(request.form.get("count", 0))
    feeds = []
    for i in range(count):
        if request.form.get(f"delete_{i}"):
            continue
        name = request.form.get(f"name_{i}", "").strip()
        url = request.form.get(f"url_{i}", "").strip()
        if not (name and url):
            continue
        feeds.append(
            {
                "name": name,
                "url": url,
                "enabled": bool(request.form.get(f"enabled_{i}")),
            }
        )

    # 新規追加行
    new_name = request.form.get("name_new", "").strip()
    new_url = request.form.get("url_new", "").strip()
    if new_name and new_url:
        feeds.append(
            {
                "name": new_name,
                "url": new_url,
                "enabled": bool(request.form.get("enabled_new")),
            }
        )

    data = {
        "feeds": feeds,
        "lookback_hours": int(request.form.get("lookback_hours", 26)),
        "max_articles_per_feed": int(request.form.get("max_articles_per_feed", 6)),
    }
    save_feeds(data)
    return redirect(url_for("index", saved=1))


@app.route("/save_labels", methods=["POST"])
def save_labels():
    count = int(request.form.get("count", 0))
    labels: dict[str, bool] = {}
    for i in range(count):
        name = request.form.get(f"label_name_{i}", "").strip()
        if not name:
            continue
        labels[name] = bool(request.form.get(f"label_{i}"))
    fetch_feeds.save_labels(LABELS_PATH, labels)
    return redirect(url_for("index", saved=1))


if __name__ == "__main__":
    print(f"設定ファイル: {FEEDS_PATH}")
    print(f"ジャンル定義: {LABEL_MAPPING_PATH}")
    print(f"ジャンルON/OFF: {LABELS_PATH}")
    print("ブラウザで http://127.0.0.1:8787 を開いてください")
    # debug=True: このファイル(feeds_editor.py)を編集して保存すると、
    # ブラウザをリロードするだけで変更が反映される(サーバーの手動再起動が不要)。
    # ローカル(127.0.0.1)専用ツールなので有効にしても安全。
    app.run(host="127.0.0.1", port=8787, debug=True)
