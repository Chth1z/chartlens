from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "app"


def test_single_machine_layer_packages_exist() -> None:
    expected_packages = [
        "domain",
        "application",
        "application/ports",
        "infrastructure",
        "interfaces/http",
        "composition",
    ]

    missing = [package for package in expected_packages if not (ROOT / package / "__init__.py").exists()]

    assert missing == []


def test_legacy_compatibility_modules_are_removed() -> None:
    legacy_paths = [
        "services",
        "api",
        "schemas",
        "models.py",
        "core/database.py",
    ]

    existing = [path for path in legacy_paths if (ROOT / path).exists()]

    assert existing == []


def test_core_layers_do_not_import_framework_or_database_edges() -> None:
    forbidden_by_layer = {
        "domain": {"fastapi", "sqlalchemy", "app.interfaces", "app.infrastructure", "app.composition"},
        "application": {"fastapi", "sqlalchemy", "app.interfaces", "app.infrastructure", "app.core", "app.composition"},
    }
    violations: list[str] = []

    for layer, forbidden_imports in forbidden_by_layer.items():
        for path in (ROOT / layer).rglob("*.py"):
            module = path.relative_to(ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                imported_names: list[str] = []
                if isinstance(node, ast.Import):
                    imported_names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_names = [node.module]
                for name in imported_names:
                    if any(name == forbidden or name.startswith(f"{forbidden}.") for forbidden in forbidden_imports):
                        violations.append(f"{module}: {name}")

    assert violations == []


def test_no_code_imports_legacy_modules() -> None:
    forbidden_imports = {
        "app.services",
        "app.api",
        "app.schemas",
        "app.models",
        "app.core.database",
    }
    violations = _import_violations(ROOT, forbidden_imports)

    assert violations == []


def test_http_routes_do_not_import_database_or_orm_edges() -> None:
    route_paths = [path for path in (ROOT / "interfaces" / "http").rglob("*.py") if path.name != "auth_service.py"]
    forbidden_imports = {"sqlalchemy", "app.infrastructure.db", "app.infrastructure.pipeline"}
    violations = _import_violations_for_paths(route_paths, forbidden_imports)

    assert violations == []


def _import_violations(root: Path, forbidden_imports: set[str]) -> list[str]:
    return _import_violations_for_paths(root.rglob("*.py"), forbidden_imports)


def _import_violations_for_paths(paths, forbidden_imports: set[str]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        module = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported_names: list[str] = []
            if isinstance(node, ast.Import):
                imported_names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names = [node.module]
            for name in imported_names:
                if any(name == forbidden or name.startswith(f"{forbidden}.") for forbidden in forbidden_imports):
                    violations.append(f"{module}: {name}")
    return violations
