from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MODEL_DIR: str = "/app/models"
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB
    YOLO_MODEL: str = "yolov8n.pt"
    CONFIDENCE_THRESHOLD: float = 0.5
    IOU_THRESHOLD: float = 0.45
    DEVICE: str = "cuda"  # or "cpu"

    class Config:
        env_file = ".env"

settings = Settings()
