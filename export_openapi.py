import json
from video_crawler.main import app

with open("openapi.json", "w", encoding="utf-8") as f:
    json.dump(app.openapi(), f, ensure_ascii=False, indent=2)

print("OpenAPI exported successfully")