PHP auth backend

1) Initialize DB (one-time):

   php server/init_db.php

2) Run local PHP server from project root:

   php -S localhost:8000

This will serve `server/api/*.php` under `http://localhost:8000/server/api`.

Frontend expects API at `http://localhost:8000/server/api`.

OAuth has been removed from this project. Use the provided email/password endpoints:
- `server/api/register.php` — register (POST JSON {email,password})
- `server/api/login.php` — login (POST JSON {email,password}) returns `{token}`
- `server/api/user.php` — protected endpoint, requires `Authorization: Bearer <token>`
