from types import SimpleNamespace

import smtplib

from app.services.notification import NotificationService


class FakeSMTP:
    def __init__(self, host, port, timeout=None):  # noqa: D401
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in = None
        self.sent_messages = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.logged_in = (username, password)

    def send_message(self, message):
        self.sent_messages.append(message)


class AuditStub:
    def __init__(self):
        self.events = []

    def record_event(
        self,
        *,
        event_type,
        actor_id,
        actor_role,
        document_id=None,
        ip_address=None,
        user_agent=None,
        details=None,
    ):
        self.events.append(
            {
                "event_type": event_type,
                "document_id": document_id,
                "details": details or {},
            }
        )


class FakeTwilioClient:
    def __init__(self, *args, **kwargs):
        self.messages = self
        self.sent = []

    def create(self, **kwargs):
        self.sent.append(kwargs)


class DummySession:
    class _EmptyResult:
        def first(self):
            return None

    def exec(self, *_args, **_kwargs):
        return DummySession._EmptyResult()


def test_email_notification_success(monkeypatch):
    fake = FakeSMTP("smtp.example.com", 587, timeout=10)

    def fake_smtp(host, port, timeout=None):
        # Return the same fake regardless of args to inspect later
        return fake

    monkeypatch.setattr(smtplib, "SMTP", fake_smtp)

    audit = AuditStub()
    service = NotificationService(audit_service=audit, session=DummySession())
    service.configure_public_base_url("http://example.com")
    service.configure_email(
        host="smtp.example.com",
        port=587,
        sender="Sender <sender@example.com>",
        username="user",
        password="pass",
        starttls=True,
    )

    request = SimpleNamespace(id="req-1")
    party = SimpleNamespace(email="to@example.com", full_name="Test User", notification_channel="email")
    document = SimpleNamespace(id="doc-1", name="Contrato ABC")

    result = service.notify_signature_request(request, party, document, token="token123")

    assert result is True
    assert fake.started_tls is True
    assert fake.logged_in == ("user", "pass")
    assert len(fake.sent_messages) == 1
    message = fake.sent_messages[0]
    assert message.is_multipart()
    text_part = message.get_body(preferencelist=("plain",))
    html_part = message.get_body(preferencelist=("html",))
    assert text_part is not None
    assert html_part is not None
    html_content = html_part.get_content()
    assert "http://example.com/public/sign/token123" in html_content
    types = {event["event_type"] for event in audit.events}
    assert "notification_attempt" in types
    assert "notification_sent" in types


def test_email_notification_includes_agent_download_link(monkeypatch):
    fake = FakeSMTP("smtp.example.com", 587, timeout=10)
    monkeypatch.setattr(smtplib, "SMTP", lambda host, port, timeout=None: fake)

    audit = AuditStub()
    download_url = "https://downloads.example.com/agente.exe"
    service = NotificationService(audit_service=audit, agent_download_url=download_url, session=DummySession())
    service.configure_public_base_url("http://example.com")
    service.configure_email(
        host="smtp.example.com",
        port=587,
        sender="Sender <sender@example.com>",
        username="user",
        password="pass",
        starttls=True,
    )

    request = SimpleNamespace(id="req-1")
    party = SimpleNamespace(email="to@example.com", full_name="Test User", notification_channel="email")
    document = SimpleNamespace(id="doc-1", name="Contrato ABC")

    assert service.notify_signature_request(request, party, document, token="token123") is True
    message = fake.sent_messages[0]
    text_part = message.get_body(preferencelist=("plain",))
    html_part = message.get_body(preferencelist=("html",))
    assert text_part is not None
    assert html_part is not None
    assert download_url in html_part.get_content()
    assert "Baixe e instale o agente de assinatura" in html_part.get_content()
    assert download_url in text_part.get_content()


def test_signature_request_uses_customer_trade_name(monkeypatch):
    fake = FakeSMTP("smtp.example.com", 587, timeout=10)
    monkeypatch.setattr(smtplib, "SMTP", lambda host, port, timeout=None: fake)

    class StubResult:
        def __init__(self, value):
            self.value = value

        def first(self):
            return self.value

    class StubSession:
        def __init__(self, result):
            self.result = result

        def exec(self, *_args, **_kwargs):
            return StubResult(self.result)

    audit = AuditStub()
    session = StubSession(SimpleNamespace(trade_name="Fantasia Ltda", corporate_name="Razao Ltda"))
    service = NotificationService(audit_service=audit, session=session)
    service.configure_public_base_url("http://example.com")
    service.configure_email(
        host="smtp.example.com",
        port=587,
        sender="Sender <sender@example.com>",
        username="user",
        password="pass",
        starttls=True,
    )

    request = SimpleNamespace(id="req-1")
    party = SimpleNamespace(email="to@example.com", full_name="Test User", notification_channel="email")
    document = SimpleNamespace(
        id="doc-1",
        name="Contrato ABC",
        tenant_id="ae3ddf60-0611-4bd5-80f1-a335190e2f88",
        tenant=SimpleNamespace(name="Admin Tenant"),
        customer=SimpleNamespace(trade_name="Fantasia Ltda", corporate_name="Razao Ltda"),
    )

    assert service.notify_signature_request(request, party, document, token="token123") is True
    message = fake.sent_messages[0]
    html_part = message.get_body(preferencelist=("html",))
    assert html_part is not None
    html_content = html_part.get_content()
    assert "Fantasia Ltda" in html_content
    assert "Admin Tenant" not in html_content


def test_signature_request_uses_document_customer_name(monkeypatch):
    fake = FakeSMTP("smtp.example.com", 587, timeout=10)
    monkeypatch.setattr(smtplib, "SMTP", lambda host, port, timeout=None: fake)

    audit = AuditStub()
    service = NotificationService(audit_service=audit, session=DummySession())
    service.configure_public_base_url("http://example.com")
    service.configure_email(
        host="smtp.example.com",
        port=587,
        sender="Sender <sender@example.com>",
        username="user",
        password="pass",
        starttls=True,
    )

    document = SimpleNamespace(
        id="doc-2",
        name="Contrato DEF",
        customer=SimpleNamespace(trade_name=None, corporate_name="Empresa Real S.A."),
    )
    request = SimpleNamespace(id="req-2")
    party = SimpleNamespace(email="to@example.com", full_name="User B", notification_channel="email")

    assert service.notify_signature_request(request, party, document, token="token456") is True
    html_part = fake.sent_messages[0].get_body(preferencelist=("html",))
    assert html_part is not None
    assert "Empresa Real S.A." in html_part.get_content()


def test_signature_request_neutral_fallback_when_missing_customer(monkeypatch):
    fake = FakeSMTP("smtp.example.com", 587, timeout=10)
    monkeypatch.setattr(smtplib, "SMTP", lambda host, port, timeout=None: fake)

    audit = AuditStub()
    service = NotificationService(audit_service=audit, session=DummySession())
    service.configure_public_base_url("http://example.com")
    service.configure_email(
        host="smtp.example.com",
        port=587,
        sender="Sender <sender@example.com>",
        username="user",
        password="pass",
        starttls=True,
    )

    request = SimpleNamespace(id="req-3")
    party = SimpleNamespace(email="to@example.com", full_name="Test User", notification_channel="email")
    document = SimpleNamespace(id="doc-3", name="Contrato XYZ", tenant_id=None, tenant=None, created_by=None)

    assert service.notify_signature_request(request, party, document, token="token789") is True
    html_part = fake.sent_messages[0].get_body(preferencelist=("html",))
    assert html_part is not None
    assert "Empresa solicitante" in html_part.get_content()


def test_email_notification_error_is_audited(monkeypatch):
    class ErrorSMTP(FakeSMTP):
        def send_message(self, message):  # noqa: D401
            raise RuntimeError("SMTP send failed")

    error_fake = ErrorSMTP("smtp.example.com", 587, timeout=10)

    def fake_smtp(host, port, timeout=None):
        return error_fake

    monkeypatch.setattr(smtplib, "SMTP", fake_smtp)

    audit = AuditStub()
    service = NotificationService(audit_service=audit, session=DummySession())
    service.configure_public_base_url("http://example.com")
    service.configure_email(
        host="smtp.example.com",
        port=587,
        sender="Sender <sender@example.com>",
        username="user",
        password="pass",
        starttls=True,
    )

    request = SimpleNamespace(id="req-1")
    party = SimpleNamespace(email="to@example.com", full_name="Test User", notification_channel="email")
    document = SimpleNamespace(id="doc-1", name="Contrato ABC")

    service.notify_signature_request(request, party, document, token="token123")

    types = [event["event_type"] for event in audit.events]
    assert "notification_attempt" in types
    assert "notification_error" in types


def test_notification_skipped_when_channel_unsupported():
    audit = AuditStub()
    service = NotificationService(audit_service=audit, session=DummySession())

    request = SimpleNamespace(id="req-1")
    party = SimpleNamespace(email=None, full_name="Test User", notification_channel="sms")
    document = SimpleNamespace(id="doc-1", name="Contrato ABC")

    result = service.notify_signature_request(request, party, document)

    assert result is False
    assert any(event["event_type"] == "notification_skipped" for event in audit.events)


def test_sms_notification_success(monkeypatch):
    audit = AuditStub()
    service = NotificationService(
        audit_service=audit,
        public_base_url="http://example.com",
        session=DummySession(),
    )
    service.configure_sms(account_sid="sid", auth_token="token", from_number="+123456789")

    fake_client = FakeTwilioClient()

    def fake_twilio_client(account_sid, auth_token):
        return fake_client

    monkeypatch.setattr("app.services.notification.Client", fake_twilio_client)

    request = SimpleNamespace(id="req-1")
    party = SimpleNamespace(phone_number="+5511999999999", notification_channel="sms", full_name="Test")
    document = SimpleNamespace(id="doc-1", name="Contrato ABC")

    result = service.notify_signature_request(request, party, document, token="token123")

    assert result is True
    assert len(fake_client.sent) == 1
    assert "http://example.com/public/sign/token123" in fake_client.sent[0]["body"]
    assert any(event["event_type"] == "notification_sent" for event in audit.events)


def test_sms_notification_skipped_without_config():
    audit = AuditStub()
    service = NotificationService(audit_service=audit, session=DummySession())

    request = SimpleNamespace(id="req-1")
    party = SimpleNamespace(phone_number="+5511999999999", notification_channel="sms", full_name="Test")
    document = SimpleNamespace(id="doc-1", name="Contrato ABC")

    result = service.notify_signature_request(request, party, document, token="token123")

    assert result is False

def test_notify_workflow_completed_with_attachments(monkeypatch, tmp_path):
    fake = FakeSMTP("smtp.example.com", 587, timeout=10)

    def fake_smtp(host, port, timeout=None):
        return fake

    monkeypatch.setattr(smtplib, "SMTP", fake_smtp)

    audit = AuditStub()
    service = NotificationService(audit_service=audit, session=DummySession())
    service.configure_email(
        host="smtp.example.com",
        port=587,
        sender="Sender <sender@example.com>",
        username=None,
        password=None,
        starttls=False,
    )

    report_path = tmp_path / "relatorio-final.pdf"
    report_path.write_bytes(b"%PDF-1.4 test report")

    document = SimpleNamespace(id="doc-1", name="Contrato XYZ")
    parties = [SimpleNamespace(email="signer@example.com")]

    service.notify_workflow_completed(
        document=document,
        parties=parties,
        attachments=[report_path],
        extra_recipients=["owner@example.com"],
    )

    assert len(fake.sent_messages) == 2
    first_message = fake.sent_messages[0]
    attachments = list(first_message.iter_attachments())
    assert attachments, "expected attachment in completion email"
    assert attachments[0].get_filename() == "relatorio-final.pdf"

    sent_event_types = {event["event_type"] for event in audit.events}
    assert "workflow_completed_notification_sent" in sent_event_types
