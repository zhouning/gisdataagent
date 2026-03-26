from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import dwg_parser, model_parser, converter

app = FastAPI(
    title="CAD/3D Parser Service",
    version="1.0.0",
    description="Parse DXF/DWG, OBJ/FBX files and convert to GIS formats",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dwg_parser.router, prefix="/api/v1/parse", tags=["DWG/DXF Parser"])
app.include_router(model_parser.router, prefix="/api/v1/parse", tags=["3D Model Parser"])
app.include_router(converter.router, prefix="/api/v1/convert", tags=["Format Converter"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "cad-parser"}
