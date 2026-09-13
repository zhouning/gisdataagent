from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"


def test_docker_image_copies_uwm_public_proxy_data_for_traditional_livability():
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY data/uwm_public_proxy/ /app/data/uwm_public_proxy/" in text
