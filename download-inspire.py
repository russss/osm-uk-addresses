import requests
from zipfile import ZipFile
from tempfile import TemporaryFile
import sys
from pathlib import Path
import lxml.html

HOST = 'https://use-land-property-data.service.gov.uk'
output_dir = Path(sys.argv[1])

res = requests.get(HOST + '/datasets/inspire/download')
root = lxml.html.document_fromstring(res.text)

try:
    output_dir.mkdir()
except FileExistsError:
    pass

for l in root.xpath("//a[contains(.,'Download .gml')]"):
    download_url = HOST + l.get('href')
    print(f"Fetching {download_url}...")
    file_name = download_url.split('/')[-1].split('.')[0] + '.gml'

    res = requests.get(download_url)
    with TemporaryFile(suffix='.zip') as f:
        for chunk in res.iter_content(chunk_size=8192):
            f.write(chunk)
        with ZipFile(f) as zipf:
            zipf.extract('Land_Registry_Cadastral_Parcels.gml', path=output_dir)
            (output_dir / 'Land_Registry_Cadastral_Parcels.gml').rename(output_dir / file_name)
