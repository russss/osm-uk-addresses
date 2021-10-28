FROM python:3.9-slim

WORKDIR /app
COPY . .
RUN pip3 install -e .

WORKDIR /app/geojson_tile_server
CMD uvicorn --host 0.0.0.0 --port 80 main:app
