from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Final

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from websocket import WebSocketApp  # websocket-client

WSS_URL: Final[str] = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
PING_EVERY_SECONDS: Final[float] = 10.0
FIRST_MSG_TIMEOUT_S: Final[float] = 3.0

load_dotenv()


def _env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing env var: {name}")
    return v


def _split_csv(value: str) -> list[str]:
    items = [x.strip() for x in value.split(",")]
    return [x for x in items if x]


class ClobCreds(BaseModel):
    api_key: str = Field(min_length=1)
    secret: str = Field(min_length=1)
    passphrase: str = Field(min_length=1)


@dataclass
class OrderState:
    open_orders: dict[str, dict[str, object]]


def _mask(s: str) -> str:
    if len(s) <= 8:
        return "*****"
    return f"{s[:4]}…{s[-4:]}"


def _ping_loop(ws: WebSocketApp, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            ws.send("PING")
        except Exception:
            return
        stop.wait(PING_EVERY_SECONDS)


def _build_first_msg(
    *,
    creds: ClobCreds,
    markets: list[str],
    auth_key_name: str,
    type_value: str,
) -> dict[str, object]:
    auth: dict[str, str]
    if auth_key_name == "apikey":
        auth = {"apikey": creds.api_key, "secret": creds.secret, "passphrase": creds.passphrase}
    elif auth_key_name == "apiKey":
        auth = {"apiKey": creds.api_key, "secret": creds.secret, "passphrase": creds.passphrase}
    else:
        raise RuntimeError("bad auth_key_name")

    return {
        "markets": markets,
        "type": type_value,
        "auth": auth,
    }


def main() -> None:
    # IMPORTANT: these should be CLOB L2 creds derived from PRIVATE_KEY,
    # not Builder keys from polymarket.com/settings?tab=builder. :contentReference[oaicite:10]{index=10}
    creds = ClobCreds(
        api_key=_env("CLOB_API_KEY"),
        secret=_env("CLOB_API_SECRET"),
        passphrase=_env("CLOB_API_PASSPHRASE"),
    )

    markets_raw = os.getenv("POLY_CONDITION_IDS", "").strip()
    markets = _split_csv(markets_raw)
    if not markets:
        raise RuntimeError("Set POLY_CONDITION_IDS to at least one condition id (market id).")

    attempts = [
        ("apikey", "user"),
        ("apiKey", "user"),
        ("apikey", "USER"),
        ("apiKey", "USER"),
    ]

    state = OrderState(open_orders={})

    attempt_idx = 0
    stop_ping = threading.Event()
    got_any_message = threading.Event()

    def on_open(ws: WebSocketApp) -> None:
        nonlocal attempt_idx
        auth_key_name, type_value = attempts[attempt_idx % len(attempts)]
        attempt_idx += 1

        msg = _build_first_msg(creds=creds, markets=markets, auth_key_name=auth_key_name, type_value=type_value)
        redacted = json.loads(json.dumps(msg))
        red_auth = redacted.get("auth")
        if isinstance(red_auth, dict):
            for k in list(red_auth.keys()):
                red_auth[k] = _mask(str(red_auth[k]))
        print(f"[open] attempt={auth_key_name}/{type_value} markets={len(markets)} payload={redacted}")

        ws.send(json.dumps(msg))
        stop_ping.clear()
        threading.Thread(target=_ping_loop, args=(ws, stop_ping), daemon=True).start()

        def _deadline_close() -> None:
            time.sleep(FIRST_MSG_TIMEOUT_S)
            if not got_any_message.is_set():
                try:
                    ws.close()
                except Exception:
                    pass

        threading.Thread(target=_deadline_close, daemon=True).start()

    def on_message(_: WebSocketApp, message: str) -> None:
        got_any_message.set()
        print(f"[recv] {message}")
        try:
            obj = json.loads(message)
        except json.JSONDecodeError:
            return
        if not isinstance(obj, dict):
            return

        if obj.get("event_type") == "order":
            oid = str(obj.get("id", ""))
            if oid:
                state.open_orders[oid] = obj
                et = obj.get("type", "?")
                mkt = obj.get("market", "?")
                print(f"[order] type={et} id={oid} market={mkt} open={len(state.open_orders)}")

    def on_error(_: WebSocketApp, error: object) -> None:
        print(f"[error] {error!r}")

    def on_close(ws: WebSocketApp, code: int | None, msg: str | None) -> None:
        stop_ping.set()
        print(f"[close] code={code} msg={msg!r}")
        got_any_message.clear()
        time.sleep(0.5)
        try:
            ws.run_forever()
        except Exception as e:
            print(f"[reconnect-error] {e!r}")

    ws = WebSocketApp(
        WSS_URL,
        header=["Origin: https://polymarket.com"],
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    ws.run_forever(ping_interval=None) # type: ignore


if __name__ == "__main__":
    main()
