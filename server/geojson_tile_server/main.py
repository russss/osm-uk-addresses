import re
import databases
import mercantile
from starlette.applications import Starlette
from starlette.config import Config
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response
from starlette.templating import Jinja2Templates
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles


config = Config(".env")
templates = Jinja2Templates(directory="templates")
DATABASE_URL = config("DATABASE_URL")


database = databases.Database(DATABASE_URL)

MIN_ZOOM = 16
MAX_ZOOM = 21

LAYERS = {
    "addresses": """
        SELECT ST_Transform(ST_PointOnSurface(geometry), {srid}) AS geometry, inspireid
            FROM split_buildings
            WHERE ST_Intersects(ST_Transform({bbox}, 27700), geometry)
    """,
    "inspire": """
        SELECT ST_Transform(wkb_geometry, {srid}) AS geometry, inspireid
            FROM inspire
            WHERE ST_Intersects(ST_Transform({bbox}, 27700), wkb_geometry)
    """,
    "split_buildings": """
        SELECT ST_Transform(geometry, {srid}) AS geometry, inspireid
            FROM split_buildings
            WHERE ST_Intersects(ST_Transform({bbox}, 27700), geometry)
    """,
}

FORMATS = {
    "json": {"mimetype": "application/json", "name": "GeoJSON"},
    "mvt": {"mimetype": "application/vnd.vector-tile", "name": "Mapbox Vector Tiles"},
}


async def serve(request):
    layer = request.path_params["layer"]
    format = request.path_params["format"]

    if layer not in LAYERS:
        raise HTTPException(404)

    if format not in FORMATS:
        raise HTTPException(404)

    try:
        x, y, z = (
            int(request.path_params["x"]),
            int(request.path_params["y"]),
            int(request.path_params["z"]),
        )
    except ValueError:
        raise HTTPException(400, "Invalid coordinates")

    # TODO: make zoom range configurable
    if z < MIN_ZOOM or z >= MAX_ZOOM:
        raise HTTPException(404, "Z coordinate out of range")

    if x < 0 or x > 2 ** z:
        raise HTTPException(404, "X coordinate out of range")

    if y < 0 or y > 2 ** z:
        raise HTTPException(404, "Y coordinate out of range")

    srid = 3857
    if format == "json":
        srid = 4326

    bounds = mercantile.bounds(x, y, z)
    bbox_sql = f"ST_MakeEnvelope({bounds.west}, {bounds.south}, {bounds.east}, {bounds.north}, 4326)"
    sql = LAYERS[layer].format(bbox=bbox_sql, srid=srid)

    if format == "json":
        layer_sql = f"""
            WITH row AS ({sql})
            SELECT json_build_object('type', 'FeatureCollection', 'features', json_agg(ST_AsGeoJSON(row)::json))
            FROM row"""
    elif format == "mvt":
        layer_sql = f"""
            WITH mvtgeom AS (
                WITH row AS ({sql})
                SELECT ST_AsMVTGeom(geometry, ST_TileEnvelope({z}, {x}, {y}), buffer => 64) AS geom, inspireid AS id FROM row
            )
            SELECT ST_AsMVT(mvtgeom.*, '{layer}') FROM mvtgeom
        """

    row = await database.fetch_one(query=layer_sql)
    return Response(row[0], media_type=FORMATS[format]["mimetype"])


async def tilejson(request):
    layer = request.path_params["layer"]
    if layer not in LAYERS:
        raise HTTPException(404)

    format = request.path_params["format"]
    if format not in FORMATS:
        raise HTTPException(404)

    return JSONResponse(
        {
            "tilejson": "2.2.0",
            "tiles": [
                request.url_for(
                    "serve", layer=layer, z="{z}", x="{x}", y="{y}", format=format
                )
            ],
            "minzoom": MIN_ZOOM,
            "maxzoom": MAX_ZOOM,
        }
    )


async def index(request):
    return templates.TemplateResponse("index.html", {"request": request})


async def layers_list(request):
    return templates.TemplateResponse(
        "layers.html",
        {"request": request, "layers": LAYERS.keys()},
    )


routes = [
    Route("/", endpoint=index, name="index", methods=["GET"]),
    Route("/layers", endpoint=layers_list, name="layers_list", methods=["GET"]),
    Mount("/static", app=StaticFiles(directory="static"), name="static"),
    Route("/{layer:str}/{format:str}.json", endpoint=tilejson, methods=["GET"]),
    Route(
        "/{layer:str}/{z:str}/{x:str}/{y:str}.{format:str}",
        endpoint=serve,
        name="serve",
        methods=["GET"],
    ),
]

middleware = [Middleware(CORSMiddleware, allow_origins=["*"])]

app = Starlette(
    routes=routes,
    middleware=middleware,
    on_startup=[database.connect],
    on_shutdown=[database.disconnect],
)
