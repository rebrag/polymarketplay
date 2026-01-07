from __future__ import annotations

import os
from typing import Final

from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

load_dotenv()

HOST: Final[str] = "https://clob.polymarket.com"
CHAIN_ID: Final[int] = 137


def _env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing env var: {name}")
    return v


def main() -> None:
    private_key = _env("POLY_KEY")
    funder = _env("POLY_FUNDER")  # address that holds funds (proxy/smart wallet for Magic users)
    token_id = "75629705399315100429782801927688804009370855830465152723321991275574948545131"  # outcome token (ERC1155 token id)

    client = ClobClient(
        HOST,
        key=private_key,
        chain_id=CHAIN_ID,
        signature_type=1,  # 1 for email/Magic wallet signatures
        funder=funder,
    )
    client.set_api_creds(client.create_or_derive_api_creds())

    usdc_amount = 5.0
    mo = MarketOrderArgs(
        token_id=token_id,
        amount=usdc_amount,        # BUY: amount is dollars (USDC)
        side=BUY,
        order_type=OrderType.FOK,  # or OrderType.FAK
    )

    signed = client.create_market_order(mo)
    resp = client.post_order(signed, OrderType.FOK)
    print(resp)


if __name__ == "__main__":
    main()

#command to start/restart server
#notes: python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
