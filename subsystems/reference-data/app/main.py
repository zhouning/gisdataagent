from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import control_points, datum_info, precision_compare

app = FastAPI(
    title="Reference Data Service",
    version="1.0.0",
    description="Control points, datum info, and coordinate precision comparison",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(control_points.router, prefix="/api/v1", tags=["Control Points"])
app.include_router(datum_info.router, prefix="/api/v1", tags=["Datum Info"])
app.include_router(precision_compare.router, prefix="/api/v1", tags=["Precision Compare"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "reference-data"}
