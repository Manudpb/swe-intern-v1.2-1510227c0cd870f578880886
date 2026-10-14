"""FR-021 / constitution Principle V - the answer key is unreachable at runtime.

A service that can see the answer key produces a score that measures nothing, and the failure
is unrecoverable after the fact. So this is asserted two ways: no runtime file access touches
a ground-truth path, and the submitted filename changes nothing about the report.

The compose-mount check lives in T112 on the host, because the compose file is not inside the
image where these tests run (finding I1).
"""
from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from tests.conftest import submit

pytestmark = pytest.mark.integration


def test_no_runtime_file_access_touches_a_ground_truth_path(
    client, damage_photo, monkeypatch
):
    opened: list[str] = []
    real_open = builtins.open
    real_path_open = Path.open

    def recording_open(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    def recording_path_open(self, *args, **kwargs):
        opened.append(str(self))
        return real_path_open(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", recording_open)
    monkeypatch.setattr(Path, "open", recording_path_open)

    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")
    assert response.status_code == 200

    offenders = [path for path in opened if "ground-truth" in path.replace("\\", "/")]
    assert not offenders, f"runtime code read the answer key: {offenders}"


def test_renaming_the_photo_does_not_change_the_report(make_client, damage_photo):
    """No filename-to-answer-key correspondence can exist if the name is never used."""
    from tests.fakes import FakeLLM
    from tests.fakes.scripts.scenarios import clean_triage

    first_client, _ = make_client(llm=FakeLLM(clean_triage()))
    second_client, _ = make_client(llm=FakeLLM(clean_triage()))

    as_img_001 = first_client.post(
        "/api/v1/claims/triage",
        data={"description": "Burst pipe in the kitchen"},
        files=[("images", ("IMG_001.jpg", damage_photo, "image/jpeg"))],
    )
    as_random = second_client.post(
        "/api/v1/claims/triage",
        data={"description": "Burst pipe in the kitchen"},
        files=[("images", ("zzz-unrelated-name.jpg", damage_photo, "image/jpeg"))],
    )

    assert as_img_001.status_code == as_random.status_code == 200
    first = as_img_001.json()["triage_assessment"]
    second = as_random.json()["triage_assessment"]
    assert first == second


def test_the_knowledge_base_is_the_only_corpus_the_app_knows(deps):
    """The app holds the archive; nothing else is wired in as retrieval material."""
    assert deps.knowledge_base
    for claim_id, record in deps.knowledge_base.items():
        assert claim_id.startswith("CLM-")
        # Answer-key records are keyed IMG_xxx and carry image_description; archive records
        # never do. If one ever leaked into the corpus, this would catch it.
        assert "image_description" not in record
        assert "description_hint" not in record


def test_settings_do_not_point_anywhere_near_the_answer_key(settings):
    for path in (settings.knowledge_base_dir, settings.tools_dir, settings.openapi_path):
        assert "ground-truth" not in str(path).replace("\\", "/")
