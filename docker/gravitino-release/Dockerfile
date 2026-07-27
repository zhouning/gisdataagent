FROM eclipse-temurin:17.0.16_8-jdk-jammy

ARG GRAVITINO_BINARY_SHA256=bed7e51701628f651bc53a03307eed16ae04c15b083ee9be40af7fb776b625cd
ARG POSTGRESQL_JDBC_SHA256=90c39c97ac309b5767882f9beef913244da029204af2d2982c2b45bcfcb42624

LABEL org.opencontainers.image.title="Apache Gravitino local release build" \
      org.opencontainers.image.version="1.3.0" \
      org.opencontainers.image.revision="40fdf6ab96ac87b47e6d3e14e7c4dc0d815e68f0" \
      org.opencontainers.image.source="https://github.com/apache/gravitino" \
      gda.openai.com/image-provenance="local_release_build"

COPY gravitino-1.3.0-bin.tar.gz /tmp/gravitino-1.3.0-bin.tar.gz
COPY postgresql-42.7.0.jar /tmp/postgresql-42.7.0.jar

RUN echo "${GRAVITINO_BINARY_SHA256}  /tmp/gravitino-1.3.0-bin.tar.gz" | sha256sum -c - \
    && echo "${POSTGRESQL_JDBC_SHA256}  /tmp/postgresql-42.7.0.jar" | sha256sum -c - \
    && mkdir -p /opt/gravitino \
    && tar -xzf /tmp/gravitino-1.3.0-bin.tar.gz -C /opt/gravitino --strip-components=1 \
    && install -m 0644 /tmp/postgresql-42.7.0.jar /opt/gravitino/libs/postgresql-42.7.0.jar \
    && chmod +x /opt/gravitino/bin/gravitino.sh \
    && useradd -u 1000 -g 0 -M -s /usr/sbin/nologin gravitino \
    && chown -R 1000:0 /opt/gravitino \
    && rm -f /tmp/gravitino-1.3.0-bin.tar.gz /tmp/postgresql-42.7.0.jar

WORKDIR /opt/gravitino
USER 1000:0
EXPOSE 8090
CMD ["/opt/gravitino/bin/gravitino.sh", "run"]
