import requests
import re
from zipfile import ZipFile
from tempfile import TemporaryFile
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

URL = 'https://ros.locationcentre.co.uk/internet/inspireAtomDataset.aspx?id=KvuAI9BV6i4%7e'
output_dir = Path(sys.argv[1])

res = requests.get(URL)
root = ET.fromstring(res.text)

try:
    output_dir.mkdir()
except FileExistsError:
    pass

for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
    if entry.find("./{http://www.w3.org/2005/Atom}title").text != 'Cadastral Parcels in EPSG:27700':
        continue

    for link in entry.findall("./{http://www.w3.org/2005/Atom}link"):
        download_url = link.get('href')
        print(f"Fetching {download_url}...")
        res = requests.get(download_url)
        with TemporaryFile(suffix='.zip') as f:
            for chunk in res.iter_content(chunk_size=8192):
                f.write(chunk)
            with ZipFile(f) as zipf:
                prefix = None
                for f in zipf.filelist:
                    match = re.match(r'^([A-Z]+)_bng\.shp$', f.filename)
                    if match:
                        prefix = match.group(1)

                if not prefix:
                    print(f"No matching file found in {download_url}")
                    continue

                for ext in ('shp', 'prj', 'shx', 'dbf'):
                    zipf.extract(f"{prefix}_bng.{ext}", path=output_dir)
