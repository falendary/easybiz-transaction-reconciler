## Key constraints (intentional MVP trade-offs)

| Constraint | Detail |
|---|---|
| No auth on API | Endpoints are open — localhost only |
| Synchronous Claude calls | Long extractions block the HTTP thread |
| Local file storage | Files written to `MEDIA_ROOT`; lost on container restart |


---

## Before going to production

Priority order — tackle these before any real users:

**Must have**
- [ ] Gunicorn + Nginx (replace `runserver`)
- [ ] Docker + docker-compose
- [ ] PostgreSQL (replace SQLite)
- [ ] Django security settings (`DEBUG=False`, HSTS, secure cookies)
- [ ] API authentication — JWT or SSO (see `STEPS_TO_PRODUCTION.md`)
- [ ] Object storage for uploads (S3 or equivalent)
- [ ] Sentry error tracking
- [ ] Health check endpoints
- [ ] GitHub Actions CI (lint + test + coverage gate)
- [ ] PostgreSQL automated backups

**Should have**
- [ ] Celery + Redis — move Claude calls off the request thread
- [ ] API rate limiting (Claude calls cost money per request)
- [ ] Structured logging
- [ ] CORS + CSRF configuration for a decoupled frontend
