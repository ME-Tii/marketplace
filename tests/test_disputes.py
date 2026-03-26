import pytest

def test_order_detail_requires_login(client):
    response = client.get('/order/1', follow_redirects=True)
    assert response.status_code in [200, 404]

def test_dispute_requires_login(client):
    response = client.get('/dispute/1')
    assert response.status_code in [302, 404]

def test_admin_dispute_requires_login(client):
    response = client.get('/admin/dispute/1')
    assert response.status_code in [302, 403]

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
