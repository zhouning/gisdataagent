ARG BASE_IMAGE=192.168.106.71/datacenter/runtime-notebook-pyspark:v3.0.0-arrch64
FROM ${BASE_IMAGE}

USER root

ARG SPARK_HOME=/usr/local/spark
ARG JAR_SOURCE=.tmp/ivy2/jars

COPY ${JAR_SOURCE}/org.apache.hadoop_hadoop-aws-3.3.4.jar ${SPARK_HOME}/jars/hadoop-aws-3.3.4.jar
COPY ${JAR_SOURCE}/com.amazonaws_aws-java-sdk-bundle-1.12.262.jar ${SPARK_HOME}/jars/aws-java-sdk-bundle-1.12.262.jar
COPY ${JAR_SOURCE}/org.wildfly.openssl_wildfly-openssl-1.0.7.Final.jar ${SPARK_HOME}/jars/wildfly-openssl-1.0.7.Final.jar
COPY ${JAR_SOURCE}/org.apache.iceberg_iceberg-spark-runtime-3.5_2.12-1.6.1.jar ${SPARK_HOME}/jars/iceberg-spark-runtime-3.5_2.12-1.6.1.jar
COPY ${JAR_SOURCE}/org.apache.sedona_sedona-spark-shaded-3.5_2.12-1.9.0.jar ${SPARK_HOME}/jars/sedona-spark-shaded-3.5_2.12-1.9.0.jar
COPY ${JAR_SOURCE}/org.datasyslab_geotools-wrapper-1.9.0-33.5.jar ${SPARK_HOME}/jars/geotools-wrapper-1.9.0-33.5.jar

ENV MMFE_SPARK_RUNTIME_MODE=baked-jars
ENV MMFE_SPARK_RUNTIME_JARS="hadoop-aws-3.3.4,aws-java-sdk-bundle-1.12.262,wildfly-openssl-1.0.7.Final,iceberg-spark-runtime-3.5_2.12-1.6.1,sedona-spark-shaded-3.5_2.12-1.9.0,geotools-wrapper-1.9.0-33.5"

USER 1000
