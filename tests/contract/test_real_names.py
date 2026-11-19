"""The centralized acceptance names must stay tied to real definitions."""

from tests.contract import names
from tests.contract.adapter import resolve_callable


def test_every_named_implementation_entry_point_resolves():
    for path in (
        names.ANSWER_CONTRACT_EVALUATOR,
        names.ANSWER_MERGER,
        names.SOURCE_INVENTORY_BUILDER,
        names.COVERAGE_EVALUATOR,
        names.SLOT_EXTRACTOR,
        names.LOGICAL_CALL_EXECUTOR,
        names.DOCUMENT_STATE_EVALUATOR,
        names.REVIEW_DISPOSITION_EVALUATOR,
        names.PREPROCESS_FILE,
    ):
        assert callable(resolve_callable(path)), path


def test_attempt_disposition_and_state_names_match_real_modules():
    import llm_contract as contract
    from app.core import review

    attempt = contract.new_attempt("offline-model")
    assert names.ATTEMPTS_FIELD == "attempts"
    assert {"section", "http_status", "error_kind", "retry", "retry_reason"} <= set(attempt)
    assert set(review.DISPOSITIONS) == {
        names.DISPOSITION_CONFIRMED_ABSENT,
        names.DISPOSITION_ENTERED_MANUALLY,
    }
    assert review.document_state({"attention": []}) == names.DOCUMENT_STATE_READY
    assert review.document_state({
        "attention": [{"id": "att-1", "text": "missing", "disposition": None}]
    }) == names.DOCUMENT_STATE_NEEDS_ATTENTION


def test_route_constants_match_registered_methods_and_paths():
    from app.api.routes import extract, review

    routes = {
        (method, route.path)
        for router in (extract.router, review.router)
        for route in router.routes
        for method in route.methods
    }
    assert ("POST", names.REVIEW_ROUTE) in routes
    assert ("PATCH", names.FIELD_EDIT_ROUTE) in routes
    assert ("PATCH", names.CELL_EDIT_ROUTE) in routes
    assert ("GET", names.DOWNLOAD_ROUTE) in routes
