import pytest

def test_register_page_loads(client):
    response = client.get('/register')
    assert response.status_code == 200

def test_login_page_loads(client):
    response = client.get('/login')
    assert response.status_code == 200

def test_forgot_password_page_loads(client):
    response = client.get('/forgot-password')
    assert response.status_code == 200

def test_logout_requires_login(client):
    response = client.get('/logout', follow_redirects=True)
    assert response.status_code == 200

def test_homepage_loads(client):
    response = client.get('/')
    assert response.status_code == 200

def test_dashboard_loads(client):
    response = client.get('/dashboard')
    assert response.status_code == 200

def test_about_page_loads(client):
    response = client.get('/about')
    assert response.status_code == 200

def test_contact_page_loads(client):
    response = client.get('/contact')
    assert response.status_code == 200

def test_terms_page_loads(client):
    response = client.get('/terms')
    assert response.status_code == 200

def test_privacy_page_loads(client):
    response = client.get('/privacy')
    assert response.status_code == 200
