"""
auditor/scanner.py — Árbol jerárquico del repo para auditoría
"""

from pathlib import Path

# Carpetas y archivos que no aportan nada al análisis
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".aider.tags.cache.v4",
    "node_modules", ".mypy_cache", ".pytest_cache", "dist", "build",
    "drive_cache", "excluir",
}

SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico", ".webp",
    ".mp3", ".mp4", ".zip", ".tar", ".gz", ".rar",
    ".db", ".sqlite", ".sqlite3",
    ".lock", ".log",
}

# Archivos de texto que sí se analizan (vacío = todos los que no estén en SKIP)
INCLUDE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
    ".md", ".txt", ".sh", ".bat", ".ps1",
    ".html", ".css",
}


# El contenido de lo que se escanea acaba en un LLM cloud (Groq/NVIDIA): nunca
# credenciales ni datos personales. Se compara contra el nombre en minusculas.
DENY_NAME_PARTS = (
    "token", "credential", "secret", "password", "passwd", "apikey", "api_key",
    "id_rsa", "id_ed25519", "historico", "entrevista",
)
DENY_SUFFIXES = {".env", ".pem", ".key", ".pfx", ".p12", ".crt"}


def _is_sensitive(p: Path) -> bool:
    name = p.name.lower()
    return (
        name == ".env"
        or name.startswith(".env.")
        or p.suffix.lower() in DENY_SUFFIXES
        or any(part in name for part in DENY_NAME_PARTS)
    )


def scan(repo_path: str) -> list[dict]:
    """
    Recorre el repo y devuelve lista de archivos a auditar.
    Cada item: {"path": str, "rel": str, "size": int, "depth": int}
    Ordenados: primero archivos raíz, luego por carpeta, sin profundidad excesiva.
    """
    root = Path(repo_path).resolve()
    files = []

    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue

        # Saltar si alguna parte del path está en SKIP_DIRS
        parts = p.relative_to(root).parts
        if any(part in SKIP_DIRS for part in parts):
            continue

        # Saltar extensiones excluidas
        if p.suffix.lower() in SKIP_EXTENSIONS:
            continue

        # Solo incluir extensiones conocidas
        if p.suffix.lower() not in INCLUDE_EXTENSIONS:
            continue

        if _is_sensitive(p) or any(part.lower().startswith(".garmin") for part in parts):
            continue

        # No seguir enlaces simbolicos que apunten fuera del repo
        try:
            p.resolve().relative_to(root)
        except ValueError:
            continue

        rel = p.relative_to(root)
        files.append({
            "path":  str(p),
            "rel":   str(rel),
            "size":  p.stat().st_size,
            "depth": len(rel.parts) - 1,  # 0 = raíz
        })

    return files


def tree(repo_path: str) -> str:
    """
    Devuelve el árbol del repo como string, igual que `tree` de terminal.
    Útil para incluir en el prompt de resumen ejecutivo.
    """
    root = Path(repo_path).resolve()
    lines = [str(root)]

    def _walk(path: Path, prefix: str = ""):
        entries = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name))
        for i, entry in enumerate(entries):
            if entry.name in SKIP_DIRS:
                continue
            connector = "└── " if i == len(entries) - 1 else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                extension = "    " if i == len(entries) - 1 else "│   "
                _walk(entry, prefix + extension)

    _walk(root)
    return "\n".join(lines)


def group_by_folder(files: list[dict]) -> dict[str, list[dict]]:
    """
    Agrupa los archivos por carpeta (str).
    "" = raíz del repo.
    """
    groups: dict[str, list[dict]] = {}
    for f in files:
        folder = str(Path(f["rel"]).parent)
        if folder == ".":
            folder = ""
        groups.setdefault(folder, []).append(f)
    return groups


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    files = scan(path)
    print(f"{len(files)} archivos a auditar\n")
    print(tree(path))
