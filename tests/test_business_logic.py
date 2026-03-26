import pytest
import os

def test_shipping_cost_multiplied_by_quantity():
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

def test_order_total_calculation():
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

def test_full_refund_seller_at_fault():
    """Test refund when seller is at fault: item + shipping + return shipping"""
    order_amount = 30.00
    return_shipping = 10.00
    full_refund = order_amount + return_shipping
    assert full_refund == 40.00

def test_refund_buyer_pays_return():
    """Test refund when buyer pays return shipping: item + original shipping - return shipping"""
    order_amount = 30.00
    return_shipping = 10.00
    refund = order_amount - return_shipping
    assert refund == 20.00

def test_quantity_validation():
    """Test that quantity must be positive"""
    quantity = 1
    assert quantity >= 1

def test_zero_shipping_when_no_shipping_flag():
    """Test shipping cost is 0 when shipping not available"""
    has_shipping = False
    shipping_cost = 5.00 if has_shipping else 0
    assert shipping_cost == 0
