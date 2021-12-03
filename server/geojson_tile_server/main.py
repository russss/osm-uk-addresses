import logging
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
from asyncio.exceptions import TimeoutError
from asyncpg.exceptions import PostgresSyntaxError

log = logging.getLogger(__name__)
config = Config(".env")
templates = Jinja2Templates(directory="templates")
DATABASE_URL = config("DATABASE_URL")

database = databases.Database(
    DATABASE_URL,
    command_timeout=5,
    server_settings={"application_name": "osm_addresses_tile_server"},
)

MIN_ZOOM = 16
MAX_ZOOM = 21

fields = {}

LAYERS = {
    "addresses": """
        SELECT ST_Transform(representative_point(geometry), {srid}) AS geometry, 
                count(uprn.uprn) AS urpn_count,
                CASE WHEN count(uprn.uprn) = 1 THEN max(uprn.uprn)::text ELSE NULL END AS "ref:GB:uprn",
                inspireid AS "ref:GB:inspire"
            FROM split_buildings, uprn
            WHERE ST_Intersects(ST_Transform({bbox}, 27700), geometry)
            AND ST_Contains(split_buildings.geometry, uprn.geom)
            GROUP BY split_buildings.geometry, split_buildings.inspireid
    """,
    "inspire": """
        SELECT ST_Transform(wkb_geometry, {srid}) AS geometry, inspireid AS "ref:GB:inspire"
            FROM inspire
            WHERE ST_Intersects(ST_Transform({bbox}, 27700), wkb_geometry)
    """,
    "split_buildings": """
        SELECT ST_Transform(geometry, {srid}) AS geometry, inspireid AS "ref:GB:inspire"
            FROM split_buildings
            WHERE ST_Intersects(ST_Transform({bbox}, 27700), geometry)
    """,
    "uprn": """
        SELECT ST_Transform(geom, {srid}) AS geometry, uprn AS "ref:GB:uprn"
            FROM uprn
            WHERE ST_Intersects(ST_Transform({bbox}, 27700), geom)
    """,
}

FORMATS = {
    "json": {"mimetype": "application/json", "name": "GeoJSON"},
    "mvt": {
        "mimetype": "application/vnd.mapbox-vector-tile",
        "name": "Mapbox Vector Tiles",
    },
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
        bounds = mercantile.bounds(x, y, z)
        bbox_sql = f"ST_MakeEnvelope({bounds.west}, {bounds.south}, {bounds.east}, {bounds.north}, 4326)"
        srid = 4326
    elif format == "mvt":
        bbox_sql = f"ST_TileEnvelope({z}, {x}, {y}, margin => (64.0 / 4096))"

    sql = LAYERS[layer].format(bbox=bbox_sql, srid=srid)

    if format == "json":
        layer_sql = f"""
            WITH row AS ({sql})
            SELECT json_build_object('type', 'FeatureCollection', 'features', json_agg(ST_AsGeoJSON(row)::json))
            FROM row"""
    elif format == "mvt":
        field_sql = ", ".join(['"' + field + '"' for field in fields[layer]])
        layer_sql = f"""
            WITH mvtgeom AS (
                WITH row AS ({sql})
                SELECT ST_AsMVTGeom(geometry, ST_TileEnvelope({z}, {x}, {y}), buffer => 64) AS geom, {field_sql} FROM row
            )
            SELECT ST_AsMVT(mvtgeom.*, '{layer}') FROM mvtgeom
        """

    try:
        row = await database.fetch_one(query=layer_sql)
    except TimeoutError:
        log.warn("Timeout while executing SQL query: %s", str(layer_sql))
        raise HTTPException(503, "Database timeout")
    except PostgresSyntaxError:
        log.warn("Invalid SQL query: %s", str(layer_sql))
        raise HTTPException(500, "Database error")
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


async def load_fields():
    log.info("Loading field names...")
    bbox_sql = "ST_MakeEnvelope(-180, -90, 180, 90, 4326)"
    for layer, sql in LAYERS.items():
        sql = sql.format(bbox=bbox_sql, srid=4326)
        row = await database.fetch_one(query=sql + "LIMIT 1")
        fields[layer] = set(row.keys()) - {"geometry"}
    log.info("Field names loaded")


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
    on_startup=[database.connect, load_fields],
    on_shutdown=[database.disconnect],
)
