"""Public upstream test fixtures; kept outside distributed application assets."""
from pathlib import Path
import io
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]/'.artifacts'/'vision-fixtures'
ROOT.mkdir(parents=True,exist_ok=True)
def fetch(url):
    with urllib.request.urlopen(url,timeout=50) as response:return response.read()

portrait=ROOT/'portrait.jpg'
if not portrait.exists():portrait.write_bytes(fetch('https://storage.googleapis.com/mediapipe-assets/portrait.jpg'))
archive=ROOT/'coco128.zip'
if not archive.exists():archive.write_bytes(fetch('https://github.com/ultralytics/assets/releases/download/v0.0.0/coco128.zip'))
with zipfile.ZipFile(archive) as z:
    selected=[]
    for name in z.namelist():
        if '/labels/' in name and name.endswith('.txt'):
            lines=z.read(name).decode().splitlines()
            if any(line.split()[0]=='67' for line in lines if line.split()):
                image=name.replace('/labels/','/images/').replace('.txt','.jpg')
                target=ROOT/Path(image).name;target.write_bytes(z.read(image));selected.append(target.name)
    print('PHONE_FIXTURES',selected)
print('FIXTURES_READY',ROOT)
