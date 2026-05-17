# Frontend/Backend Boundary

This project uses FastAPI response models as the backend-to-frontend contract and a single frontend API client as the call boundary.

## Rules

- Backend JSON endpoints under `backend/app/api/routes.py` must declare `response_model`.
- File or streaming endpoints may omit `response_model` only when they are listed in `scripts/project-governance-check.ps1`.
- Frontend code outside `frontend/src/shared/api/client.ts` must not call `fetch`, `axios`, `XMLHttpRequest`, or hard-code `/api/` paths.
- Frontend types in `frontend/src/shared/types/api.ts` must be updated in the same change as backend contract changes.
- Removed backend routes should stay deleted. Keep only tests that assert old routes do not return.

## Change Checklist

1. Update backend contracts in `backend/app/api/contracts.py` and route `response_model`.
2. Update `frontend/src/shared/types/api.ts`.
3. Update API wrapper functions in `frontend/src/shared/api/client.ts`.
4. Update UI callers to consume normalized client results.
5. Run:

```powershell
python -m pytest backend\tests
cd frontend
npm test
npm run build
cd ..
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\project-governance-check.ps1
```
