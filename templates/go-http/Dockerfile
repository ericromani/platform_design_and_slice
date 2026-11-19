# Platform Go preset image: static binary on distroless, non-root.
FROM docker.io/library/golang:1.25 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/server ./cmd/server

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/server /server
USER 10001
EXPOSE 8080
ENTRYPOINT ["/server"]
