def assert_decision(response: dict, status: str, code: str) -> dict:
    """Confere o status e o único motivo, e devolve o `reason` para quem quiser conferir os valores."""
    assert response["status"] == status, response
    reason = response["metadata"]["reason"]
    assert reason["code"] == code, response
    assert response["metadata"]["policy_version"] == "pix-v1.3"

    return reason
