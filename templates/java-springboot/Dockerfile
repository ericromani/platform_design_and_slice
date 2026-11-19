# Platform Java preset image: layered Spring Boot jar on a JRE, non-root.
FROM docker.io/library/maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml .
RUN mvn -B -q dependency:go-offline
COPY src ./src
RUN mvn -B -q package -DskipTests

FROM docker.io/library/eclipse-temurin:21-jre
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
COPY --from=build /src/target/app.jar /app/app.jar
USER 10001
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "/app/app.jar"]
