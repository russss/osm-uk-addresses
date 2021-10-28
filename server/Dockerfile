FROM python:3.9-slim

WORKDIR /app/geojson_tile_server
COPY . .
RUN pip3 install -e .

CMD uvicorn --host 0.0.0.0 --port 80 geojson_tile_server.main:app
