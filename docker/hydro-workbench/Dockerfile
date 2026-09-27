ARG HYDRO_RUNTIME_IMAGE=abu-dhabi-hydrodynamics:runtime-v1
FROM ${HYDRO_RUNTIME_IMAGE}

USER root
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir \
    --index-url "${PIP_INDEX_URL}" \
    starlette==1.3.1 uvicorn==0.38.0 boto3==1.40.35 psycopg2-binary==2.9.10

# The worker imports the canonical SWMM output parser from the Abu Dhabi flood
# adapter.  That adapter is a package (its __init__ performs the public
# exports), so copying only hydro_workbench makes the API appear healthy but
# causes Kubernetes worker Jobs to fail at import time.  Ship the complete
# data_agent package into the runtime image; this keeps the API and worker on
# the same contract and avoids a second, drifting parser implementation.
COPY --chown=10001:10001 data_agent/ /app/data_agent/

USER 10001:10001
WORKDIR /app
EXPOSE 8080
ENTRYPOINT []
CMD ["python", "-m", "uvicorn", "data_agent.hydro_workbench.app:app", "--host", "0.0.0.0", "--port", "8080"]
