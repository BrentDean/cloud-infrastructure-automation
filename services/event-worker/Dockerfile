FROM golang:1.26-alpine AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/event-worker .

FROM scratch
COPY --from=build /out/event-worker /event-worker
USER 10001:10001
ENTRYPOINT ["/event-worker"]
