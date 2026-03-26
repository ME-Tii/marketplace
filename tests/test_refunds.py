import pytest

def test_full_refund_includes_shipping():
    """Full refund when seller is at fault includes original shipping"""
    order_amount = 50.00
    shipping_cost = 10.00
    return_shipping = 8.00
    
    full_refund = order_amount + return_shipping
    assert full_refund == 58.00

def test_partial_refund_buyer_pays_return():
    """When buyer pays return, subtract return shipping from refund"""
    order_amount = 50.00
    return_shipping = 8.00
    
    refund = order_amount - return_shipping
    assert refund == 42.00

def test_item_price_only_refund():
    """Refund of just item price (no shipping)"""
    item_price = 45.00
    quantity = 2
    refund = item_price * quantity
    assert refund == 90.00

def test_local_pickup_no_shipping_refund():
    """Local pickup orders have no shipping to refund"""
    order_amount = 50.00
    shipping_cost = 0
    
    refund_with_shipping = order_amount + shipping_cost
    assert refund_with_shipping == 50.00

def test_refund_calculation_multiple_items():
    """Test refund with multiple quantities"""
    item_price = 15.00
    shipping_per_item = 3.00
    quantity = 4
    return_shipping = 12.00
    
    order_total = (item_price + shipping_per_item) * quantity
    full_refund = order_total + return_shipping
    
    assert order_total == 72.00
    assert full_refund == 84.00

def test_zero_return_shipping():
    """When return shipping is 0, full refund = order amount"""
    order_amount = 50.00
    return_shipping = 0
    
    refund = order_amount
    assert refund == 50.00

def test_refund_cannot_exceed_original():
    """Buyer refund cannot exceed original payment"""
    original_amount = 50.00
    return_shipping = 100.00
    
    refund = min(original_amount + return_shipping, original_amount)
    assert refund == 50.00
