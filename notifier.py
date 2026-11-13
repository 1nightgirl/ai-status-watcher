"""Discord Webhook への通知。

DISCORD_WEBHOOK_URL が未設定の場合は送信せず、標準出力に
「送信予定の内容」を表示して正常終了する (dry-run 動作)。
"""
import json
import urllib.request

DISCORD_CONTENT_LIMIT = 2000


def send_discord(webhook_url, content):
    """通知を送信する。送信したら True、dry-run なら False を返す。"""
    if len(content) > DISCORD_CONTENT_LIMIT:
        content = content[: DISCORD_CONTENT_LIMIT - 1] + "…"
    if not webhook_url:
        print("[dry-run] DISCORD_WEBHOOK_URL 未設定のため送信しません。送信予定の内容:")
        print(content)
        print("---")
        return False
    body = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "ai-status-watcher/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
    print("Discordへ通知しました。")
    return True
