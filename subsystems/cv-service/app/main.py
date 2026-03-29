from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import cad_detection, raster_quality, model_validation


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: load models
    print("[cv-service] Starting up, loading models...")
    yield
    # Shutdown: release resources
    print("[cv-service] Shutting down, releasing resources...")


app = FastAPI(
    title="CV Visual Detection Service",
    version="1.0.0",
    description="YOLO-based visual detection for CAD, raster, and 3D models",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cad_detection.router, prefix="/api/v1/detect", tags=["CAD Detection"])
app.include_router(raster_quality.router, prefix="/api/v1/detect", tags=["Raster Quality"])
app.include_router(model_validation.router, prefix="/api/v1/detect", tags=["Model Validation"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "cv-service"}
