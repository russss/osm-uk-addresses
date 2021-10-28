# Tile Server

This is a simple tile server which serves the address data as tiled GeoJSON using the same ["Slippy map" tiling convention](https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames) as OSM map tiles.

It requires the PostGIS database URL to be provided as an environment variable, e.g.:

    DATABASE_URL="postgresql://user:password@host/osm_addresses"

To run a development instance with reloading:

    uvicorn --reload geojson_tile_server.main:app

An example URL is:

    http://127.0.0.1:8000/addresses/17/65492/43567.json

(Only zoom levels 16-21 are currently supported)
