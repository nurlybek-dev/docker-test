# Docker services
# Установка
```
git clone https://github.com/nurlybek-dev/docker-test.git
cd docker-test
# С виртуальным окружением либо без него
pip install -r requirements.txt
```

# Запуск
```
python main.py
Сайт будет доступен по локалхосту на 8000 порту.
```

# Использование

```
Роуты
GET /images - Список образов
POST /images - Создание образа, возращает экземпляр созданного образа
{
    "name": "image name",
    "base": "image base",
    "code": "image code"
}

GET /builds - Список билдов
POST /builds - Создание билда и его запуск, возвращает экземпляр созданного билда
{
    "image_id": id
}

POST /stop/<build_id> - Остановка билда
```

# Примеры POST

## Образы
```
# Redis server
curl -X 'POST' \
  'http://127.0.0.1:8000/images' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "name": "redis-serv",
  "base": "redis",
  "code": "CMD [\"redis-server\"]"
}'

# Alpine image echo
curl -X 'POST' \
  'http://127.0.0.1:8000/images' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "name": "alpine-hello-world",
  "base": "alpine",
  "code": "CMD [\"echo\", \"Hello world\"]"
}'

```

## Билды
```
# Redis server
curl -X 'POST' \
  'http://127.0.0.1:8000/builds' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "image_id": 1
}'

# Alpine image echo
curl -X 'POST' \
  'http://127.0.0.1:8000/builds' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "image_id": 2
}'

```

## Остановка
```
curl -X 'POST' \
  'http://127.0.0.1:8000/stop/1' \
  -H 'accept: application/json' \
  -d ''
```
