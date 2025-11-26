from fastapi import FastAPI, UploadFile, File
from fastapi.testclient import TestClient

app = FastAPI()

@app.post('/upload')
async def upload(file: UploadFile | None = File(None)):
    return {'has_file': file is not None}

client = TestClient(app)
resp = client.post('/upload', json={})
print(resp.status_code, resp.json())
