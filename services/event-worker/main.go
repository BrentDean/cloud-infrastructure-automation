package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/nats-io/nats.go"
)

const incidentCreatedSubject = "labops.incident.created"

type incidentCreated struct {
	EventID    string `json:"event_id"`
	IncidentID string `json:"incident_id"`
	EventType  string `json:"event_type"`
}

type deliveryStore interface {
	Record(context.Context, string, string, []byte) (bool, error)
}

type postgresStore struct {
	pool *pgxpool.Pool
}

func (store postgresStore) Record(
	ctx context.Context, subject, eventID string, payload []byte,
) (bool, error) {
	tag, err := store.pool.Exec(
		ctx,
		`INSERT INTO event_deliveries (subject, event_id, payload)
		 VALUES ($1, $2::uuid, $3::jsonb)
		 ON CONFLICT (event_id) DO NOTHING`,
		subject,
		eventID,
		string(payload),
	)
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() == 1, nil
}

func decodeIncidentCreated(payload []byte) (incidentCreated, error) {
	var event incidentCreated
	if len(payload) == 0 || len(payload) > 16*1024 {
		return event, errors.New("event payload must contain 1-16384 bytes")
	}

	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&event); err != nil {
		return event, fmt.Errorf("decode event: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return event, errors.New("event payload must contain one JSON object")
	}

	if event.EventType != "incident.created" {
		return event, errors.New("unexpected event_type")
	}
	if !validUUID(event.EventID) {
		return event, errors.New("event_id must be a UUID")
	}
	if !validUUID(event.IncidentID) {
		return event, errors.New("incident_id must be a UUID")
	}
	return event, nil
}

func recordMessage(
	ctx context.Context, store deliveryStore, subject string, payload []byte,
) (incidentCreated, bool, error) {
	var zero incidentCreated
	if subject != incidentCreatedSubject {
		return zero, false, errors.New("unexpected NATS subject")
	}
	event, err := decodeIncidentCreated(payload)
	if err != nil {
		return zero, false, err
	}
	inserted, err := store.Record(ctx, subject, event.EventID, payload)
	if err != nil {
		return zero, false, err
	}
	return event, inserted, nil
}

func validUUID(value string) bool {
	if len(value) != 36 {
		return false
	}
	for index, char := range value {
		switch index {
		case 8, 13, 18, 23:
			if char != '-' {
				return false
			}
		default:
			if !strings.ContainsRune("0123456789abcdefABCDEF", char) {
				return false
			}
		}
	}
	return true
}

func env(name, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}

func postgresDSN() (string, error) {
	password := os.Getenv("PGPASSWORD")
	if password == "" {
		return "", errors.New("PGPASSWORD is required")
	}
	user := env("PGUSER", "labuser")
	database := env("PGDATABASE", "labdb")
	host := env("PGHOST", "postgres")
	port := env("PGPORT", "5432")

	connectionURL := &url.URL{
		Scheme: "postgres",
		User:   url.UserPassword(user, password),
		Host:   net.JoinHostPort(host, port),
		Path:   database,
	}
	query := connectionURL.Query()
	query.Set("sslmode", env("PGSSLMODE", "disable"))
	connectionURL.RawQuery = query.Encode()
	return connectionURL.String(), nil
}

func connectPostgres(
	ctx context.Context, logger *slog.Logger, dsn string,
) (*pgxpool.Pool, error) {
	for {
		pool, err := pgxpool.New(ctx, dsn)
		if err == nil {
			pingCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
			err = pool.Ping(pingCtx)
			cancel()
			if err == nil {
				return pool, nil
			}
			pool.Close()
		}

		logger.Warn("PostgreSQL connection unavailable; retrying")
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(time.Second):
		}
	}
}

func connectNATS(
	ctx context.Context, logger *slog.Logger, serverURL string,
) (*nats.Conn, error) {
	for {
		connection, err := nats.Connect(
			serverURL,
			nats.Name("labops-event-worker"),
			nats.Timeout(2*time.Second),
			nats.MaxReconnects(-1),
			nats.ReconnectWait(time.Second),
			nats.DisconnectErrHandler(func(_ *nats.Conn, err error) {
				if err != nil {
					logger.Warn("NATS disconnected", "error", err.Error())
				}
			}),
			nats.ReconnectHandler(func(_ *nats.Conn) {
				logger.Info("NATS reconnected")
			}),
		)
		if err == nil {
			return connection, nil
		}

		logger.Warn("NATS connection unavailable; retrying")
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(time.Second):
		}
	}
}

func run(ctx context.Context, logger *slog.Logger) error {
	dsn, err := postgresDSN()
	if err != nil {
		return err
	}
	pool, err := connectPostgres(ctx, logger, dsn)
	if err != nil {
		return err
	}
	defer pool.Close()

	connection, err := connectNATS(ctx, logger, env("NATS_URL", "nats://nats:4222"))
	if err != nil {
		return err
	}
	defer connection.Close()

	store := postgresStore{pool: pool}
	subscription, err := connection.Subscribe(incidentCreatedSubject, func(message *nats.Msg) {
		messageCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()

		event, inserted, err := recordMessage(
			messageCtx, store, message.Subject, message.Data,
		)
		if err != nil {
			logger.Error(
				"event processing failed",
				"subject", message.Subject,
				"error", err.Error(),
			)
			return
		}
		logger.Info(
			"event delivery recorded",
			"subject", message.Subject,
			"event_id", event.EventID,
			"incident_id", event.IncidentID,
			"inserted", inserted,
		)
	})
	if err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}
	if err := connection.FlushTimeout(2 * time.Second); err != nil {
		return fmt.Errorf("establish subscription: %w", err)
	}

	logger.Info("event worker ready", "subject", incidentCreatedSubject)
	<-ctx.Done()

	if err := subscription.Drain(); err != nil {
		logger.Warn("subscription drain failed", "error", err.Error())
	}
	if err := connection.Drain(); err != nil {
		logger.Warn("NATS drain failed", "error", err.Error())
	}
	return nil
}

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	if err := run(ctx, logger); err != nil && !errors.Is(err, context.Canceled) {
		logger.Error("event worker stopped", "error", err.Error())
		os.Exit(1)
	}
}
