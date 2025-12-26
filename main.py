# main.py
from __future__ import annotations

from http import HTTPStatus
from os import getenv
from typing import Any, Mapping

import html
import pymongo
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


class NewsArticle(BaseModel):
    title: str
    description: str
    article_text: str
    publication_datetime: str
    header_photo_url: str | None = Field(None)
    header_photo_base64: str | None = Field(None)
    keywords: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    source_url: str


app = FastAPI(title="News Page Generator service", description="Study Case Example")

_mongo_client: pymongo.MongoClient | None = None


def _env(name: str, default: str | None = None) -> str | None:
    v = getenv(name)
    return v if v not in (None, "") else default


def _build_mongo_uri() -> str:
    mongo_user = _env("MONGO_USER")
    mongo_password = _env("MONGO_PASSWORD")
    mongo_host = _env("MONGO_HOST", "localhost")
    mongo_port = _env("MONGO_PORT", "27017")
    mongo_auth_source = _env("MONGO_AUTH_SOURCE", "admin")

    if not mongo_user or not mongo_password:
        raise RuntimeError("MONGO_USER and MONGO_PASSWORD must be set")

    return f"mongodb://{mongo_user}:{mongo_password}@{mongo_host}:{mongo_port}/?authSource={mongo_auth_source}"


@app.on_event("startup")
def startup():
    global _mongo_client
    _mongo_client = pymongo.MongoClient(
        _build_mongo_uri(),
        serverSelectionTimeoutMS=5000,
    )
    # Проверяем соединение сразу, чтобы не ловить 500 “внезапно”
    _mongo_client.admin.command("ping")


@app.on_event("shutdown")
def shutdown():
    global _mongo_client
    if _mongo_client is not None:
        _mongo_client.close()
        _mongo_client = None


def get_collection() -> pymongo.collection.Collection[Mapping[str, Any] | Any]:
    if _mongo_client is None:
        raise RuntimeError("Mongo client is not initialized")

    # Совместимо с вашими переменными из Scrapy:
    mongo_db = _env("MONGO_DB", "items")
    collection = _env("MONGO_COLLECTION", "kp_articles")

    # (опционально) совместимость с альтернативными именами:
    mongo_db = _env("MONGO_DATABASE", mongo_db)
    collection = _env("MONGO_DATABASE_COLLECTION", collection)

    return _mongo_client[mongo_db][collection]


def _e(s: str | None) -> str:
    return html.escape(s or "", quote=True)


async def _sample_articles(col, size: int) -> list[NewsArticle]:
    # Вынесено в threadpool, чтобы не блокировать event loop
    def _do():
        total = col.count_documents({})
        if total == 0:
            return []

        s = min(size, total)

        docs = list(
            col.aggregate(
                [
                    {"$sample": {"size": s}},
                    {"$project": {"_id": 0}},
                ]
            )
        )
        out: list[NewsArticle] = []
        for d in docs:
            d.pop("_id", None)
            try:
                out.append(NewsArticle(**d))
            except Exception:
                continue
        return out

    return await run_in_threadpool(_do)


@app.get("/articles", tags=["HTML Article Manager"])
async def get_random_articles_in_html(
    col=Depends(get_collection),
    size: int = Query(10, ge=1, le=500),
) -> HTMLResponse:
    articles = await _sample_articles(col, size)
    if not articles:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="There is no any articles",
        )

    html_parts: list[str] = [
        """<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Новости онлайн</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    .article { border: 1px solid #ccc; margin-bottom: 20px; padding: 10px; border-radius: 8px; }
    .title { font-size: 18px; font-weight: bold; }
    .description { font-weight: 600; color: #555; margin-top: 6px; }
    .article_text { margin: 10px 0; white-space: pre-wrap; }
    .meta { margin: 5px 0; color: #444; font-size: 13px; }
    .source_url a { color: #0066cc; text-decoration: none; }
    .source_url a:hover { text-decoration: underline; }
    img { max-width: 360px; display: block; margin-top: 10px; border-radius: 8px; }
  </style>
</head>
<body>
  <h1>Сводка новостей</h1>
"""
    ]

    for a in articles:
        html_parts.append(
            f"""
  <div class="article">
    <div class="title">{_e(a.title)}</div>
    <div class="description">{_e(a.description)}</div>
    <div class="article_text">{_e(a.article_text)}</div>
    <div class="meta"><b>Дата публикации:</b> {_e(a.publication_datetime)}</div>
    <div class="meta"><b>Ключевые слова:</b> {_e(", ".join(a.keywords))}</div>
    <div class="meta"><b>Авторы:</b> {_e(", ".join(a.authors))}</div>
    <div class="meta source_url"><b>Ссылка на источник:</b>
      <a href="{_e(a.source_url)}" target="_blank" rel="noreferrer">{_e(a.source_url)}</a>
    </div>
"""
        )
        if a.header_photo_base64:
            html_parts.append(f"""    <img src="data:image/jpeg;base64,{a.header_photo_base64}" alt="header photo"/>""")
            if a.header_photo_url:
                html_parts.append(
                    f"""
    <div class="meta source_url"><a href="{_e(a.header_photo_url)}" target="_blank" rel="noreferrer">Ссылка на фото</a></div>
"""
                )
        html_parts.append("  </div>\n")

    html_parts.append("</body></html>")

    return HTMLResponse(content="".join(html_parts), status_code=200)
