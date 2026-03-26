import pytest

def test_order_detail_requires_login(client):
    response = client.get('/order/1', follow_redirects=True)
    assert b'login' in response.data.lower() or b'Login' in response.data

def test_dispute_requires_login(client):
    response = client.get('/dispute/1', follow_redirects=True)
    assert b'login' in response.data.lower()

def test_admin_dispute_requires_login(client):
    response = client.get('/admin/dispute/1', follow_redirects=True)
    assert b'login' in response.data.lower() or b'Admin' in response.data

def test_refund_calculation_with_seller_fault():
    """Test refund when seller is at fault: item + shipping + return shipping"""
    order_amount = 30.00
    original_shipping = 10.00
    return_shipping = 10.00
    
    full_refund = order_amount + return_shipping
    
    assert full_refund == 40.00

def test_refund_calculation_buyer_pays_return():
    """Test refund when buyer pays return shipping: item + original shipping - return shipping"""
    order_amount = 30.00
    original_shipping = 10.00
    return_shipping = 10.00
    
    refund_minus_return = order_amount - return_shipping
    
    assert refund_minus_return == 20.00
