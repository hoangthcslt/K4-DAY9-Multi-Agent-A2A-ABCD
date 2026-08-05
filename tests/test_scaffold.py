from pathlib import Path

from olist_multi_agent.config import Settings
from olist_multi_agent.contracts import AgentHandoff, CaseInput
from olist_multi_agent.data_loader import OlistIndexes
from olist_multi_agent.verifier import verify_candidate


def test_settings_defaults_to_disabled_local_provider(tmp_path: Path) -> None:
    settings = Settings.from_env(tmp_path)
    assert settings.llm_enabled is False
    assert settings.llm_provider == "ollama"
    assert settings.api_key() == ""


def test_case_and_handoff_contracts() -> None:
    case = CaseInput.model_validate(
        {
            "case_id": "EC_001",
            "customer_request": {"claimed_order_id": "order-1"},
            "investigation_scope": {
                "include_customer_history": True,
                "include_product_context": True,
            },
            "policy_version": "EC_POLICY_V2",
        }
    )
    handoff = AgentHandoff(case_id=case.case_id, agent="customer")
    assert handoff.status == "pending"


def test_basic_verifier_rejects_wrong_case_id() -> None:
    result = verify_candidate({"case_id": "EC_999"}, "EC_001")
    assert result.valid is False


def test_customer_history_index_contains_order_ids() -> None:
    indexes = OlistIndexes.load(Path("data"))
    history_ids = [
        order_id
        for order_ids in indexes.customer_order_ids_by_unique_id.values()
        for order_id in order_ids
    ]
    assert history_ids
    assert set(history_ids).issubset(indexes.orders_by_id)


def test_verifier_rejects_unknown_related_order() -> None:
    indexes = OlistIndexes.load(Path("data"))
    result = verify_candidate(
        {
            "case_id": "EC_001",
            "customer_context": {
                "related_order_ids": ["not-an-order-id"],
            },
        },
        "EC_001",
        indexes=indexes,
    )
    assert result.valid is False
    assert any("related_order_id does not exist" in error for error in result.errors)
