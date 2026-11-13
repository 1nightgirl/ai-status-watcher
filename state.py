"""state.json の読み書き。

state.json の構造:
{
  "version": 1,
  "services": {
    "<service_id>": {
      "level": "ok" | "degraded" | "outage",
      "components": {"<component name>": "<raw status>", ...},
      "changed_at": "<ISO8601 JST>",   # レベルが最後に変わった時刻
      "last_check": "<ISO8601 JST>",   # 最後に確認した時刻
      "fetch_error": false             # 直近の取得が失敗したかどうか
    }
  }
}
"""
import json
import os

DEFAULT_STATE = {"version": 1, "services": {}}


def load_state(path):
    if not os.path.exists(path):
        return json.loads(json.dumps(DEFAULT_STATE))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(DEFAULT_STATE))
    if not isinstance(data, dict) or "services" not in data:
        return json.loads(json.dumps(DEFAULT_STATE))
    return data


def save_state(path, state):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
