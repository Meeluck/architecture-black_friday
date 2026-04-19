#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="mongo-sharding.yml"

CONFIG_SERVICE="configsvr"
CONFIG_PORT="27019"
CONFIG_RS="configReplSet"

MONGOS_SERVICE="mongos_router"
MONGOS_PORT="27017"

SHARD1_SERVICE="shard1-rs1"
SHARD1_PORT="27018"
SHARD1_RS="shard1ReplSet"

SHARD2_SERVICE="shard2-rs1"
SHARD2_PORT="27018"
SHARD2_RS="shard2ReplSet"

DB_NAME="somedb"
COLLECTION_NAME="helloDoc"

WAIT_TIMEOUT_SEC="${WAIT_TIMEOUT_SEC:-60}"
WAIT_INTERVAL_SEC="${WAIT_INTERVAL_SEC:-2}"

log() {
  echo
  echo "==> $1"
}

debug_docker_ps() {
  log "Текущие контейнеры (docker ps)"
  docker ps
}

debug_docker_ps


log "Инициализация config server replica set"
docker compose -f "${COMPOSE_FILE}" exec -T "${CONFIG_SERVICE}" \
  mongosh --port "${CONFIG_PORT}" --quiet <<'EOF'
try {
  rs.status()
  print("configReplSet already initialized")
} catch (e) {
  rs.initiate({
    _id: "configReplSet",
    configsvr: true,
    members: [
      { _id: 0, host: "configsvr:27019" }
    ]
  })
}
EOF

log "Небольшая пауза после инициализации config server"
sleep 5

log "Инициализация shard1 replica set"
docker compose -f "${COMPOSE_FILE}" exec -T "${SHARD1_SERVICE}" \
  mongosh --port "${SHARD1_PORT}" --quiet <<'EOF'
try {
  rs.status()
  print("shard1ReplSet already initialized")
} catch (e) {
  rs.initiate({
    _id: "shard1ReplSet",
    members: [
      { _id: 0, host: "shard1-rs1:27018" }
    ]
  })
}
EOF

log "Инициализация shard2 replica set"
docker compose -f "${COMPOSE_FILE}" exec -T "${SHARD2_SERVICE}" \
  mongosh --port "${SHARD2_PORT}" --quiet <<'EOF'
try {
  rs.status()
  print("shard2ReplSet already initialized")
} catch (e) {
  rs.initiate({
    _id: "shard2ReplSet",
    members: [
      { _id: 0, host: "shard2-rs1:27018" }
    ]
  })
}
EOF

log "Ожидание стабилизации replica set'ов"
sleep 8

log "Добавление shard'ов в mongos"
docker compose -f "${COMPOSE_FILE}" exec -T "${MONGOS_SERVICE}" \
  mongosh --port "${MONGOS_PORT}" --quiet <<'EOF'
const shards = sh.status().shards || [];
const shardHosts = shards.map(s => s.host);

if (!shardHosts.includes("shard1ReplSet/shard1-rs1:27018")) {
  sh.addShard("shard1ReplSet/shard1-rs1:27018");
} else {
  print("shard1 already added");
}

if (!shardHosts.includes("shard2ReplSet/shard2-rs1:27018")) {
  sh.addShard("shard2ReplSet/shard2-rs1:27018");
} else {
  print("shard2 already added");
}

sh.status();
EOF

log "Включение шардирования и наполнение тестовыми данными"
docker compose -f "${COMPOSE_FILE}" exec -T "${MONGOS_SERVICE}" \
  mongosh --port "${MONGOS_PORT}" --quiet <<EOF
sh.enableSharding("${DB_NAME}");

db = db.getSiblingDB("${DB_NAME}");

try {
  sh.shardCollection("${DB_NAME}.${COLLECTION_NAME}", { name: "hashed" });
} catch (e) {
  print("Collection is already sharded or shardCollection failed: " + e);
}

const count = db.${COLLECTION_NAME}.countDocuments();
if (count < 1000) {
  const docs = [];
  for (let i = count; i < 1000; i++) {
    docs.push({ age: i, name: "ly" + i });
  }
  if (docs.length > 0) {
    db.${COLLECTION_NAME}.insertMany(docs);
  }
}

print("Total count: " + db.${COLLECTION_NAME}.countDocuments());
EOF

log "Проверка общего количества документов через mongos"
docker compose -f "${COMPOSE_FILE}" exec -T "${MONGOS_SERVICE}" \
  mongosh --port "${MONGOS_PORT}" --quiet <<EOF
use ${DB_NAME}
db.${COLLECTION_NAME}.countDocuments()
EOF

log "Проверка количества документов на shard1"
docker compose -f "${COMPOSE_FILE}" exec -T "${SHARD1_SERVICE}" \
  mongosh --port "${SHARD1_PORT}" --quiet <<EOF
use ${DB_NAME}
db.${COLLECTION_NAME}.countDocuments()
EOF

log "Проверка количества документов на shard2"
docker compose -f "${COMPOSE_FILE}" exec -T "${SHARD2_SERVICE}" \
  mongosh --port "${SHARD2_PORT}" --quiet <<EOF
use ${DB_NAME}
db.${COLLECTION_NAME}.countDocuments()
EOF

log "Готово"