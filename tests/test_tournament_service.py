import mongomock

import services.tournament_service as ts


def _collection():
    client = mongomock.MongoClient()
    return client["test_db"]["tournaments"]


def _seed_basic(collection):
    tour = ts.create_tournament(name="Cup", collection=collection)
    ts.add_participant(tournament_name="Cup", team_name="Team A", coach_id=1, collection=collection)
    ts.add_participant(tournament_name="Cup", team_name="Team B", coach_id=2, collection=collection)
    return tour


def test_preview_bracket_does_not_mutate():
    collection = _collection()
    _seed_basic(collection)

    preview = ts.preview_bracket(tournament_name="Cup", collection=collection)
    assert len(preview) == 1
    assert preview[0]["team_a"] == "Team A"
    assert preview[0]["team_b"] == "Team B"

    # State should remain draft and no matches inserted
    tour = ts.get_tournament("Cup", collection=collection)
    assert tour["state"] == ts.TOURNAMENT_STATE_DRAFT
    assert ts.list_matches("Cup", collection=collection) == []


def test_generate_bracket_idempotent():
    collection = _collection()
    _seed_basic(collection)

    first = ts.generate_bracket(tournament_name="Cup", collection=collection)
    assert len(first) == 1
    second = ts.generate_bracket(tournament_name="Cup", collection=collection)
    assert len(second) == 1

    # Should not create duplicate matches
    assert collection.count_documents({"record_type": "tournament_match"}) == 1


def test_match_report_and_confirm_with_expected_updated_at():
    collection = _collection()
    _seed_basic(collection)
    matches = ts.generate_bracket(tournament_name="Cup", collection=collection)
    match_id = str(matches[0]["_id"])
    expected = matches[0]["updated_at"]

    reported = ts.report_score(
        tournament_name="Cup",
        match_id=match_id,
        reporter_team_id=matches[0]["team_a"],
        score_for=2,
        score_against=1,
        expected_updated_at=expected,
        collection=collection,
    )
    assert reported["scores"]
    # Use stale expected_updated_at to force retry
    stale = expected.replace(year=expected.year - 1)
    try:
        ts.confirm_match(
            tournament_name="Cup",
            match_id=match_id,
            confirming_team_id=matches[0]["team_b"],
            expected_updated_at=stale,
            collection=collection,
        )
        assert False, "Expected concurrency error"
    except RuntimeError:
        pass

    # Fresh expected_updated_at should work
    fresh = collection.find_one({"_id": matches[0]["_id"]})["updated_at"]
    confirmed = ts.confirm_match(
        tournament_name="Cup",
        match_id=match_id,
        confirming_team_id=matches[0]["team_b"],
        expected_updated_at=fresh,
        collection=collection,
    )
    assert confirmed["status"] == ts.MATCH_STATUS_COMPLETED
