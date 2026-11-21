"""核验本机兼容服务配置和余额；仅显式 --call 时发送一条生成请求。"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--call", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "logs/llm-preflight.json")
    args = parser.parse_args()
    config_path = ROOT / "config.local.json"
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        for key in ("POKE_LLM_BASE_URL", "POKE_LLM_MODEL", "POKE_LLM_API_KEY"):
            if isinstance(config.get(key), str) and config[key].strip():
                os.environ[key] = config[key].strip()
    from backend.llm import _settings, model_status, explain
    import httpx
    config = _settings()
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "configuration": model_status(), "network_attempted": False, "chat_verified": False}
    if result["configuration"]["configured"]:
        try:
            with httpx.Client(timeout=20, trust_env=False, headers={"Authorization": "Bearer " + config["key"]} if config["key"] else {}) as client:
                result["network_attempted"] = True
                if config["host"] == "api.deepseek.com":
                    balance = client.get("https://api.deepseek.com/user/balance")
                    balance.raise_for_status()
                    result["balance"] = balance.json()
                    if not result["balance"].get("is_available"):
                        raise ValueError("existing_balance_unavailable")
                models = client.get(config["base"] + "/models")
                models.raise_for_status()
                result["model_listed"] = config["model"] in {row.get("id") for row in models.json().get("data", [])}
                if not result["model_listed"]:
                    raise ValueError("configured_model_not_listed")
            if args.call:
                os.environ["POKE_LLM_AUDIT_PATH"] = str(args.output.with_suffix(".calls.jsonl"))
                started = time.monotonic()
                answer, warning = explain("皮卡丘种族值总和是多少？", [{"id": "pokemon-25", "title": "皮卡丘", "text": "皮卡丘种族值为35、55、40、50、50、90，总和320。"}], "皮卡丘种族值总和为320。")
                result.update(chat_verified=bool(answer), answer=answer, warning=warning, latency_seconds=round(time.monotonic()-started,3))
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            # 不记录请求头、完整异常或密钥。
            result["failure_class"] = type(exc).__name__
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
