from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    OLLAMA_URL: str = "http://127.0.0.1:11434/api/generate"
    OLLAMA_EMBED_URL: str = "http://127.0.0.1:11434/api/embed"
    MODEL: str = "qwen2.5:7b"
    TIMEOUT: int = 120
    NVIDIA_API_KEY: str = ""
    NVIDIA_MODEL_GENERAL: str = "meta/llama-3.3-70b-instruct"
    NVIDIA_MODEL_CODE: str = "deepseek-ai/deepseek-v4-pro"
    FIGARO_SSH_KEY: str = ""
    FIGARO_HOST: str = "100.78.43.76"

    GROQ_API_KEY: str = ""
    GROQ_MODEL_GENERAL: str = "openai/gpt-oss-120b"
    GROQ_MODEL_CODE: str = "qwen/qwen3.6-27b"

    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 2048
    OLLAMA_NUM_CTX: int = 4096   # 8192 dispara la latencia de Ollama en la RTX 5050 (~46s)

    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_DB: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str

    # Relay en figaro-server
    RELAY_URL: str = "http://100.78.43.76:10004"

    # Auth interna -- clave compartida entre Jarvis API y el relay de Figaro
    JARVIS_API_KEY: str = ""   # protege /chat, /chat/agent, /tasks, /aprende, /audit/*
    RELAY_API_KEY: str = ""    # protege /queue/pending y /queue/ack del relay en Figaro

    # Google
    GOOGLE_CREDENTIALS_FILE: str = "config/google_credentials.json"
    GOOGLE_TOKEN_FILE: str = "config/google_token.json"

    # Centro de Mando
    MANDO_API_URL: str = "https://figaro-server.taild7b9e6.ts.net/mando-api"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
