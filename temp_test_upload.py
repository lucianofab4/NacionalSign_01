from fastapi import FastAPI, UploadFile, File
from fastapi.testclient import TestClient

app = FastAPI()

@app.post('/upload')
async def upload(files: list[UploadFile] | None = File(None)):
    return {'count': len(files or [])}

client = TestClient(app)
resp = client.post('/upload', files={'files': ('test.txt', b'data', 'text/plain')})
print(resp.status_code, resp.json())
