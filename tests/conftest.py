import json
from pathlib import Path

import pytest

from classpartai.action.harness import Harness, Settings
from classpartai.action.store import Store
from classpartai.classlist import ClassList
from classpartai.contracts import SessionResults

DATA = Path(__file__).resolve().parents[1] / "data"


class FakeMailer:
    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.fail = fail

    def send(self, to, subject, text, idempotency_key):
        if self.fail:
            raise RuntimeError("provider down")
        self.sent.append({"to": to, "subject": subject, "text": text, "key": idempotency_key})
        return f"msg-{len(self.sent)}"


@pytest.fixture
def session() -> SessionResults:
    return SessionResults.model_validate_json((DATA / "sample_session.json").read_text())


@pytest.fixture
def classlist(tmp_path) -> ClassList:
    path = tmp_path / "classlist.json"
    path.write_text((DATA / "sample_classlist.json").read_text())
    return ClassList(path)


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture
def harness(tmp_path, classlist, mailer) -> Harness:
    settings = Settings(test_mode=False, test_recipient="", prof_email="prof@example.edu")
    return Harness(Store(tmp_path / "test.db"), classlist, mailer, settings)


def tool_call(id_, name, **arguments):
    return {
        "id": id_,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }
