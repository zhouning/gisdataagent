ARG HYDRO_RUNTIME_IMAGE=abu-dhabi-hydrodynamics:runtime-v1
FROM ${HYDRO_RUNTIME_IMAGE}

USER root
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN python -m pip install --no-cache-dir \
    --index-url "${PIP_INDEX_URL}" \
    starlette==1.3.1 uvicorn==0.38.0

COPY --chown=10001:10001 data_agent/hydro_workbench/ /app/data_agent/hydro_workbench/

USER 10001:10001
WORKDIR /app
EXPOSE 8080
ENTRYPOINT []
CMD ["python", "-m", "uvicorn", "data_agent.hydro_workbench.app:app", "--host", "0.0.0.0", "--port", "8080"]
