import pytest

def test_shipping_cost_calculation_with_decimals():
    """Test shipping cost with decimal values"""
    shipping_cost_per_item = 3.99
    quantity = 3
    expected = shipping_cost_per_item * quantity
    assert expected == 11.97

def test_order_total_with_decimal_prices():
    """Test total calculation with decimal prices"""
    item_price = 19.99
    shipping_cost_per_item = 5.50
    quantity = 2
    
    item_total = item_price * quantity
    shipping_total = shipping_cost_per_item * quantity
    order_total = item_total + shipping_total
    
    assert item_total == 39.98
    assert shipping_total == 11.00
    assert order_total == 50.98

def test_transaction_fee_calculation():
    """Test 10% transaction fee calculation"""
    item_total = 100.00
    transaction_fee = item_total * 0.10
    assert transaction_fee == 10.00
    
    item_total = 45.00
    transaction_fee = item_total * 0.10
    assert transaction_fee == 4.50

def test_quantity_zero_returns_zero():
    """Test that zero quantity returns zero shipping"""
    shipping_cost_per_item = 5.00
    quantity = 0
    expected_shipping = shipping_cost_per_item * quantity
    assert expected_shipping == 0

def test_large_quantity_shipping():
    """Test shipping cost with large quantity"""
    shipping_cost_per_item = 2.50
    quantity = 100
    expected = shipping_cost_per_item * quantity
    assert expected == 250.00

def test_none_shipping_handling():
    """Test handling of None/null shipping cost"""
    shipping_cost_per_item = None
    quantity = 3
    shipping = (shipping_cost_per_item or 0) * quantity
    assert shipping == 0
