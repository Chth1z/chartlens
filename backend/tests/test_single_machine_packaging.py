from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_server_dependencies_do_not_include_removed_distributed_runtime() -> None:
    requirements = (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")

    assert "redis" not in requirements.lower()
    assert "rq" not in requirements.lower()
    assert "psycopg" not in requirements.lower()


def test_removed_distributed_deployment_files_are_absent() -> None:
    removed_files = [
        "docker-compose.yml",
        "backend/Dockerfile",
        "backend/app/worker.py",
        "frontend/Dockerfile",
        "frontend/nginx.conf",
    ]

    remaining = [path for path in removed_files if (ROOT / path).exists()]

    assert remaining == []
