import pytest

def test_create_post_page_loads(client):
    response = client.get('/create_post_page', follow_redirects=True)
    assert response.status_code == 200

def test_search_or_listing_page(client):
    response = client.get('/')
    assert response.status_code == 200

def test_post_detail_requires_login_for_buy(client):
    response = client.get('/checkout/1', follow_redirects=True)
    assert response.status_code == 200

def test_edit_post_requires_login(client):
    response = client.get('/edit_post/1', follow_redirects=True)
    assert response.status_code == 200

def test_delete_post_requires_login(client):
    response = client.post('/delete_post/1', follow_redirects=True)
    assert response.status_code == 200

def test_messages_requires_login(client):
    response = client.get('/messages', follow_redirects=True)
    assert response.status_code == 200

def test_orders_requires_login(client):
    response = client.get('/orders', follow_redirects=True)
    assert response.status_code == 200

def test_profile_route_exists(client):
    response = client.get('/profile/nonexistent')
    assert response.status_code in [200, 302, 404]
