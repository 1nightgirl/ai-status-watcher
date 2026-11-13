"""AIサービスの障害監視 → Discord通知。

GitHub Actions から定期実行されることを想定。
状態は state.json に保持し、レベル (ok / degraded / outage) が
変わったときだけ Discord へ通知する。

- 初回実行時は通知せず、現状態を state.json に初期記録するだけ。
- ステータス取得自体が失敗した場合は障害とは判定せず「取得失敗」として
  扱い、通知しない (監視側の失敗を障害と誤報しない)。
- DISCORD_WEBHOOK_URL 未設定時は dry-run (標準出力に送信予定内容を表示)。

外部依存なし (Python標準ライブラリのみ)。
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
STATE_PATH = os.path.join(BASE_DIR, "state.json")

LEVEL_LABEL = {"ok": "正常", "degraded": "性能低下", "outage": "障害"}
STATUS_LABEL = {
    "operational": "正常",
    "degraded_performance": "性能低下",
    "partial_outage": "一部障害",
    "major_outage": "大規模障害",
    "under_maintenance": "メンテナンス中",
}


def now_jst():
    return datetime.now(JST)


def load_config(path):
    """config.yaml の簡易パーサ。

    services: の下に並ぶ `- key: value` 形式のフラットな構造だけを扱う。
    値はプレーンな文字列 (クォート可) のみ。
    """
    services = []
    current = None
    in_services = False
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not line.startswith((" ", "-")) and stripped.endswith(":"):
                in_services = stripped == "services:"
                continue
            if not in_services:
                continue
            if stripped.startswith("- "):
                current = {}
                services.append(current)
                stripped = stripped[2:].strip()
                if not stripped:
                    continue
            if current is not None and ":" in stripped:
                key, _, value = stripped.partition(":")
                current[key.strip()] = value.strip().strip('"').strip("'")
    return services


def fetch_json(url, timeout=20):
    req = urllib.request.Request(
        url, headers={"User-Agent": "ai-status-watcher/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_statuspage(service):
    """Statuspage API からコンポーネント状態を取得し、レベルを判定する。

    戻り値: (level, components_dict) / 取得失敗時は例外を送出。
    """
    status_data = fetch_json(service["status_url"])
    components_data = fetch_json(service["components_url"])

    components = {}
    for comp in components_data.get("components", []):
        if comp.get("group"):
            continue  # グループ見出しは実コンポーネントではないので除外
        components[comp.get("name", "")] = comp.get("status", "")

    if components:
        statuses = set(components.values())
        if statuses & {"partial_outage", "major_outage"}:
            level = "outage"
        elif "degraded_performance" in statuses:
            level = "degraded"
        else:
            level = "ok"
    else:
        # コンポーネントが取れない場合は全体 indicator で代替判定
        indicator = status_data.get("status", {}).get("indicator", "")
        level = {"none": "ok", "minor": "degraded"}.get(indicator, "outage")
    return level, components


def check_http(service):
    """HTTP到達チェック。2xx/3xx/4xx は応答あり (up)、
    5xx・タイムアウト・接続エラーは down とみなす。"""
    req = urllib.request.Request(
        service["check_url"],
        headers={"User-Agent": "ai-status-watcher/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read(1024)
            code = resp.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception:
        return "outage", {}
    return ("ok" if code < 500 else "outage"), {}


CHECKERS = {"statuspage": check_statuspage, "http": check_http}


def affected_components(components):
    """正常でもメンテナンス中でもないコンポーネント名と状態のリスト。"""
    return [
        (name, status)
        for name, status in components.items()
        if status not in ("operational", "under_maintenance")
    ]


def build_message(service, old_level, new_level, components, when):
    name = service["name"]
    old_label = LEVEL_LABEL.get(old_level, old_level)
    new_label = LEVEL_LABEL.get(new_level, new_level)
    if new_level == "ok":
        title = f"🟢【復旧】{name}"
    elif old_level == "outage" and new_level == "degraded":
        title = f"🟠【一部復旧】{name}"
    elif new_level == "outage":
        title = f"🔴【障害発生】{name}"
    else:
        title = f"🟠【性能低下】{name}"
    lines = [
        title,
        f"状態が「{old_label}」→「{new_label}」に変わりました。",
    ]
    affected = affected_components(components)
    if affected:
        lines.append("影響コンポーネント:")
        for comp_name, comp_status in affected:
            label = STATUS_LABEL.get(comp_status, comp_status)
            lines.append(f"・{comp_name}（{label}）")
    lines.append(f"公式ステータス: {service.get('page_url', '')}")
    lines.append(f"確認時刻: {when.strftime('%Y-%m-%d %H:%M')} JST")
    return "\n".join(lines)


def main():
    sys.path.insert(0, BASE_DIR)
    from notifier import send_discord
    from state import load_state, save_state

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    services = load_config(CONFIG_PATH)
    state = load_state(STATE_PATH)
    when = now_jst()
    when_iso = when.isoformat(timespec="seconds")

    for service in services:
        sid = service["id"]
        checker = CHECKERS.get(service.get("type", ""))
        if checker is None:
            print(f"[{sid}] 未知の type: {service.get('type')} のためスキップ")
            continue
        prev = state["services"].get(sid)
        try:
            level, components = checker(service)
        except Exception as e:
            # 取得失敗は障害と判定しない。前回レベルは保持し、
            # fetch_error フラグだけを記録して通知しない。
            print(f"[{sid}] 取得失敗 (障害とは判定しません): {e}")
            entry = dict(prev) if prev else {
                "level": None,
                "components": {},
                "changed_at": None,
            }
            entry["fetch_error"] = True
            entry["last_check"] = when_iso
            state["services"][sid] = entry
            continue

        if prev is None or prev.get("level") is None:
            # 初回は通知せず初期記録のみ
            state["services"][sid] = {
                "level": level,
                "components": components,
                "changed_at": when_iso,
                "last_check": when_iso,
                "fetch_error": False,
            }
            print(f"[{sid}] 初期記録: {level} (通知なし)")
            continue

        old_level = prev["level"]
        entry = {
            "level": level,
            "components": components,
            "changed_at": prev.get("changed_at") or when_iso,
            "last_check": when_iso,
            "fetch_error": False,
        }
        if level != old_level:
            entry["changed_at"] = when_iso
            message = build_message(service, old_level, level, components, when)
            try:
                send_discord(webhook_url, message)
            except Exception as e:
                print(f"[{sid}] Discord送信に失敗しました: {e}")
            print(f"[{sid}] レベル変化: {old_level} -> {level} (通知)")
        else:
            print(f"[{sid}] 変化なし: {level}")
        state["services"][sid] = entry

    save_state(STATE_PATH, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
