import databases
import mercantile
from starlette.applications import Starlette
from starlette.config import Config
from starlette.exceptions import HTTPException
from starlette.responses import Response, FileResponse
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles


config = Config(".env")
DATABASE_URL = config("DATABASE_URL")


database = databases.Database(DATABASE_URL)


async def serve(request):
    x, y, z = (
        request.path_params["x"],
        request.path_params["y"],
        request.path_params["z"],
    )

    # TODO: make zoom range configurable
    if z < 16 or z > 21:
        raise HTTPException(400, "Z coordinate out of range")

    if x < 0 or x > 2 ** z:
        raise HTTPException(400, "X coordinate out of range")

    if y < 0 or y > 2 ** z:
        raise HTTPException(400, "Y coordinate out of range")

    bounds = mercantile.bounds(x, y, z)

    row = await database.fetch_one(
        query="""
        WITH row AS (
            SELECT ST_Transform(ST_PointOnSurface(geometry), 4326) AS geometry, inspireid
            FROM split_buildings
            WHERE ST_Contains(
                ST_Transform(ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326), 27700),
                geometry)
        )
        SELECT json_build_object('type', 'FeatureCollection', 'features', json_agg(ST_AsGeoJSON(row)::json))
        FROM row""",
        values={
            "minx": bounds.west,
            "miny": bounds.south,
            "maxx": bounds.east,
            "maxy": bounds.north,
        },
    )
    return Response(row[0], media_type="application/json")


async def index(request):
    return FileResponse('index.html')


routes = [
    #  Route('/', endpoint=index, name="index", methods=["GET"]),
    #  Mount('/static', app=StaticFiles(directory='static'), name="static"),
    Route("/addresses/{z:int}/{x:int}/{y:int}.json", endpoint=serve, methods=["GET"]),
]

middleware = [
    Middleware(CORSMiddleware, allow_origins=['*'])
]

app = Starlette(
    routes=routes, middleware=middleware, on_startup=[database.connect], on_shutdown=[database.disconnect]
)
