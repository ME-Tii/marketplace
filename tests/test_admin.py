import pytest

def test_admin_dashboard_requires_admin(client):
    response = client.get('/admin')
    assert response.status_code == 403

def test_admin_disputes_requires_admin(client):
    response = client.get('/admin/disputes')
    assert response.status_code == 403
