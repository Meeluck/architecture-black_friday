
# Задание 2. Репликация

## Описание

1. Скопируйте директорию с проектом `mongo-sharding` под новым именем `mongo-sharding-repl`.
2. В файле `compose.yaml` измените имя проекта на name: `mongo-sharding-repl`.
3. Модифицируйте `compose.yaml` таким образом, чтобы реализовать второй вариант схемы. За основу можете взять пример из урока про репликацию и кеширование.
4. В директории с проектом создайте файл **README.md**. Опишите там шаги, которые нужно выполнить, чтобы настроить репликацию для каждого шарда в MongoDB.

> Не забывайте, что с помощью shell-скрипта можно автоматизировать выполнение команд.


### На что будет смотреть ревьюер:

- Проект запускается.
- Настройка по инструкции в README.md выполняется без ошибок.
- Приложение работает и показывает общее количество документов в базе (≥ 1000), количество документов в каждом из шардов, а также количество реплик.

## Настройка

### **Запуск**

`docker compose up -d`

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
