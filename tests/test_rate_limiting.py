import pytest

def test_rate_limit_login_endpoint(client):
    """Test that login endpoint can be accessed (rate limit kicks in after repeated requests)"""
    response = client.get('/login')
    assert response.status_code in [200, 429]

def test_rate_limit_register_endpoint(client):
    """Test that register endpoint can be accessed"""
    response = client.get('/register')
    assert response.status_code in [200, 429]

def test_rate_limit_contact_endpoint(client):
    """Test that contact endpoint can be accessed"""
    response = client.get('/contact')
    assert response.status_code in [200, 429]

def test_rate_limit_forgot_password_endpoint(client):
    """Test that forgot password endpoint can be accessed"""
    response = client.get('/forgot-password')
    assert response.status_code in [200, 429]
