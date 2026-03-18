Python blur analysis microservice (FastAPI + OpenCV)

Run from project root:

1) Create venv (optional but recommended)

   python -m venv .venv
   .venv\Scripts\Activate.ps1

2) Install dependencies

   pip install -r python_service/requirements.txt

3) Start service

   python python_service/app.py

Service URL (default expected by PHP):
- http://127.0.0.1:8001
- Health check: GET /health
- Analyze: POST /analyze-folder

Request body for /analyze-folder:
{
  "imagesDir": "absolute path to extracted images folder",
  "qualityMode": "very_blurry|slightly_blurry|acceptable|very_sharp"
}

Notes:
- Keep this service running while using blur analysis from the web app.
- PHP endpoint `server/api/analyze_blur.php` calls this service.
- RAW files `.nef`, `.dng`, and `.cr2` are supported via `rawpy`.
