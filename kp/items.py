import scrapy


class KpArticleItem(scrapy.Item):
    # обязательные
    title = scrapy.Field()
    description = scrapy.Field()
    article_text = scrapy.Field()
    publication_datetime = scrapy.Field()
    keywords = scrapy.Field()   # list[str]
    authors = scrapy.Field()    # list[str]
    source_url = scrapy.Field()

    # необязательные
    header_photo_url = scrapy.Field()
    header_photo_base64 = scrapy.Field()
