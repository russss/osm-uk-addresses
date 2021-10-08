FROM python:3.9-slim

COPY . /app
RUN pip3 install -e /app

CMD uvicorn --host 0.0.0.0 --port 80 geojson_tile_server.main:app
