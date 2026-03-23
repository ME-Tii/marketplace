#!/usr/bin/env python3
import sqlite3
import os

# Change to marketplace directory
os.chdir('/home/thomasseitz22/marketplace')

conn = sqlite3.connect('database.db')
c = conn.cursor()

# Get user IDs
c.execute("SELECT id, username FROM users LIMIT 5")
users = {row[1]: row[0] for row in c.fetchall()}
print(f"Found users: {users}")

# Get category IDs
c.execute("SELECT id, name FROM categories LIMIT 10")
categories = {row[1]: row[0] for row in c.fetchall()}
print(f"Found categories: {categories}")

# Sample listings with placeholder images
demo_listings = [
    {
        'title': 'MacBook Pro 2021 14" M1 Pro',
        'description': 'Excellent condition, barely used. Includes charger and original box. Perfect for students and professionals. Battery health at 95%.',
        'type': 'sell',
        'price': 1200.00,
        'image': 'https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=400',
        'category': 'Electronics',
        'user': 'user1'
    },
    {
        'title': 'IKEA MALM Desk - White',
        'description': 'Barely used MALM desk with pull-out panel. Some minor scratches but overall great condition. Pickup only.',
        'type': 'sell',
        'price': 80.00,
        'image': 'https://images.unsplash.com/photo-1518455027359-f3f8164ba6bd?w=400',
        'category': 'Furniture',
        'user': 'user2'
    },
    {
        'title': 'Sony WH-1000XM4 Headphones',
        'description': 'Best noise-canceling headphones. Used for 6 months. Comes with case and cables. Black color.',
        'type': 'sell',
        'price': 180.00,
        'image': 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=400',
        'category': 'Electronics',
        'user': 'admin'
    },
    {
        'title': 'Nike Air Max 270 - Size 10',
        'description': 'Brand new, never worn. Bought wrong size. Original price $150, selling for $90.',
        'type': 'sell',
        'price': 90.00,
        'image': 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=400',
        'category': 'Fashion',
        'user': 'user1'
    },
    {
        'title': 'Looking for: Gaming Monitor 27"',
        'description': 'Looking for a 27 inch gaming monitor, 144Hz or higher. Budget around $200. Can pick up locally.',
        'type': 'buy',
        'price': 200.00,
        'image': 'https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?w=400',
        'category': 'Electronics',
        'user': 'user2'
    },
    {
        'title': 'Nintendo Switch OLED',
        'description': 'Selling my Switch OLED, comes with dock, joycons, and 3 games (Zelda, Mario Kart, Smash). All in original boxes.',
        'type': 'sell',
        'price': 280.00,
        'image': 'https://images.unsplash.com/photo-1578303512597-81e6cc155b3e?w=400',
        'category': 'Electronics',
        'user': 'admin'
    },
    {
        'title': 'FREE: Moving - Take My Couch',
        'description': 'Must pick up by this weekend. Gray fabric couch, 3 seater. Some wear but very comfortable. You haul!',
        'type': 'giveaway',
        'price': 0,
        'image': 'https://images.unsplash.com/photo-1555041469-a586c61ea9bc?w=400',
        'category': 'Furniture',
        'user': 'user1'
    },
    {
        'title': 'iPhone 14 Pro Max 256GB',
        'description': 'Space Black, excellent condition with case and screen protector since day 1. Includes original box and charger.',
        'type': 'sell',
        'price': 850.00,
        'image': 'https://images.unsplash.com/photo-1678685888221-cda773a3dcdb?w=400',
        'category': 'Electronics',
        'user': 'user2'
    },
    {
        'title': 'Vintage Vinyl Records Collection',
        'description': 'About 50 records from the 70s-90s. Rock, jazz, and classical. Selling as a lot only.',
        'type': 'sell',
        'price': 150.00,
        'image': 'https://images.unsplash.com/photo-1603048588665-791ca8aea617?w=400',
        'category': 'Collectibles',
        'user': 'admin'
    },
    {
        'title': 'Trading: PS5 for Xbox Series X',
        'description': 'Looking to trade my PS5 (with 2 controllers) for an Xbox Series X. Both in great condition.',
        'type': 'trade',
        'price': 0,
        'image': 'https://images.unsplash.com/photo-1606144042614-b2417e99c4e3?w=400',
        'category': 'Electronics',
        'user': 'user1'
    },
    {
        'title': 'KitchenAid Stand Mixer',
        'description': 'Artisan series, red color. Used only a few times, like new. Includes all original attachments.',
        'type': 'sell',
        'price': 250.00,
        'image': 'https://images.unsplash.com/photo-1594385208974-2e75f8d7bb48?w=400',
        'category': 'Home',
        'user': 'user2'
    },
    {
        'title': 'Mountain Bike - Trek Marlin 7',
        'description': '2022 model, size L. Perfect for trails and commuting. Recent tune-up, new brakes. Great condition!',
        'type': 'sell',
        'price': 600.00,
        'image': 'https://images.unsplash.com/photo-1576435728678-68d0fbf94e91?w=400',
        'category': 'Sports',
        'user': 'admin'
    },
    {
        'title': 'Textbooks: Computer Science',
        'description': 'Selling 5 CS textbooks - algorithms, databases, web development. All in good condition. Make an offer!',
        'type': 'sell',
        'price': 50.00,
        'image': 'https://images.unsplash.com/photo-1532012197267-da84d127e765?w=400',
        'category': 'Books',
        'user': 'user1'
    },
    {
        'title': 'Samsung 55" 4K Smart TV',
        'description': 'Used for 2 years, still works perfectly. Includes remote and wall mount bracket. Great for gaming!',
        'type': 'sell',
        'price': 350.00,
        'image': 'https://images.unsplash.com/photo-1593359677879-a4bb92f829d1?w=400',
        'category': 'Electronics',
        'user': 'user2'
    },
    {
        'title': 'Roomba i7+ Robot Vacuum',
        'description': 'Cleans itself! Includes auto-empty base. Works great, just upgraded to newer model. All accessories included.',
        'type': 'sell',
        'price': 300.00,
        'image': 'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400',
        'category': 'Home',
        'user': 'admin'
    },
]

# Check if posts table has local_pickup and shipping_available columns
c.execute("PRAGMA table_info(posts)")
columns = [col[1] for col in c.fetchall()]
has_delivery = 'local_pickup' in columns and 'shipping_available' in columns
print(f"Has delivery columns: {has_delivery}")

for listing in demo_listings:
    user_id = users.get(listing['user'])
    category_id = categories.get(listing['category'])
    
    if not user_id:
        print(f"Skipping: User {listing['user']} not found")
        continue
    
    # Check if listing already exists
    c.execute("SELECT id FROM posts WHERE title = ?", (listing['title'],))
    if c.fetchone():
        print(f"Skipping: Listing '{listing['title']}' already exists")
        continue
    
    if has_delivery:
        c.execute("""
            INSERT INTO posts (title, description, type, image, price, user_id, local_pickup, shipping_available, shipping_cost, quantity, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1, 1, 15.00, 1, 1)
        """, (listing['title'], listing['description'], listing['type'], listing['image'], listing['price'], user_id))
        post_id = c.lastrowid
    else:
        c.execute("""
            INSERT INTO posts (title, description, type, image, price, user_id, quantity, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1, 1)
        """, (listing['title'], listing['description'], listing['type'], listing['image'], listing['price'], user_id))
        post_id = c.lastrowid
    
    # Add category if exists
    if category_id:
        c.execute("INSERT OR IGNORE INTO posts_categories (post_id, category_id) VALUES (?, ?)", (post_id, category_id))
    
    print(f"Added: {listing['title']}")

conn.commit()
conn.close()
print("\nDemo listings added successfully!")
