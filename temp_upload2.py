from fastapi import FastAPI, UploadFile, File
from fastapi.testclient import TestClient

app = FastAPI()

@app.post('/upload')
async def upload(files: list[UploadFile] | None = File(None), file: UploadFile | None = File(None)):
    total = len(files or []) + (1 if file else 0)
    names = []
    if files:
        names.extend([f.filename for f in files])
    if file:
        names.append(file.filename)
    return {'count': total, 'names': names}

client = TestClient(app)
resp = client.post('/upload', files=[('files', ('doc1.pdf', b'a', 'application/pdf')), ('files', ('doc2.pdf', b'b', 'application/pdf'))])
print(resp.status_code, resp.json())
resp2 = client.post('/upload', files={'file': ('doc.pdf', b'd', 'application/pdf')})
print(resp2.status_code, resp2.json())
