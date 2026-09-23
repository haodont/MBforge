# Development workflow

Use Python 3.12 with `uv`, Node `>=24.14.1`, and npm.

```powershell
uv sync
npm --prefix frontend install
npm --prefix agent install
uv run pytest tests/ -q
uv run ruff check src tests
uv run ruff format src tests --check
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
```

Keep database and model runtime data outside the repository. Stop local
verification servers after use; the normal development ports are 18792 and
5173.
