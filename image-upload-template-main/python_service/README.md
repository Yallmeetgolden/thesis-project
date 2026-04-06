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
- Optional professional mode uses PyTorch model blending.

Deep-learning model (optional but recommended):
- Place TorchScript model at `python_service/models/blur_classifier.pt`
- Or set env var `BLUR_MODEL_PATH` to your model file.
- Expected output: blurry/sharp logits or probability tensor (service parses common shapes).

Fallback behavior:
- If model is missing/unloadable, service automatically falls back to classical CV scoring.
- Response contains calibration fields `modelUsed`, `modelStatus`, and `deepLearningAppliedCount`.

Training your blur model (recommended)

Expected dataset structure (class names must be exactly blurry/sharp):

Option A (separate train/val):

dataset/
   train/
      blurry/
      sharp/
   val/
      blurry/
      sharp/

Option B (single folder, used for both train and val quickly):

dataset/
   blurry/
   sharp/

Train + export TorchScript model:

python python_service/train_blur_model.py --data-dir "C:\path\to\dataset"

Outputs:
- `python_service/models/blur_classifier.pt` (used by analyzer)
- `python_service/models/blur_classifier_state_dict.pth`
- `python_service/models/training_metrics.json`

After training:
- Restart service: `python python_service/app.py`
- Analyzer should report `modelUsed: hybrid` when model is active.
