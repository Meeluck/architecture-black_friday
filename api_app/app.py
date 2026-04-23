import json
import logging
import os
import time
from typing import List, Optional

# Асинхронный драйвер MongoDB
import motor.motor_asyncio

# BSON-тип MongoDB для поля _id
from bson import ObjectId

# FastAPI: создание API, описание тела запроса, HTTP-ошибки и статусы
from fastapi import Body, FastAPI, HTTPException, status

# Библиотека для кэширования ответов FastAPI
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.decorator import cache

# Кастомное middleware для логирования
from logmiddleware import RouterLoggingMiddleware, logging_config

# Pydantic-модели для валидации и сериализации
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.functional_validators import BeforeValidator

# Ошибки pymongo
from pymongo import errors

# Асинхронный Redis-клиент
from redis import asyncio as aioredis

# Для Annotated-типа
from typing_extensions import Annotated


# Настройка логирования
logging.config.dictConfig(logging_config)
logger = logging.getLogger(__name__)


# Создаём FastAPI-приложение
app = FastAPI()

# Подключаем middleware, которое будет логировать запросы
app.add_middleware(
    RouterLoggingMiddleware,
    logger=logger,
)


# Читаем настройки из переменных окружения
DATABASE_URL = os.environ["MONGODB_URL"]
DATABASE_NAME = os.environ["MONGODB_DATABASE_NAME"]

# Redis необязателен, поэтому берём через getenv
REDIS_URL = os.getenv("REDIS_URL", None)


# Заглушка вместо кэша.
# Если Redis не настроен, этот декоратор ничего не делает.
def nocache(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


# Если Redis есть — используем настоящий кэш.
# Если Redis нет — подменяем его пустым декоратором.
if REDIS_URL:
    cache = cache
else:
    cache = nocache


# Создаём MongoDB-клиент и выбираем базу данных
client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URL)
db = client[DATABASE_NAME]


# Тип для MongoDB ObjectId.
# В ответах API он будет превращён в строку.
PyObjectId = Annotated[str, BeforeValidator(str)]


# Код, который выполняется при старте приложения
@app.on_event("startup")
async def startup():
    # Если Redis настроен — инициализируем кэш
    if REDIS_URL:
        redis = aioredis.from_url(REDIS_URL, encoding="utf8", decode_responses=True)
        FastAPICache.init(RedisBackend(redis), prefix="api:cache")


# Модель одного пользователя
class UserModel(BaseModel):
    # id в Python соответствует _id в MongoDB
    id: Optional[PyObjectId] = Field(alias="_id", default=None)

    # Обязательные поля
    age: int = Field(...)
    name: str = Field(...)


# Модель ответа со списком пользователей
class UserCollection(BaseModel):
    users: List[UserModel]

async def get_collection_stats(collection_name: str) -> dict:
    """
    Возвращает статистику по коллекции:
    - общее количество документов
    - количество документов по каждому шарду, если коллекция шардирована

    Для шардированной коллекции pipeline с $collStats возвращает
    по одной записи на shard. В каждой записи есть:
    - shard: имя шарда
    - count: количество документов на шарде
    """
    collection = db.get_collection(collection_name)

    # Точный общий count по коллекции
    total_documents = await collection.count_documents({})

    documents_by_shard = None

    try:
        shard_stats_cursor = collection.aggregate(
            [
                {
                    "$collStats": {
                        "count": {}
                    }
                }
            ]
        )
        shard_stats = await shard_stats_cursor.to_list(length=None)

        # Если коллекция шардирована, Mongo обычно вернёт несколько документов,
        # по одному на каждый shard, и в них будет поле "shard".
        per_shard = {}
        for item in shard_stats:
            shard_name = item.get("shard")
            shard_count = item.get("count")

            # Для нешардированной коллекции поля shard может не быть
            if shard_name is not None and shard_count is not None:
                per_shard[shard_name] = shard_count

        if per_shard:
            documents_by_shard = per_shard

    except Exception as ex:
        # Не валим весь endpoint, если статистику по шардам получить не удалось.
        logger.warning(
            "Failed to get shard stats for collection '%s': %s",
            collection_name,
            ex,
        )

    return {
        "documents_count": total_documents,
        "documents_by_shard": documents_by_shard,
    }


# Получить информацию по шардам и репликам
async def get_shards_info() -> dict:
    """
    Возвращает информацию по каждому шарду:
    - host: строка из listShards
    - replica_set_name: имя replica set
    - replica_count: количество членов replica set
    - replica_members: список узлов replica set
    """
    shards_info = {}

    shards_list = await client.admin.command({"listShards": 1})

    for shard in shards_list.get("shards", []):
        shard_id = shard["_id"]
        shard_host = shard["host"]  # например: rs0/shard1a:27018,shard1b:27018,shard1c:27018

        replica_set_name = None
        replica_members = []

        if "/" in shard_host:
            replica_set_name, members_part = shard_host.split("/", 1)
            replica_members = [member.strip() for member in members_part.split(",") if member.strip()]
        else:
            # Теоретически shard может быть не replica set, а одиночным узлом
            replica_members = [shard_host]

        shards_info[shard_id] = {
            "host": shard_host,
            "replica_set_name": replica_set_name,
            "replica_count": len(replica_members),
            "replica_members": replica_members,
        }

    return shards_info


async def get_sharded_distribution() -> dict:
    """
    Возвращает распределение документов по шардам
    для шардированных коллекций текущей БД.
    """
    distribution = {}

    try:
        admin_db = client["admin"]

        # $shardedDataDistribution должен запускаться на admin DB через mongos
        cursor = admin_db.aggregate(
            [
                {"$shardedDataDistribution": {}},
                {"$match": {"ns": {"$regex": f"^{DATABASE_NAME}\\."}}},
            ]
        )

        items = await cursor.to_list(length=None)

        for item in items:
            ns = item.get("ns")  # например "somedb.helloDoc"
            if not ns or "." not in ns:
                continue

            db_name, collection_name = ns.split(".", 1)
            if db_name != DATABASE_NAME:
                continue

            per_shard = {}
            for shard_info in item.get("shards", []):
                shard_name = shard_info.get("shardName")
                shard_documents = shard_info.get("numOwnedDocuments", 0)

                if shard_name is not None:
                    per_shard[shard_name] = shard_documents

            if per_shard:
                distribution[collection_name] = per_shard

    except Exception as ex:
        logger.exception("Failed to get sharded distribution")

    return distribution

# Диагностический эндпоинт
@app.get("/")
async def root():
    # Список коллекций в текущей БД
    collection_names = await db.list_collection_names()

    # Топология MongoDB
    topology_description = client.topology_description
    read_preference = client.client_options.read_preference
    topology_type = topology_description.topology_type_name
    replicaset_name = topology_description.replica_set_name

    # Информация по шардам и репликам
    shards = None
    if topology_type == "Sharded":
        shards = await get_shards_info()

    # Распределение документов по шардам для шардированных коллекций
    sharded_distribution = {}
    if topology_type == "Sharded":
        sharded_distribution = await get_sharded_distribution()

    # Сбор статистики по коллекциям и общий счётчик по базе
    collections = {}
    database_documents_count = 0
    database_documents_by_shard = {}

    for collection_name in collection_names:
        collection = db.get_collection(collection_name)

        # Точный count по коллекции
        documents_count = await collection.count_documents({})
        database_documents_count += documents_count

        # Распределение по шардам для конкретной коллекции
        documents_by_shard = sharded_distribution.get(collection_name)

        collections[collection_name] = {
            "documents_count": documents_count,
            "documents_by_shard": documents_by_shard,
        }

        # Агрегируем общее количество документов по каждому шарду по всей БД
        if documents_by_shard:
            for shard_name, shard_documents in documents_by_shard.items():
                database_documents_by_shard[shard_name] = (
                    database_documents_by_shard.get(shard_name, 0) + shard_documents
                )

    # Статус репликации для текущего подключения
    try:
        replica_status = await client.admin.command("replSetGetStatus")
        replica_status = json.dumps(replica_status, indent=2, default=str)
    except errors.OperationFailure:
        replica_status = "No Replicas"

    # Проверяем, включён ли кэш
    cache_enabled = False
    if REDIS_URL:
        cache_enabled = FastAPICache.get_enable()

    # Возвращаем диагностическую информацию
    return {
        "mongo_topology_type": topology_type,
        "mongo_replicaset_name": replicaset_name,
        "mongo_db": DATABASE_NAME,
        "read_preference": str(read_preference),
        "mongo_nodes": client.nodes,
        "mongo_primary_host": client.primary,
        "mongo_secondary_hosts": client.secondaries,
        "mongo_is_primary": client.is_primary,
        "mongo_is_mongos": client.is_mongos,

        "database_documents_count": database_documents_count,
        "database_documents_by_shard": database_documents_by_shard,

        "collections": collections,
        "shards": shards,

        "cache_enabled": cache_enabled,
        "status": "OK",
    }


# Эндпоинт: посчитать количество документов в коллекции
@app.get("/{collection_name}/count")
async def collection_count(collection_name: str):
    collection = db.get_collection(collection_name)
    items_count = await collection.count_documents({})

    return {
        "status": "OK",
        "mongo_db": DATABASE_NAME,
        "items_count": items_count,
    }


# Эндпоинт: получить список пользователей
@app.get(
    "/{collection_name}/users",
    response_description="List all users",
    response_model=UserCollection,
    response_model_by_alias=False,
)
@cache(expire=60 * 1)  # кэш ответа на 60 секунд
async def list_users(collection_name: str):
    """
    Возвращает список пользователей из коллекции.
    Без пагинации, максимум 1000 записей.
    """

    # Искусственная задержка 1 секунда.
    # Для async-кода это неудачное решение: лучше использовать await asyncio.sleep(1)
    time.sleep(1)

    collection = db.get_collection(collection_name)

    # Читаем максимум 1000 документов и заворачиваем в модель ответа
    return UserCollection(users=await collection.find().to_list(1000))


# Эндпоинт: получить одного пользователя по имени
@app.get(
    "/{collection_name}/users/{name}",
    response_description="Get a single user",
    response_model=UserModel,
    response_model_by_alias=False,
)
async def show_user(collection_name: str, name: str):
    """
    Ищет пользователя по полю name.
    """

    collection = db.get_collection(collection_name)

    # Пытаемся найти документ по имени
    if (user := await collection.find_one({"name": name})) is not None:
        return user

    # Если не нашли — возвращаем HTTP 404
    raise HTTPException(status_code=404, detail=f"User {name} not found")


# Эндпоинт: создать пользователя
@app.post(
    "/{collection_name}/users",
    response_description="Add new user",
    response_model=UserModel,
    status_code=status.HTTP_201_CREATED,
    response_model_by_alias=False,
)
async def create_user(collection_name: str, user: UserModel = Body(...)):
    """
    Создаёт нового пользователя в коллекции.
    """

    collection = db.get_collection(collection_name)

    # Вставляем документ в MongoDB.
    # exclude=["id"] — поле id не передаём, MongoDB сама создаст _id.
    # by_alias=True — используем имена полей как в БД, то есть _id вместо id.
    new_user = await collection.insert_one(
        user.model_dump(by_alias=True, exclude=["id"])
    )

    # Сразу читаем созданный документ обратно по _id
    created_user = await collection.find_one({"_id": new_user.inserted_id})

    # Возвращаем созданный объект клиенту
    return created_user