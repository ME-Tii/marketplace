#!/usr/bin/env python3
"""
Initialize database with seed data.
Run this script once to populate the database with demo data.
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'database.db')

def init_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    print("Checking database tables...")
    
    # Check if users table exists
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not c.fetchone():
        print("Database not initialized. Please run the app first to create tables.")
        return
    
    # Check if posts already exist
    c.execute("SELECT COUNT(*) FROM posts")
    post_count = c.fetchone()[0]
    
    if post_count > 0:
        print(f"Database already has {post_count} posts. Skipping seed data.")
        conn.close()
        return
    
    print("Adding seed data...")
    
    # Get user IDs
    c.execute("SELECT id FROM users WHERE username = 'admin'")
    admin = c.fetchone()
    c.execute("SELECT id FROM users WHERE username = 'user1'")
    user1 = c.fetchone()
    c.execute("SELECT id FROM users WHERE username = 'user2'")
    user2 = c.fetchone()
    c.execute("SELECT id FROM users WHERE username = 'sam'")
    sam = c.fetchone()
    
    if not all([admin, user1, user2]):
        print("Required users not found. Skipping seed data.")
        conn.close()
        return
    
    admin_id, user1_id, user2_id, sam_id = admin[0], user1[0], user2[0], sam[0]
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Demo posts with real images
    demo_posts = [
        # Admin posts
        (admin_id, 'DJ Equipment Set', 'Professional DJ equipment set including mixer, turntables, and speakers. Perfect for parties and events.', 'sell', '/static/pictures/placeholder.png', 850.00, 1, 1, 15.00, timestamp),
        (admin_id, 'Sony WH-1000XM4 Headphones', 'Best noise-canceling headphones. Used for 6 months. Comes with case and cables. Black color.', 'sell', '/static/pictures/headphones.jpg', 180.00, 1, 1, 15.00, timestamp),
        (admin_id, 'Nintendo Switch OLED', 'Selling my Switch OLED, comes with dock, joycons, and 3 games (Zelda, Mario Kart, Smash). All in original boxes.', 'sell', '/static/pictures/switch.jpg', 280.00, 1, 1, 15.00, timestamp),
        (admin_id, 'Vintage Vinyl Records Collection', 'About 50 records from the 70s-90s. Rock, jazz, and classical. Selling as a lot only.', 'sell', '/static/pictures/vinyl.jpg', 150.00, 1, 1, 15.00, timestamp),
        (admin_id, 'Roomba i7+ Robot Vacuum', 'Cleans itself! Includes auto-empty base. Works great, just upgraded to newer model. All accessories included.', 'sell', '/static/pictures/roomba.jpg', 300.00, 1, 1, 15.00, timestamp),
        (admin_id, 'Mountain Bike - Trek Marlin 7', '2022 model, size L. Perfect for trails and commuting. Recent tune-up, new brakes. Great condition!', 'sell', '/static/pictures/bike.jpg', 600.00, 1, 1, 15.00, timestamp),
        
        # User 1 posts
        (user1_id, 'MacBook Pro 2021 14" M1 Pro', 'Excellent condition, barely used. Includes charger and original box. Perfect for students and professionals. Battery health at 95%.', 'sell', '/static/pictures/macbook.jpg', 1200.00, 1, 1, 15.00, timestamp),
        (user1_id, 'Nike Air Max 270 - Size 10', 'Brand new, never worn. Bought wrong size. Original price $150, selling for $90.', 'sell', '/static/pictures/sneakers.jpg', 90.00, 1, 1, 15.00, timestamp),
        (user1_id, 'FREE: Moving - Take My Couch', 'Must pick up by this weekend. Gray fabric couch, 3 seater. Some wear but very comfortable. You haul!', 'giveaway', '/static/pictures/couch.jpg', 0.00, 1, 1, 0.00, timestamp),
        (user1_id, 'Trading: PS5 for Xbox Series X', 'Looking to trade my PS5 (with 2 controllers) for an Xbox Series X. Both in great condition.', 'trade', '/static/pictures/ps5.jpg', 0.00, 1, 1, 15.00, timestamp),
        (user1_id, 'Textbooks: Computer Science', 'Selling 5 CS textbooks - algorithms, databases, web development. All in good condition. Make an offer!', 'sell', '/static/pictures/books.jpg', 50.00, 1, 1, 10.00, timestamp),
        
        # User 2 / Sam posts
        (user2_id, 'IKEA MALM Desk - White', 'Barely used MALM desk with pull-out panel. Some minor scratches but overall great condition. Pickup only.', 'sell', '/static/pictures/desk.jpg', 80.00, 1, 1, 15.00, timestamp),
        (user2_id, 'Looking for: Gaming Monitor 27"', 'Looking for a 27 inch gaming monitor, 144Hz or higher. Budget around $200. Can pick up locally.', 'buy', '/static/pictures/monitor.jpg', 200.00, 1, 1, 15.00, timestamp),
        (user2_id, 'iPhone 14 Pro Max 256GB', 'Space Black, excellent condition with case and screen protector since day 1. Includes original box and charger.', 'sell', '/static/pictures/iphone.jpg', 850.00, 1, 1, 15.00, timestamp),
        (user2_id, 'KitchenAid Stand Mixer', 'Artisan series, red color. Used only a few times, like new. Includes all original attachments.', 'sell', '/static/pictures/mixer.jpg', 250.00, 1, 1, 15.00, timestamp),
        (user2_id, 'Samsung 55" 4K Smart TV', 'Used for 2 years, still works perfectly. Includes remote and wall mount bracket. Great for gaming!', 'sell', '/static/pictures/tv.jpg', 350.00, 1, 1, 20.00, timestamp),
    ]
    
    for post in demo_posts:
        c.execute('''
            INSERT INTO posts (user_id, title, description, type, image, price, local_pickup, shipping_available, shipping_cost, timestamp, quantity, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
        ''', post)
    
    print(f"Added {len(demo_posts)} demo posts")
    
    conn.commit()
    conn.close()
    print("Seed data complete!")

if __name__ == '__main__':
    init_database()
