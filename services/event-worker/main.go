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
	"github.com/nats-io/nats.go/jetstream"
)

const (
	incidentCreatedSubject = "labops.incident.created"
	eventStreamName        = "LABOPS_EVENTS"
	durableConsumerName    = "labops-event-worker"
)

var errInvalidEvent = errors.New("invalid event")

type incidentCreated struct {
	EventID    string `json:"event_id"`
	IncidentID string `json:"incident_id"`
	EventType  string `json:"event_type"`
}

type deliveryStore interface {
	Record(context.Context, string, string, []byte) (bool, error)
}

type eventMessage interface {
	Subject() string
	Data() []byte
	DoubleAck(context.Context) error
	NakWithDelay(time.Duration) error
	TermWithReason(string) error
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

func invalidEvent(message string) error {
	return fmt.Errorf("%w: %s", errInvalidEvent, message)
}

func decodeIncidentCreated(payload []byte) (incidentCreated, error) {
	var event incidentCreated
	if len(payload) == 0 || len(payload) > 16*1024 {
		return event, invalidEvent("payload must contain 1-16384 bytes")
	}

	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&event); err != nil {
		return event, fmt.Errorf("%w: decode event: %v", errInvalidEvent, err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return event, invalidEvent("payload must contain one JSON object")
	}

	if event.EventType != "incident.created" {
		return event, invalidEvent("unexpected event_type")
	}
	if !validUUID(event.EventID) {
		return event, invalidEvent("event_id must be a UUID")
	}
	if !validUUID(event.IncidentID) {
		return event, invalidEvent("incident_id must be a UUID")
	}
	return event, nil
}

func recordMessage(
	ctx context.Context, store deliveryStore, subject string, payload []byte,
) (incidentCreated, bool, error) {
	var zero incidentCreated
	if subject != incidentCreatedSubject {
		return zero, false, invalidEvent("unexpected NATS subject")
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

func handleMessage(
	ctx context.Context, store deliveryStore, message eventMessage,
) (incidentCreated, bool, string, error) {
	var zero incidentCreated
	event, inserted, err := recordMessage(
		ctx, store, message.Subject(), message.Data(),
	)
	if err != nil {
		if errors.Is(err, errInvalidEvent) {
			if termErr := message.TermWithReason("invalid LabOps event"); termErr != nil {
				return zero, false, "terminate_failed", errors.Join(err, termErr)
			}
			return zero, false, "terminated", err
		}
		if nakErr := message.NakWithDelay(time.Second); nakErr != nil {
			return zero, false, "retry_failed", errors.Join(err, nakErr)
		}
		return zero, false, "retry", err
	}

	ackCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	if err := message.DoubleAck(ackCtx); err != nil {
		return event, inserted, "ack_failed", fmt.Errorf("double ack: %w", err)
	}
	return event, inserted, "acked", nil
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

func streamConfig() jetstream.StreamConfig {
	return jetstream.StreamConfig{
		Name:              eventStreamName,
		Description:       "LabOps durable domain events",
		Subjects:          []string{incidentCreatedSubject},
		Retention:         jetstream.LimitsPolicy,
		MaxConsumers:      10,
		MaxMsgs:           10000,
		MaxBytes:          64 * 1024 * 1024,
		Discard:           jetstream.DiscardOld,
		MaxAge:            7 * 24 * time.Hour,
		MaxMsgsPerSubject: -1,
		MaxMsgSize:        16 * 1024,
		Storage:           jetstream.FileStorage,
		Replicas:          1,
		Duplicates:        10 * time.Minute,
	}
}

func consumerConfig() jetstream.ConsumerConfig {
	return jetstream.ConsumerConfig{
		Durable:       durableConsumerName,
		Description:   "Persist LabOps incident.created events to PostgreSQL",
		DeliverPolicy: jetstream.DeliverAllPolicy,
		AckPolicy:     jetstream.AckExplicitPolicy,
		AckWait:       10 * time.Second,
		MaxDeliver:    5,
		FilterSubject: incidentCreatedSubject,
		ReplayPolicy:  jetstream.ReplayInstantPolicy,
		MaxAckPending: 64,
	}
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

func configureJetStream(
	ctx context.Context, connection *nats.Conn,
) (jetstream.Consumer, error) {
	js, err := jetstream.New(connection)
	if err != nil {
		return nil, fmt.Errorf("create JetStream context: %w", err)
	}
	stream, err := js.CreateOrUpdateStream(ctx, streamConfig())
	if err != nil {
		return nil, fmt.Errorf("configure stream: %w", err)
	}
	consumer, err := stream.CreateOrUpdateConsumer(ctx, consumerConfig())
	if err != nil {
		return nil, fmt.Errorf("configure consumer: %w", err)
	}
	return consumer, nil
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

	setupCtx, cancelSetup := context.WithTimeout(ctx, 10*time.Second)
	consumer, err := configureJetStream(setupCtx, connection)
	cancelSetup()
	if err != nil {
		return err
	}

	store := postgresStore{pool: pool}
	consumeContext, err := consumer.Consume(
		func(message jetstream.Msg) {
			messageCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()

			event, inserted, outcome, err := handleMessage(messageCtx, store, message)
			if err != nil {
				level := slog.LevelError
				if errors.Is(err, errInvalidEvent) {
					level = slog.LevelWarn
				}
				logger.Log(
					context.Background(),
					level,
					"event processing did not complete normally",
					"subject", message.Subject(),
					"outcome", outcome,
					"error", err.Error(),
				)
				return
			}

			metadata, metadataErr := message.Metadata()
			deliveryAttempt := uint64(0)
			if metadataErr == nil {
				deliveryAttempt = metadata.NumDelivered
			}
			logger.Info(
				"event delivery recorded",
				"subject", message.Subject(),
				"event_id", event.EventID,
				"incident_id", event.IncidentID,
				"inserted", inserted,
				"delivery_attempt", deliveryAttempt,
			)
		},
		jetstream.ConsumeErrHandler(func(_ jetstream.ConsumeContext, err error) {
			logger.Warn("JetStream consume error", "error", err.Error())
		}),
	)
	if err != nil {
		return fmt.Errorf("consume JetStream events: %w", err)
	}

	logger.Info(
		"event worker ready",
		"subject", incidentCreatedSubject,
		"stream", eventStreamName,
		"consumer", durableConsumerName,
	)

	<-ctx.Done()
	consumeContext.Drain()
	select {
	case <-consumeContext.Closed():
	case <-time.After(5 * time.Second):
		logger.Warn("JetStream consumer drain timed out")
		consumeContext.Stop()
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
