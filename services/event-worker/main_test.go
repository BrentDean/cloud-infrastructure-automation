package main

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/nats-io/nats.go/jetstream"
)

type fakeStore struct {
	calls    int
	subject  string
	eventID  string
	payload  []byte
	inserted bool
	err      error
}

func (store *fakeStore) Record(
	_ context.Context, subject, eventID string, payload []byte,
) (bool, error) {
	store.calls++
	store.subject = subject
	store.eventID = eventID
	store.payload = append([]byte(nil), payload...)
	return store.inserted, store.err
}

type fakeMessage struct {
	subject    string
	data       []byte
	doubleAcks int
	naks       int
	terms      int
	ackErr     error
	nakErr     error
	termErr    error
}

func (message *fakeMessage) Subject() string {
	return message.subject
}

func (message *fakeMessage) Data() []byte {
	return message.data
}

func (message *fakeMessage) DoubleAck(context.Context) error {
	message.doubleAcks++
	return message.ackErr
}

func (message *fakeMessage) NakWithDelay(time.Duration) error {
	message.naks++
	return message.nakErr
}

func (message *fakeMessage) TermWithReason(string) error {
	message.terms++
	return message.termErr
}

func validPayload() []byte {
	return []byte(`{"event_id":"11111111-2222-4333-8444-555555555555","incident_id":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","event_type":"incident.created"}`)
}

func TestRecordMessagePersistsValidEvent(t *testing.T) {
	store := &fakeStore{inserted: true}

	event, inserted, err := recordMessage(
		context.Background(), store, incidentCreatedSubject, validPayload(),
	)
	if err != nil {
		t.Fatalf("recordMessage returned error: %v", err)
	}
	if !inserted {
		t.Fatal("expected inserted delivery")
	}
	if event.EventType != "incident.created" || store.calls != 1 {
		t.Fatalf("unexpected event/store calls: %#v calls=%d", event, store.calls)
	}
	if store.subject != incidentCreatedSubject || store.eventID != event.EventID {
		t.Fatalf("unexpected persisted identifiers: %q %q", store.subject, store.eventID)
	}
}

func TestRecordMessageRejectsMalformedAndUnexpectedEvents(t *testing.T) {
	tests := []struct {
		name    string
		subject string
		payload string
	}{
		{"wrong subject", "labops.other", string(validPayload())},
		{"malformed json", incidentCreatedSubject, `{"event_id":`},
		{"wrong type", incidentCreatedSubject, `{"event_id":"11111111-2222-4333-8444-555555555555","incident_id":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","event_type":"incident.deleted"}`},
		{"unknown field", incidentCreatedSubject, `{"event_id":"11111111-2222-4333-8444-555555555555","incident_id":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","event_type":"incident.created","secret":"nope"}`},
		{"bad event uuid", incidentCreatedSubject, `{"event_id":"not-a-uuid","incident_id":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","event_type":"incident.created"}`},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			store := &fakeStore{inserted: true}
			_, _, err := recordMessage(
				context.Background(), store, test.subject, []byte(test.payload),
			)
			if !errors.Is(err, errInvalidEvent) {
				t.Fatalf("expected invalid-event error, got %v", err)
			}
			if store.calls != 0 {
				t.Fatalf("invalid event reached store: %d calls", store.calls)
			}
		})
	}
}

func TestHandleMessageDoubleAcksSuccessfulStore(t *testing.T) {
	store := &fakeStore{inserted: true}
	message := &fakeMessage{subject: incidentCreatedSubject, data: validPayload()}

	event, inserted, outcome, err := handleMessage(
		context.Background(), store, message,
	)

	if err != nil || outcome != "acked" || !inserted {
		t.Fatalf("unexpected result: event=%#v inserted=%v outcome=%q err=%v", event, inserted, outcome, err)
	}
	if message.doubleAcks != 1 || message.naks != 0 || message.terms != 0 {
		t.Fatalf("unexpected acknowledgement calls: %#v", message)
	}
}

func TestHandleMessageAcksIdempotentDuplicate(t *testing.T) {
	store := &fakeStore{inserted: false}
	message := &fakeMessage{subject: incidentCreatedSubject, data: validPayload()}

	_, inserted, outcome, err := handleMessage(
		context.Background(), store, message,
	)

	if err != nil || outcome != "acked" || inserted {
		t.Fatalf("unexpected duplicate result: inserted=%v outcome=%q err=%v", inserted, outcome, err)
	}
	if message.doubleAcks != 1 {
		t.Fatalf("duplicate must still be acknowledged, got %d acks", message.doubleAcks)
	}
}

func TestHandleMessageNaksTransientStoreFailure(t *testing.T) {
	expected := errors.New("database unavailable")
	store := &fakeStore{err: expected}
	message := &fakeMessage{subject: incidentCreatedSubject, data: validPayload()}

	_, _, outcome, err := handleMessage(context.Background(), store, message)

	if !errors.Is(err, expected) || outcome != "retry" {
		t.Fatalf("expected retry for store error, outcome=%q err=%v", outcome, err)
	}
	if message.naks != 1 || message.doubleAcks != 0 || message.terms != 0 {
		t.Fatalf("unexpected acknowledgement calls: %#v", message)
	}
}

func TestHandleMessageTerminatesPoisonEvent(t *testing.T) {
	store := &fakeStore{inserted: true}
	message := &fakeMessage{
		subject: incidentCreatedSubject,
		data:    []byte(`{"event_type":"wrong"}`),
	}

	_, _, outcome, err := handleMessage(context.Background(), store, message)

	if !errors.Is(err, errInvalidEvent) || outcome != "terminated" {
		t.Fatalf("expected terminated invalid event, outcome=%q err=%v", outcome, err)
	}
	if message.terms != 1 || message.naks != 0 || message.doubleAcks != 0 {
		t.Fatalf("unexpected acknowledgement calls: %#v", message)
	}
	if store.calls != 0 {
		t.Fatalf("poison event reached store: %d calls", store.calls)
	}
}

func TestJetStreamConfigsAreDurableAndBounded(t *testing.T) {
	stream := streamConfig()
	if stream.Name != eventStreamName || stream.Storage != jetstream.FileStorage {
		t.Fatalf("unexpected stream identity/storage: %#v", stream)
	}
	if len(stream.Subjects) != 1 || stream.Subjects[0] != incidentCreatedSubject {
		t.Fatalf("unexpected stream subjects: %#v", stream.Subjects)
	}
	if stream.Replicas != 1 || stream.MaxAge != 7*24*time.Hour || stream.Duplicates != 10*time.Minute {
		t.Fatalf("unexpected stream durability limits: %#v", stream)
	}

	consumer := consumerConfig()
	if consumer.Durable != durableConsumerName || consumer.AckPolicy != jetstream.AckExplicitPolicy {
		t.Fatalf("unexpected consumer durability config: %#v", consumer)
	}
	if consumer.FilterSubject != incidentCreatedSubject || consumer.MaxDeliver != 5 {
		t.Fatalf("unexpected consumer delivery config: %#v", consumer)
	}
}
