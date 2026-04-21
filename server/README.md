PHP auth backend

1) Initialize DB (one-time):

   php server/init_db.php

2) Run local PHP server from project root:

   php -d upload_max_filesize=1024M -d post_max_size=1024M -d max_execution_time=300 -d memory_limit=1024M -S 127.0.0.1:8000 router.php

This will serve `server/api/*.php` under `http://localhost:8000/server/api`.

Frontend expects API at `http://localhost:8000/server/api`.

3) Run Python blur analysis microservice (required for `/server/api/analyze_blur.php`):

   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r python_service/requirements.txt
   python python_service/app.py

Python service runs on `http://127.0.0.1:8001` by default.
For professional-level accuracy, add TorchScript model at `python_service/models/blur_classifier.pt`.

OAuth has been removed from this project. Use the provided email/password endpoints:
- `server/api/register.php` — register (POST JSON {email,password})
- `server/api/login.php` — login (POST JSON {email,password}) returns `{token}`
- `server/api/user.php` — protected endpoint, requires `Authorization: Bearer <token>`
