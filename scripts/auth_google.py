"""Google OAuth ローカル認証スクリプト.

初回のみローカルで実行し、token.json を生成する。
生成された token.json の中身を GitHub Secrets の GOOGLE_TOKEN_JSON に貼り付ける。

事前準備:
1. https://console.cloud.google.com/ で新規プロジェクト作成
2. 「APIとサービス」→「ライブラリ」で Google Calendar API を有効化
3. 「OAuth同意画面」を設定（ユーザータイプ: 外部、テストユーザーに自分を追加）
4. 「認証情報」→「認証情報を作成」→「OAuth クライアント ID」
   - アプリケーションの種類: デスクトップアプリ
5. 作成された JSON をダウンロードし、`credentials.json` としてこのスクリプトと同じ階層に配置
6. このスクリプトを実行: `python scripts/auth_google.py`

実行するとブラウザが開いて Google アカウントへのログインを求められる。
許可すると、リポジトリのルートに token.json が生成される。
"""

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Google Calendar の予定読み書きに必要なスコープ
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# プロジェクトルート（scripts/ の一つ上）
ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_PATH = ROOT / "credentials.json"
TOKEN_PATH = ROOT / "token.json"


def main() -> None:
    creds = None

    # 既存の token.json があれば再利用
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    # 期限切れならリフレッシュ、なければ新規認証
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"{CREDENTIALS_PATH} が見つかりません。\n"
                    "Google Cloud Console で OAuth クライアント (デスクトップアプリ) を作成し、\n"
                    "credentials.json をプロジェクトルートに配置してください。"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            # ローカルサーバを立ち上げてブラウザでログイン
            creds = flow.run_local_server(port=0)

        # token.json として保存
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    print(f"✅ 認証完了: {TOKEN_PATH}")
    print("\n次のステップ:")
    print(f"  1. {TOKEN_PATH} の中身をすべてコピー")
    print("  2. GitHub の Settings → Secrets and variables → Actions で")
    print("     `GOOGLE_TOKEN_JSON` という名前で貼り付け")
    print("\n⚠️  token.json は絶対にコミットしないでください（.gitignore で除外済み）。")


if __name__ == "__main__":
    main()
