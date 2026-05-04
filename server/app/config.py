from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://attendance:attendance_secret@postgres:5432/face_attendance"
    jwt_secret: str = "aiot-face-attendance-jwt-secret-2025"
    jwt_algorithm: str = "HS256"
    distance_threshold: float = 0.5
    cooldown_seconds: int = 5

    class Config:
        env_file = ".env"


settings = Settings()
