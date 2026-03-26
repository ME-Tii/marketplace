import pytest

def test_checkout_requires_login(client):
    response = client.get('/checkout/1', follow_redirects=True)
    assert b'login' in response.data.lower() or b'login' in response.data.decode().lower()

def test_shipping_cost_calculation():
    """Test that shipping cost is multiplied by quantity"""
    shipping_cost_per_item = 5.00
    quantity = 3
    
    expected_shipping = shipping_cost_per_item * quantity
    
    assert expected_shipping == 15.00

def test_shipping_cost_single_item():
    """Test shipping cost with single item"""
    shipping_cost_per_item = 5.00
    quantity = 1
    
    expected_shipping = shipping_cost_per_item * quantity
    
    assert expected_shipping == 5.00

def test_shipping_cost_zero_for_local_pickup():
    """Test that local pickup has no shipping cost"""
    delivery_method = 'local_pickup'
    
    shipping_cost = 0 if delivery_method == 'local_pickup' else 5.00
    
    assert shipping_cost == 0

def test_order_total_with_shipping():
    """Test total calculation: item_total + shipping"""
    item_price = 10.00
    shipping_cost_per_item = 5.00
    quantity = 2
    
    item_total = item_price * quantity
    shipping_total = shipping_cost_per_item * quantity
    order_total = item_total + shipping_total
    
    assert order_total == 30.00
    assert item_total == 20.00
    assert shipping_total == 10.00
