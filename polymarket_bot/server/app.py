from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from polymarket_bot.server.lifespan import lifespan
from polymarket_bot.server.routes import books, debug, events, logs, metrics, odds, orders, user, ws

load_dotenv()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(events.router)
    app.include_router(books.router)
    app.include_router(user.router)
    app.include_router(orders.router)
    app.include_router(odds.router)
    app.include_router(logs.router)
    app.include_router(metrics.router)
    app.include_router(debug.router)
    app.include_router(ws.router)
    return app


app = create_app()
