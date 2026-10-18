from tests.utils.requisition import ClientRequisition


def test_health_check_is_available():
    """O Compose precisa reconhecer que a API está pronta para receber pedidos."""
    response = ClientRequisition.send("GET", "/health_check")

    assert response.response_status == 204
