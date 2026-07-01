from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    OLLAMA_URL: str = "http://127.0.0.1:11434/api/generate"
    MODEL: str = "qwen2.5:7b"
    TIMEOUT: int = 120

    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_DB: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str

    # Relay en figaro-server
    RELAY_URL: str = "http://100.78.43.76:10004"

    # Google
    GOOGLE_CREDENTIALS_FILE: str = "config/google_credentials.json"
    GOOGLE_TOKEN_FILE: str = "config/google_token.json"

    class Config:
        env_file = ".env"


settings = Settings()