"""
core/intent_ml.py
Clasificador ML de intents usando TF-IDF + SVM.
Aprende de training_data.json y de la tabla intents (conversaciones reales).
Se reentrena automáticamente cada AUTO_RETRAIN_EVERY mensajes nuevos.
"""
import json
import os
import pickle
import logging
import threading
from pathlib import Path

log = logging.getLogger("jarvis.intent_ml")

MODEL_PATH    = Path("config/intent_model.pkl")
TRAINING_PATH = Path("config/training_data.json")
AUTO_RETRAIN_EVERY = 50

# Lock estrecho: solo protege las asignaciones a globals, no las operaciones lentas.
_lock = threading.Lock()
_classifier = None
_vectorizer = None
_messages_since_retrain = 0


def _load_training_data() -> tuple[list[str], list[str]]:
    texts, labels = [], []

    if TRAINING_PATH.exists():
        with open(TRAINING_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for intent, examples in data.items():
            for ex in examples:
                texts.append(ex)
                labels.append(intent)

    try:
        from core.db import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT message, intent_type FROM intents
            WHERE intent_type != 'general'
            AND message IS NOT NULL
            AND LENGTH(message) > 5
            ORDER BY id DESC
            LIMIT 2000
        """)
        for msg, intent_type in cur.fetchall():
            texts.append(msg)
            labels.append(intent_type)
        cur.close()
        conn.close()
    except Exception as e:
        log.warning(f"No se pudieron cargar intents de BD: {e}")

    return texts, labels


def train() -> bool:
    """Entrena el modelo fuera del lock y hace swap atómico al terminar."""
    global _classifier, _vectorizer

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.svm import LinearSVC

    texts, labels = _load_training_data()
    if len(texts) < 10:
        log.warning("Pocos ejemplos para entrenar — usando solo regex")
        return False

    new_vec = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 4),
        min_df=1,
        sublinear_tf=True,
    )
    new_clf = LinearSVC(max_iter=2000, C=1.0)
    X = new_vec.fit_transform(texts)
    new_clf.fit(X, labels)

    # Swap atómico: el lock se sostiene el mínimo tiempo posible
    with _lock:
        _classifier = new_clf
        _vectorizer = new_vec

    MODEL_PATH.parent.mkdir(exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump((new_vec, new_clf), f)

    log.info(f"Modelo entrenado: {len(texts)} ejemplos, {len(set(labels))} intents")
    return True


def load() -> bool:
    """Carga el modelo desde disco o entrena si no existe."""
    global _classifier, _vectorizer

    if MODEL_PATH.exists():
        with open(MODEL_PATH, "rb") as f:
            new_vec, new_clf = pickle.load(f)
        with _lock:
            _classifier = new_clf
            _vectorizer = new_vec
        log.info("Modelo ML cargado desde disco")
        return True
    return train()


def predict(message: str) -> tuple[str, float]:
    """
    Predice el intent. Thread-safe.
    Devuelve (intent_type, confidence).
    """
    global _messages_since_retrain

    with _lock:
        clf, vec = _classifier, _vectorizer

    if clf is None:
        if not load():
            return "general", 0.0
        with _lock:
            clf, vec = _classifier, _vectorizer

    X = vec.transform([message])
    intent = clf.predict(X)[0]

    try:
        distances = clf.decision_function(X)[0]
        if hasattr(distances, "__len__"):
            confidence = float(max(distances)) / (float(max(distances)) + 1)
        else:
            confidence = min(abs(float(distances)) / 2, 1.0)
    except Exception:
        confidence = 0.7

    # Incremento atómico del contador; reentrenamiento en thread separado
    with _lock:
        _messages_since_retrain += 1
        should_retrain = _messages_since_retrain >= AUTO_RETRAIN_EVERY
        if should_retrain:
            _messages_since_retrain = 0

    if should_retrain:
        log.info("Auto-reentrenando modelo ML en background...")
        threading.Thread(target=train, daemon=True).start()

    return intent, confidence


def add_example(text: str, intent_type: str):
    """Añade un ejemplo al training_data.json y reentrena en background."""
    if not TRAINING_PATH.exists():
        data = {}
    else:
        with open(TRAINING_PATH, encoding="utf-8") as f:
            data = json.load(f)

    if intent_type not in data:
        data[intent_type] = []
    if text not in data[intent_type]:
        data[intent_type].append(text)
        with open(TRAINING_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log.info(f"Ejemplo añadido: '{text}' → {intent_type}")
        threading.Thread(target=train, daemon=True).start()
