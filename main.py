import os
import asyncio

from fastapi import FastAPI
from pydantic import BaseModel

import docker
import asyncpg
import uvicorn

from concurrent.futures import ThreadPoolExecutor


BASE_PATH = os.path.dirname(os.path.abspath(__file__))
IMAGES_PATH = os.path.join(BASE_PATH, 'images')


class Image(BaseModel):
    name: str
    base: str
    code: str


class Build(BaseModel):
    image_id: int


class BuildStatus:
    NEW = 'new'
    RUNNING = 'running'
    FINISHED = 'finished'


app = FastAPI()

# Для выполнения процессов докера
_executor = ThreadPoolExecutor(10)

# Глобальный пулл соеденений к бд
pool = None


async def init_db():
    """Подключение к базе docker_test, если нету создается база
    Создаются таблицы images, builds"""
    global pool
    try:
        pool = await asyncpg.create_pool(database='docker_test', user='postgres', password='postgres')
    except asyncpg.InvalidCatalogNameError:
        conn = await asyncpg.connect(database='template1', user='postgres', password='postgres')
        await conn.execute('CREATE DATABASE docker_test')
        await conn.close()
        pool = await asyncpg.create_pool(database='docker_test', user='postgres', password='postgres')

    async with pool.acquire() as conn:
        await conn.execute('''
        CREATE TABLE IF NOT EXISTS images(
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            base TEXT NOT NULL,
            code TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS builds(
            id SERIAL PRIMARY KEY,
            image_id INT REFERENCES images (id),
            container_id TEXT,
            is_success BOOLEAN DEFAULT true,
            status VARCHAR(10) DEFAULT 'new'
        );
        ''')


@app.on_event('startup')
async def startup():
    """Создается папка под образы и вызов инициализаций базы"""
    if(not os.path.exists(IMAGES_PATH)):
        os.mkdir(IMAGES_PATH)

    await init_db()


@app.on_event("shutdown")
async def shutdown():
    await pool.close()


@app.get('/images')
async def images():
    """Возвращает список образов из базы"""
    async with pool.acquire() as conn:
        images = await conn.fetch('SELECT * FROM images')
    return {'images': images}


@app.post('/images')
async def create(image: Image):
    """Создаёт образ в базе"""
    async with pool.acquire() as conn:
        image = await conn.fetch('''
            INSERT INTO images(name, base, code) 
            VALUES($1, $2, $3) 
            RETURNING id, name, base, code
        ''', image.name, image.base, image.code)
    return {'status': 'ok', 'image': image}


@app.get('/builds')
async def builds():
    """Возвращает билдов из базы"""
    async with pool.acquire() as conn:
        builds = await conn.fetch('SELECT * FROM builds')
    return {'builds': builds}


@app.post('/builds')
async def build(build: Build):
    """Создаёт билд из образа и запускает контейнер"""
    async with pool.acquire() as conn:
        image = await conn.fetchrow('SELECT * FROM images WHERE id=$1', build.image_id)
        if image:
            build_record = await conn.fetchrow('''
                INSERT INTO builds (image_id) 
                VALUES($1) 
                RETURNING id, image_id, container_id, is_success, status
                ''', build.image_id)
            asyncio.create_task(start_build(image, build_record))
            return {'status': 'ok', 'build': build_record}
        else:
            return {'status': 'Not found'}


@app.post('/stop/{build_id}')
async def stop(build_id: int):
    """Останавливает запущенный контейнер"""
    async with pool.acquire() as conn:
        build_record = await conn.fetchrow('SELECT * FROM builds WHERE id=$1', build_id)
        if build_record:
            asyncio.create_task(stop_build(build_record))
            return {'status': 'ok'}
        else:
            return {'status': 'Not found'}


async def start_build(image_record, build_record):
    """
    Запускает процессы создания образа и билда. в отдельный тред через run_in_executor.
    По завершению обновляет базу билдов,
    Если все прошло успешно, ставится is_success=true, status='running',
    иначе is_success=false
    """
    async with pool.acquire() as conn:
        loop = asyncio.get_running_loop()
        container = await loop.run_in_executor(_executor, build_and_run, image_record)
        if container:
            await conn.execute('''
            UPDATE builds SET is_success=$1, status=$2, container_id=$3 WHERE id=$4
            ''', True, BuildStatus.RUNNING, container.id, build_record['id'])
        else:
            await conn.execute("UPDATE builds SET is_success=$1 WHERE id=$2", False, build_record['id'])

def build_and_run(image_record):
    """
    Создает образ и запускает контейнер,
    Именно в таком варианте можно было докерфайл не обновлять каждый раз
    Но в реальности запись в бд могла измениться, поэтому оставил как есть
    """
    client = docker.from_env(timeout=300)
    try:
        image_name = image_record['name'].replace(' ', '_')
        image_path, dockerfile_path = make_dockerfile(image_record)
        image, _ = client.images.build(path=image_path, dockerfile=dockerfile_path, tag=image_name)
        container = client.containers.run(image, detach=True)
        return container
    except docker.errors.BuildError as e:
        print("Build error", e)
    except docker.errors.ContainerError as e:
        print("Container error", e)
    except docker.errors.ImageNotFound as e:
        print("Image nor found", e)
    except docker.errors.APIError as e:
        print("Server error", e)


def make_dockerfile(image_record):
    """Создаёт докерфайл
    Возвращает путь до папки образа и до докефайла"""
    image_name = image_record['name'].replace(' ', '_')
    image_path = os.path.join(IMAGES_PATH, image_name)

    if not os.path.exists(image_path):
        os.mkdir(image_path)

    dockerfile_path = os.path.join(image_path, 'Dockerfile')
    dockerfile_content = f'FROM {image_record["base"]}\n{image_record["code"]}'
    f = open(dockerfile_path, 'w')
    f.write(dockerfile_content)
    f.close()

    return (image_path, dockerfile_path)


async def stop_build(build_record):
    """
    Запускает процесс остановки через run_in_executor.
    По завершению обновляет базу билдов
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, stop_container, build_record['container_id'])

    async with pool.acquire() as conn:
        await conn.execute("UPDATE builds SET status=$1 WHERE id=$2", BuildStatus.FINISHED, build_record['id'])


def stop_container(container_id):
    """Остановка контейнера"""
    client = docker.from_env(timeout=300)
    try:
        client.containers.get(container_id).stop()
    except docker.errors.NotFound as e:
        print("Container not found", e)
    except docker.errors.APIError as e:
        print("Server error", e)


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000)
