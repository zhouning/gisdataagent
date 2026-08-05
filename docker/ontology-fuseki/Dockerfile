FROM eclipse-temurin:17-jre-jammy

ARG JENA_VERSION=5.5.0
ARG ONTOLOGY_VERSION=2.0.1
ARG JENA_SHA512=f9ae68a748e642c6a8175ee25afdfa37ce057ed37e7caf279a8a46ad93284bea808cf14d96bf30b6e4e6a4ddaf30cf5ee9d441f48a9a3d3c9e647a9b71645e0c
ARG JENA_FUSEKI_SHA512=bfbf59eac731b71bcf8e148f2abeda9b4adca215639eef3bba61243b308572b23a9a70a43c1483247f9894bfb23d69b59e0e64e1da47cb3cfc592aa979084d5c
ARG ONTOLOGY_TTL_SHA256=0b36f4aff47cdd0045190d3b8a9610069c3cf729f34ea132d8f551f139e4c4f9

LABEL org.opencontainers.image.title="GIS Data Agent Natural Resource Ontology Store" \
      org.opencontainers.image.version="${JENA_VERSION}-nr-${ONTOLOGY_VERSION}" \
      org.opencontainers.image.description="Read-only Apache Jena Fuseki/TDB2 projection for natural-resource ontology ${ONTOLOGY_VERSION}"

ADD https://archive.apache.org/dist/jena/binaries/apache-jena-${JENA_VERSION}.tar.gz /tmp/jena.tar.gz
ADD https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-${JENA_VERSION}.tar.gz /tmp/fuseki.tar.gz
RUN echo "${JENA_SHA512}  /tmp/jena.tar.gz" | sha512sum -c - \
    && echo "${JENA_FUSEKI_SHA512}  /tmp/fuseki.tar.gz" | sha512sum -c - \
    && mkdir -p /opt \
    && tar -xzf /tmp/jena.tar.gz -C /opt \
    && tar -xzf /tmp/fuseki.tar.gz -C /opt \
    && mv "/opt/apache-jena-${JENA_VERSION}" /opt/jena \
    && mv "/opt/apache-jena-fuseki-${JENA_VERSION}" /opt/fuseki \
    && rm /tmp/jena.tar.gz /tmp/fuseki.tar.gz \
    && useradd --system --uid 10001 --home /fuseki --shell /usr/sbin/nologin fuseki \
    && mkdir -p /fuseki/databases \
    && chown -R fuseki:fuseki /fuseki

COPY docker/ontology-fuseki/config.ttl /opt/fuseki/config.ttl
COPY docker/ontology-fuseki/entrypoint.sh /usr/local/bin/ontology-fuseki-entrypoint
COPY data_agent/ontology/packages/natural_resource_one_map/${ONTOLOGY_VERSION}/ontology.ttl.gz /opt/fuseki/bootstrap/ontology.ttl.gz

RUN echo "${ONTOLOGY_TTL_SHA256}  /opt/fuseki/bootstrap/ontology.ttl.gz" | sha256sum -c - \
    && chmod 0555 /usr/local/bin/ontology-fuseki-entrypoint \
    && chown -R fuseki:fuseki /opt/fuseki /opt/jena

ENV FUSEKI_HOME=/opt/fuseki
ENV JENA_HOME=/opt/jena
ENV JVM_ARGS="-Xms512m -Xmx2g -XX:+UseG1GC"

USER fuseki
WORKDIR /opt/fuseki
EXPOSE 3030
VOLUME ["/fuseki"]

ENTRYPOINT ["/usr/local/bin/ontology-fuseki-entrypoint"]
