
# Задание 4. Кэширование

## Описание

1. Скопируйте директорию с проектом mongo-sharding-repl под новым именем sharding-repl-cache.
2. В файле compose.yaml измените имя проекта на name: sharding-repl-cache.
3. Модифицируйте compose.yaml таким образом, чтобы реализовать второй вариант схемы. В качестве ориентира можете использовать пример из урока про кеширование.
4. Чтобы включить кеширование в приложении, добавьте переменную окружения:

```bash
REDIS_URL: "redis://<redis-service-name>:6379" 
```
Вместо <redis-service-name> напишите имя сервиса redis.

5. В приложении кеширование доступно для эндпоинта /<collection_name>/users. Проверьте скорость выполнения повторных запросов — она должна увеличиться.

**На что будет смотреть ревьюер:**

- Проект запускается.
- Настройка по инструкции в README.md выполняется без ошибок.
- Приложение работает и показывает общее количество документов в базе (≥ 1000), количество документов в каждом из шардов и количество реплик.
- Второй и последующие вызовы эндпоинта /<collection_name>/users выполняются <100мс.

## Настройка

### **Запуск**

`docker compose up -d`

### Авто настройка

1. Повышаем привилегии для скрипта

```bash
chmod +x mongo-init_task4.sh
```

2. Запускаем скрипт

```bash
./mongo-init_task4.sh 
```

### Ручная настройка

2. **Инициализация config server**

```bash
# 1. подключаемся
docker exec -it mongo-configsvr mongosh --port 27019 

# 2. инициализируем
rs.initiate(
{
  _id: "configReplSet",
  configsvr: true,
  members: [
    { _id: 0, host: "configsvr:27019" }
  ]
}
);
```

3. Инициализация шардов

```bash

# 1. подключаемся
docker exec -it mongo-shard1-rs1 mongosh --port 27018

# 2. инициализируем

rs.initiate(
{
  _id: "shard1ReplSet",
  members: [
    { _id: 0, host: "shard1-rs1:27018" },
    { _id: 1, host: "shard1-rs2:27018" },
    { _id: 2, host: "shard1-rs3:27018" },
  ]
}
);

```

```bash

# 1. подключаемся
docker exec -it mongo-shard2-rs1 mongosh --port 27018

# 2. инициализируем

rs.initiate(
{
  _id: "shard2ReplSet",
  members: [
    { _id: 0, host: "shard2-rs1:27018" },
    { _id: 1, host: "shard2-rs2:27018" },
    { _id: 2, host: "shard2-rs3:27018" },
  ]
}
);
```

4. Инициализация роутера

```bash
docker exec -it mongo-mongos mongosh --port 27017 

sh.addShard("shard1ReplSet/shard1-rs1:27018,shard1-rs2:27018,shard1-rs3:27018")
sh.addShard("shard2ReplSet/shard2-rs1:27018,shard2-rs2:27018,shard2-rs3:27018")

sh.status()

```

5. Наполнение тестовыми данными

```bash

docker exec -it mongo-mongos mongosh --port 27017 

sh.enableSharding("somedb")
sh.shardCollection("somedb.helloDoc", { "name" : "hashed" } )

use somedb

for(var i = 0; i < 1000; i++) db.helloDoc.insert({age:i, name:"ly"+i})

db.helloDoc.countDocuments() 
exit(); 

```

