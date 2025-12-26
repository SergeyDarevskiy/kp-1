import base64
from io import BytesIO

import aiohttp
from aiohttp.client_exceptions import InvalidUrlClientError
from PIL import Image


class PhotoDownloaderPipeline:
    def __init__(self, result_image_quality: int):
        self.result_image_quality = result_image_quality

    @classmethod
    def from_crawler(cls, crawler):
        result_image_quality = crawler.settings.get("RESULT_IMAGE_QUALITY", 35)
        return cls(result_image_quality=result_image_quality)

    def compress_image(self, image_content: bytes):
        input_buffer = BytesIO(image_content)
        output_buffer = BytesIO()
        img = Image.open(input_buffer)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(output_buffer, format="JPEG", quality=self.result_image_quality, optimize=True)
        return output_buffer.getvalue()

    async def _download_photo_to_base64(self, url: str):
        async with aiohttp.ClientSession() as session:
            response = await session.get(url)
            if response.status != 200:
                return ""
            content = await response.read()
            compressed_bytes = self.compress_image(image_content=content)
            encoded_image = base64.b64encode(compressed_bytes).decode("utf-8")
            return encoded_image

    async def process_item(self, item, spider):
        # допускаем пустые/None
        if item.get("header_photo_url"):
            try:
                photo_base64 = await self._download_photo_to_base64(item["header_photo_url"])
            except InvalidUrlClientError:
                item["header_photo_url"] = None
                item["header_photo_base64"] = None
                return item
            item["header_photo_base64"] = photo_base64
        else:
            item["header_photo_base64"] = None
        return item



import os
from datetime import datetime, timezone

from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError


class MongoPipeline:
    def __init__(self, uri: str, db_name: str, collection_name: str):
        self.uri = uri
        self.db_name = db_name
        self.collection_name = collection_name
        self.client = None
        self.collection = None

    @classmethod
    def from_crawler(cls, crawler):
        mongo_user = os.getenv("MONGO_USER", "admin")
        mongo_password = os.getenv("MONGO_PASSWORD", "adminpass")
        mongo_auth_source = os.getenv("MONGO_AUTH_SOURCE", "admin")
        mongo_db = os.getenv("MONGO_DB", "items")

        host = crawler.settings.get("MONGO_HOST", "localhost")
        port = crawler.settings.get("MONGO_PORT", 27017)
        collection = crawler.settings.get("MONGO_COLLECTION", "kp_articles")

        uri = f"mongodb://{mongo_user}:{mongo_password}@{host}:{port}/?authSource={mongo_auth_source}"
        return cls(uri=uri, db_name=mongo_db, collection_name=collection)

    def open_spider(self, spider):
        self.client = MongoClient(self.uri)
        db = self.client[self.db_name]
        self.collection = db[self.collection_name]
        # чтобы не было дублей по ссылке
        self.collection.create_index([("source_url", ASCENDING)], unique=True)

    def close_spider(self, spider):
        if self.client:
            self.client.close()

    def process_item(self, item, spider):
        doc = dict(item)

        # минимальная нормализация
        doc.setdefault("header_photo_url", None)
        doc.setdefault("header_photo_base64", None)

        # сервисные поля (не обязательны, но удобно)
        doc["parsed_at_utc"] = datetime.now(timezone.utc).isoformat()

        try:
            self.collection.insert_one(doc)
        except DuplicateKeyError:
            # если уже есть — можно игнорировать или обновлять
            self.collection.update_one(
                {"source_url": doc["source_url"]},
                {"$set": doc},
                upsert=True,
            )
        return item
