package main

import (
	"context"
	"errors"
	"testing"
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

func TestRecordMessagePersistsValidEvent(t *testing.T) {
	store := &fakeStore{inserted: true}
	payload := []byte(`{"event_id":"11111111-2222-4333-8444-555555555555","incident_id":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","event_type":"incident.created"}`)

	event, inserted, err := recordMessage(
		context.Background(), store, incidentCreatedSubject, payload,
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
		{"wrong subject", "labops.other", `{"event_id":"11111111-2222-4333-8444-555555555555","incident_id":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","event_type":"incident.created"}`},
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
			if err == nil {
				t.Fatal("expected validation error")
			}
			if store.calls != 0 {
				t.Fatalf("invalid event reached store: %d calls", store.calls)
			}
		})
	}
}

func TestRecordMessageSurfacesStoreError(t *testing.T) {
	expected := errors.New("database unavailable")
	store := &fakeStore{err: expected}
	payload := []byte(`{"event_id":"11111111-2222-4333-8444-555555555555","incident_id":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","event_type":"incident.created"}`)

	_, _, err := recordMessage(
		context.Background(), store, incidentCreatedSubject, payload,
	)
	if !errors.Is(err, expected) {
		t.Fatalf("expected store error, got %v", err)
	}
}

func TestRecordMessageReportsIdempotentDuplicate(t *testing.T) {
	store := &fakeStore{inserted: false}
	payload := []byte(`{"event_id":"11111111-2222-4333-8444-555555555555","incident_id":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","event_type":"incident.created"}`)

	event, inserted, err := recordMessage(
		context.Background(), store, incidentCreatedSubject, payload,
	)
	if err != nil {
		t.Fatalf("recordMessage returned error: %v", err)
	}
	if inserted {
		t.Fatal("expected duplicate delivery to report inserted=false")
	}
	if event.EventID == "" || store.calls != 1 {
		t.Fatalf("expected one idempotent store call, event=%#v calls=%d", event, store.calls)
	}
}
