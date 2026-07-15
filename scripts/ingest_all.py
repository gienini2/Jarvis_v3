"""
Ingesta conversaciones historicas en la tabla memories via RAG.

Fuentes:
  - jarvis_v2/claude_export/conversations.json
  - jarvis_v2/gemini_export/gemini_full*.json
  - jarvis_v2/chatgpt_export/conversations*.json

Cada entrada = un par user+assistant embebido como una sola memoria.
Idempotente por archivo (metadata.file). --force para reingestar.
"""
import sys
import os
import json
import glob
import re
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.rag import store_memory
from core.db import get_connection

EXPORT_BASE = r"C:\Users\Usuario\jarvis_v2"

# ── helpers ──────────────────────────────────────────────────────────────────

_GEMINI_PREFIX = re.compile(
    r"^(Has dicho|Gemini ha dicho|Ver razonamiento\s*\nGemini ha dicho)\s*\n+",
    re.IGNORECASE,
)


def clean_gemini(text: str) -> str:
    return _GEMINI_PREFIX.sub("", text).strip()


def extract_text(msg: dict) -> str:
    """Extrae texto de un mensaje Claude (text o content[].text)."""
    t = msg.get("text") or ""
    if not t:
        for block in msg.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                t += block.get("text", "")
    return t.strip()


def already_ingested_file(source: str, fname: str) -> bool:
    """True si ya hay memorias de este source+file concreto."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM memories WHERE source = %s AND metadata->>'file' = %s LIMIT 1",
        (source, fname)
    )
    found = cur.fetchone() is not None
    cur.close()
    conn.close()
    return found


def already_ingested(source: str) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM memories WHERE source = %s", (source,))
    n = cur.fetchone()[0]
    cur.close()
    conn.close()
    return n


def store(content: str, source: str, metadata: dict) -> bool:
    if len(content) < 30:
        return False
    if len(content) > 3000:
        content = content[:3000]
    mid = store_memory(content, source=source, metadata=metadata)
    return mid is not None


# ── Claude ───────────────────────────────────────────────────────────────────

def ingest_claude(force: bool = False) -> int:
    path = os.path.join(EXPORT_BASE, "claude_export", "conversations.json")
    if not os.path.exists(path):
        print(f"[claude] No encontrado: {path}")
        return 0

    existing = already_ingested("claude")
    if existing and not force:
        print(f"[claude] Ya ingestado ({existing} memorias). Usa --force para reingestar.")
        return 0

    print(f"[claude] Leyendo {path}...")
    with open(path, encoding="utf-8") as f:
        conversations = json.load(f)

    total = 0
    for conv in conversations:
        name = conv.get("name") or "sin título"
        conv_id = conv.get("uuid", "")
        messages = conv.get("chat_messages") or []

        i = 0
        while i < len(messages):
            m = messages[i]
            sender = m.get("sender", "")
            if sender == "human":
                user_text = extract_text(m)
                assistant_text = ""
                if i + 1 < len(messages) and messages[i + 1].get("sender") == "assistant":
                    assistant_text = extract_text(messages[i + 1])
                    i += 2
                else:
                    i += 1
                if not user_text:
                    continue
                content = f"user: {user_text}"
                if assistant_text:
                    content += f"\nassistant: {assistant_text}"
                ok = store(content, source="claude", metadata={"conv": name, "conv_id": conv_id})
                if ok:
                    total += 1
                    if total % 20 == 0:
                        print(f"  [claude] {total} memorias guardadas...")
            else:
                i += 1

    print(f"[claude] Completado: {total} memorias ingestadas.")
    return total


# ── Gemini ────────────────────────────────────────────────────────────────────

def ingest_gemini(force: bool = False) -> int:
    pattern = os.path.join(EXPORT_BASE, "gemini_export", "gemini_full*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"[gemini] No encontrados archivos en {pattern}")
        return 0

    existing = already_ingested("gemini")
    if existing and not force:
        print(f"[gemini] Ya ingestado ({existing} memorias). Usa --force para reingestar.")
        return 0

    total = 0
    for path in files:
        fname = os.path.basename(path)
        print(f"[gemini] Leyendo {fname}...")
        with open(path, encoding="utf-8") as f:
            messages = json.load(f)

        i = 0
        while i < len(messages):
            m = messages[i]
            if m.get("role") == "user":
                user_text = clean_gemini(m.get("text") or "")
                assistant_text = ""
                if i + 1 < len(messages) and messages[i + 1].get("role") == "assistant":
                    assistant_text = clean_gemini(messages[i + 1].get("text") or "")
                    i += 2
                else:
                    i += 1
                if not user_text:
                    continue
                content = f"user: {user_text}"
                if assistant_text:
                    content += f"\nassistant: {assistant_text}"
                ok = store(content, source="gemini", metadata={"file": fname})
                if ok:
                    total += 1
                    if total % 50 == 0:
                        print(f"  [gemini] {total} memorias guardadas...")
            else:
                i += 1

        print(f"  [gemini] {fname}: listo.")

    print(f"[gemini] Completado: {total} memorias ingestadas.")
    return total


# ── ChatGPT ───────────────────────────────────────────────────────────────────

def extract_chatgpt_text(message: dict) -> str:
    if not message:
        return ""
    content = message.get("content") or {}
    if content.get("content_type") == "text":
        parts = content.get("parts") or []
        return " ".join(p for p in parts if isinstance(p, str)).strip()
    return ""


def ingest_chatgpt(force: bool = False) -> int:
    pattern = os.path.join(EXPORT_BASE, "chatgpt_export", "conversations*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"[chatgpt] No encontrados archivos en {pattern}")
        return 0

    total = 0
    for path in files:
        fname = os.path.basename(path)

        # Idempotencia por archivo
        if not force and already_ingested_file("chatgpt", fname):
            print(f"[chatgpt] {fname}: ya ingestado, saltando.")
            continue

        print(f"[chatgpt] Leyendo {fname}...")
        with open(path, encoding="utf-8") as f:
            conversations = json.load(f)

        for conv in conversations:
            title = conv.get("title") or "sin título"
            conv_id = conv.get("id", "")
            mapping = conv.get("mapping") or {}

            nodes = {}
            for node_id, node in mapping.items():
                msg = node.get("message")
                if not msg:
                    continue
                role = msg.get("author", {}).get("role", "")
                if role not in ("user", "assistant"):
                    continue
                nodes[node_id] = node

            ordered = sorted(
                nodes.values(),
                key=lambda n: (n.get("message") or {}).get("create_time") or 0
            )

            i = 0
            while i < len(ordered):
                msg = ordered[i].get("message") or {}
                role = msg.get("author", {}).get("role", "")

                if role == "user":
                    user_text = extract_chatgpt_text(msg)
                    assistant_text = ""
                    if i + 1 < len(ordered):
                        next_msg = ordered[i + 1].get("message") or {}
                        if next_msg.get("author", {}).get("role") == "assistant":
                            assistant_text = extract_chatgpt_text(next_msg)
                            i += 2
                        else:
                            i += 1
                    else:
                        i += 1

                    if not user_text:
                        continue

                    content = f"user: {user_text}"
                    if assistant_text:
                        content += f"\nassistant: {assistant_text}"

                    ok = store(content, source="chatgpt", metadata={"conv": title, "conv_id": conv_id, "file": fname})
                    if ok:
                        total += 1
                        if total % 50 == 0:
                            print(f"  [chatgpt] {total} memorias guardadas...")
                else:
                    i += 1

        print(f"  [chatgpt] {fname}: listo.")

    print(f"[chatgpt] Completado: {total} memorias ingestadas.")
    return total


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ingesta conversaciones históricas en memories")
    parser.add_argument("--source", choices=["claude", "gemini", "chatgpt"], help="Ingestar solo esta fuente")
    parser.add_argument("--force", action="store_true", help="Reingestar aunque ya existan entradas")
    args = parser.parse_args()

    total = 0
    if args.source in (None, "claude"):
        total += ingest_claude(force=args.force)
    if args.source in (None, "gemini"):
        total += ingest_gemini(force=args.force)
    if args.source in (None, "chatgpt"):
        total += ingest_chatgpt(force=args.force)

    print(f"\nTotal memorias ingestadas: {total}")


if __name__ == "__main__":
    main()
