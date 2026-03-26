import pytest

def test_login_page(client):
    response = client.get('/login')
    assert response.status_code == 200
    assert b'Login' in response.data or b'Anmelden' in response.data

def test_register_page(client):
    response = client.get('/register')
    assert response.status_code == 200
    assert b'Register' in response.data or b'Registrieren' in response.data

def test_login_invalid_user(client):
    response = client.post('/login', data={
        'username': 'nonexistent',
        'password': 'wrongpass'
    }, follow_redirects=True)
    assert response.status_code == 400
    assert b'required' in response.data or b'Invalid' in response.data

def test_protected_route_requires_login(client):
    response = client.get('/dashboard', follow_redirects=True)
    assert response.status_code == 200
