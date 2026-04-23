
# Задание 2. Шардирование

## Описание 

Скопируйте исходную директорию с приложением и `compose.yaml` под новым именем `mongo-sharding`.
В файле `compose.yaml` измените имя проекта на name: `mongo-sharding`.

Модифицируйте `compose.yaml` таким образом, чтобы реализовать первый вариант схемы. За основу можете взять пример из урока про шардирование.

В директории с проектом создайте файл `README.md`. Опишите там шаги для инициализации шардирования в MongoDB.

С помощью этого shell-скрипта можно автоматизировать выполнение команд на инстансах MongoDB:

```shell
docker compose exec -T <service-name> mongosh --port <mongo port> --quiet <<EOF
<mongosh commands here>
EOF  
```

Например, так выглядят команды для отображения количества документов в БД: 

```shell
somedb 
```

инстанса 

```shell
shard1 
```

:

```shell
docker compose exec -T mongo-shard1-rs1 mongosh --port 27018  <<EOF
use somedb
db.helloDoc.countDocuments()
EOF  
```

Номера портов по умолчанию для различных типов инстансов MongoDB можно узнать в документации.  

Назовите БД somedb, а коллекцию — helloDoc.

На что будет смотреть ревьюер:

- Проект запускается.
- Настройка по инструкции в README.md выполняется без ошибок.
- Приложение работает и показывает общее количество документов в базе (≥ 1000), а также количество документов в каждом из шардов.

## Настройка

### **Запуск**

`docker compose up -d`

### Авто настройка

1. Повышаем привилегии для скрипта

```bash
chmod +x mongo-init.sh
```

2. Запускаем скрипт

```bash
./mongo-init.sh 
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
  ]
}
);
```

4. Инициализация роутера

```bash
docker exec -it mongo-mongos mongosh --port 27017 

sh.addShard("shard1ReplSet/shard1-rs1:27018")
sh.addShard("shard2ReplSet/shard2-rs1:27018")

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
