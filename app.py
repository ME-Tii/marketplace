from flask import Flask, request, redirect, url_for, render_template, session, flash, send_from_directory, Response, g
import sqlite3
import os
import logging
import mimetypes
import secrets
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect
from flask_talisman import Talisman
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import requests
import io
import base64
import stripe
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key_change_this')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['STRIPE_PUBLIC_KEY'] = os.environ.get('STRIPE_PUBLIC_KEY', 'pk_test_51T8PWW8gWUxTvhfMrWiSGibJDmrQslPZlxNN25Gpxup3pBVQoBg50DGh3pIGbXfJdIhfyzJ1G9bMraRfcIraBjSL00wJ9BQESt')
app.config['STRIPE_SECRET_KEY'] = os.environ.get('STRIPE_SECRET_KEY', '')
app.config['STRIPE_CONNECT_CLIENT_ID'] = os.environ.get('STRIPE_CONNECT_CLIENT_ID', '')
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', 'thomasseitz22@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['ADMIN_EMAIL'] = 'thomasseitz22@gmail.com'
app.config['DEFAULT_FROM_EMAIL'] = 'thomasseitz22@gmail.com'
stripe.api_key = app.config['STRIPE_SECRET_KEY']
csrf = CSRFProtect(app)
if os.environ.get('FLASK_ENV') == 'production':
    Talisman(app, content_security_policy=None)  # Basic security headers only in production
else:
    # For local development, skip Talisman to avoid HTTPS redirects
    pass

@app.route('/webhook/stripe', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('stripe-signature')
    
    if not app.config['STRIPE_SECRET_KEY'] or not sig_header:
        return '', 400
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, app.config.get('STRIPE_WEBHOOK_SECRET', '')
        )
    except ValueError:
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError:
        return 'Invalid signature', 400
    
    if event['type'] == 'checkout.session.completed':
        session_obj = event['data']['object']
        order_id = session_obj.get('metadata', {}).get('order_id')
        payment_id = session_obj.get('payment_intent')
        
        if order_id:
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute("UPDATE orders SET status = 'paid', stripe_payment_id = ? WHERE id = ?",
                     (payment_id, order_id))
            c.execute("""SELECT o.buyer_id, o.seller_id, o.amount, p.title, buyer.email, seller.email, 
                         COALESCE(buyer.email_notifications, 1), COALESCE(buyer.notify_order, 1),
                         COALESCE(seller.email_notifications, 1), COALESCE(seller.notify_order, 1)
                         FROM orders o
                         JOIN posts p ON o.post_id = p.id
                         JOIN users buyer ON o.buyer_id = buyer.id
                         JOIN users seller ON o.seller_id = seller.id
                         WHERE o.id = ?""", (order_id,))
            order_info = c.fetchone()
            if order_info:
                buyer_email = order_info[4]
                seller_email = order_info[5]
                buyer_email_notif = order_info[6]
                buyer_notify = order_info[7]
                seller_email_notif = order_info[8]
                seller_notify = order_info[9]
                post_title = order_info[3]
                amount = order_info[2]
                
                if buyer_email_notif and buyer_notify:
                    send_email(buyer_email, 'Payment Confirmed - Marketplace', 
                              f'Your payment of ${amount:.2f} for "{post_title}" has been confirmed. The seller will ship your order soon.')
                if seller_email_notif and seller_notify:
                    send_email(seller_email, 'New Order - Marketplace', 
                              f'You have a new order for "{post_title}". Payment of ${amount:.2f} received. Please ship the item.')
            conn.commit()
            conn.close()
    
    return '', 200

@app.route('/cron/check-orders', methods=['GET'])
def check_unshipped_orders():
    cron_key = os.environ.get('CRON_SECRET_KEY')
    if cron_key and request.args.get('key') != cron_key:
        return 'Unauthorized', 401
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    c.execute("""SELECT o.id, o.created_at, o.amount, p.title, seller.username, seller.email, 
                 seller.email_notifications, seller.notify_order, o.reminder_count, 
                 o.warning_sent_at, o.cancelled_at, o.stripe_payment_id, o.refund_attempts, o.tracking_number, o.shipping_method
                 FROM orders o
                 JOIN posts p ON o.post_id = p.id
                 JOIN users seller ON o.seller_id = seller.id
                 WHERE o.status = 'paid' AND o.tracking_number IS NULL AND o.shipping_method != 'local_pickup'
                 ORDER BY o.created_at""")
    orders = c.fetchall()
    
    processed = 0
    errors = []
    
    for order in orders:
        order_id = order[0]
        created_at = order[1]
        amount = order[2]
        item_title = order[3]
        seller_username = order[4]
        seller_email = order[5]
        seller_email_notif = order[6]
        seller_notify = order[7]
        reminder_count = order[8]
        warning_sent_at = order[9]
        cancelled_at = order[10]
        stripe_payment_id = order[11]
        refund_attempts = order[12]
        
        days_since_payment = (datetime.now() - datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S.%f')).days if created_at else 0
        
        if days_since_payment >= 7 and not cancelled_at:
            c.execute("UPDATE orders SET status = 'auto_cancelled', cancelled_at = CURRENT_TIMESTAMP WHERE id = ?", (order_id,))
            conn.commit()
            
            if seller_email_notif and seller_notify:
                send_email(seller_email, 'Order Auto-Cancelled - Marketplace',
                          f'Dear {seller_username}, order #{order_id} for "{item_title}" has been auto-cancelled due to no shipping activity within 7 days.\n\nA full refund of ${amount:.2f} will be processed for the buyer.')
            
            app.logger.info(f"Order #{order_id} auto-cancelled")
            processed += 1
            
        elif days_since_payment >= 8 and cancelled_at and not stripe_payment_id is None:
            item_price = amount
            try:
                if stripe_payment_id and app.config.get('STRIPE_SECRET_KEY'):
                    stripe.Refund.create(payment_intent=stripe_payment_id, amount=int(item_price * 100))
                    
                    c.execute("UPDATE orders SET status = 'refunded' WHERE id = ?", (order_id,))
                    conn.commit()
                    
                    c.execute("""SELECT buyer.email, buyer.email_notifications FROM orders o 
                                 JOIN users buyer ON o.buyer_id = buyer.id WHERE o.id = ?""", (order_id,))
                    buyer_info = c.fetchone()
                    if buyer_info and buyer_info[1]:
                        send_email(buyer_info[0], 'Refund Processed - Marketplace',
                                  f'Your refund for order #{order_id} has been processed. ${item_price:.2f} has been refunded to your original payment method.\n\nAllow 5-10 business days for the refund to appear.')
                    
                    app.logger.info(f"Order #{order_id} auto-refunded ${item_price:.2f}")
                    processed += 1
                    
            except Exception as e:
                new_attempts = (refund_attempts or 0) + 1
                c.execute("UPDATE orders SET refund_attempts = ? WHERE id = ?", (new_attempts, order_id))
                conn.commit()
                
                if new_attempts >= 2:
                    send_email(app.config['ADMIN_EMAIL'], 'Auto-Refund Failed - Marketplace',
                              f'Admin, the auto-refund for order #{order_id} failed after {new_attempts} attempts.\n\nAmount: ${item_price:.2f}\nStripe Payment ID: {stripe_payment_id}\n\nError: {str(e)}\n\nPlease investigate and process manually.')
                
                app.logger.error(f"Order #{order_id} refund failed: {str(e)}")
                errors.append(f"Order #{order_id}: {str(e)}")
                
        elif days_since_payment >= 8 and cancelled_at and stripe_payment_id is None:
            item_price = amount
            c.execute("UPDATE orders SET status = 'refunded' WHERE id = ?", (order_id,))
            conn.commit()
            
            c.execute("""SELECT buyer.email, buyer.email_notifications FROM orders o 
                         JOIN users buyer ON o.buyer_id = buyer.id WHERE o.id = ?""", (order_id,))
            buyer_info = c.fetchone()
            if buyer_info and buyer_info[1]:
                send_email(buyer_info[0], 'Order Cancelled - Marketplace',
                          f'Your order #{order_id} for "{item_title}" has been cancelled and refunded.\n\n${item_price:.2f} will be returned to your original payment method.\n\nAllow 5-10 business days for the refund to appear.')
            
            app.logger.info(f"Order #{order_id} marked as refunded (no Stripe payment)")
            processed += 1
            
        elif days_since_payment >= 6 and not warning_sent_at and not cancelled_at:
            c.execute("UPDATE orders SET warning_sent_at = CURRENT_TIMESTAMP WHERE id = ?", (order_id,))
            conn.commit()
            
            if seller_email_notif and seller_notify:
                send_email(seller_email, 'Final Warning: Order Will Be Cancelled - Marketplace',
                          f'Dear {seller_username}, your order #{order_id} for "{item_title}" has not been shipped.\n\nThis order will be AUTO-CANCELLED in 24 hours and the buyer will receive a full refund.\n\nPlease ship immediately or contact us if you need assistance.')
            
            app.logger.info(f"Final warning sent for order #{order_id}")
            processed += 1
            
        elif days_since_payment >= 3 and reminder_count < 3 and not cancelled_at:
            days_remaining = 7 - days_since_payment
            c.execute("UPDATE orders SET reminder_count = reminder_count + 1 WHERE id = ?", (order_id,))
            conn.commit()
            
            if seller_email_notif and seller_notify:
                send_email(seller_email, 'Reminder: Unshipped Order - Marketplace',
                          f'Dear {seller_username}, you have an unshipped order for "{item_title}".\n\nPlease ship within {days_remaining} days to avoid cancellation.\n\nOrder #{order_id} - ${amount:.2f}')
            
            app.logger.info(f"Reminder {reminder_count + 1} sent for order #{order_id}")
            processed += 1
    
    conn.close()
    
    result = f"Processed {processed} orders"
    if errors:
        result += f", {len(errors)} errors"
    app.logger.info(result)
    
    return result, 200

@app.route('/cron/expire-featured', methods=['GET'])
def expire_featured():
    cron_key = os.environ.get('CRON_SECRET_KEY')
    if cron_key and request.args.get('key') != cron_key:
        return 'Unauthorized', 401
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    c.execute("""UPDATE posts SET is_featured = 0 
                 WHERE is_featured = 1 
                 AND featured_until IS NOT NULL 
                 AND datetime(featured_until) < datetime('now')""")
    
    expired_count = c.rowcount
    conn.commit()
    conn.close()
    
    return f"Expired {expired_count} featured listings", 200

@app.route('/cron/check-local-pickup', methods=['GET'])
def check_local_pickup_orders():
    cron_key = os.environ.get('CRON_SECRET_KEY')
    if cron_key and request.args.get('key') != cron_key:
        return 'Unauthorized', 401
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    c.execute("""SELECT o.id, o.created_at, o.amount, p.title, o.buyer_id, o.seller_id,
                 buyer.username, buyer.email, buyer.email_notifications,
                 seller.username, seller.email, seller.email_notifications, seller.notify_order
                 FROM orders o
                 JOIN posts p ON o.post_id = p.id
                 JOIN users buyer ON o.buyer_id = buyer.id
                 JOIN users seller ON o.seller_id = seller.id
                 WHERE o.status = 'paid' AND o.shipping_method = 'local_pickup'
                 ORDER BY o.created_at""")
    orders = c.fetchall()
    
    processed = 0
    
    for order in orders:
        order_id = order[0]
        created_at = order[1]
        amount = order[2]
        item_title = order[3]
        buyer_id = order[4]
        seller_username = order[6]
        seller_email = order[8]
        seller_notify = order[12]
        
        days_since_payment = (datetime.now() - datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S.%f')).days if created_at else 0
        
        # After 7 days with no pickup, notify seller and allow buyer to cancel
        if days_since_payment >= 7:
            c.execute("""UPDATE orders SET reminder_count = reminder_count + 1 WHERE id = ? AND reminder_count < 100""", (order_id,))
            conn.commit()
            
            # Notify seller
            if seller_email and seller_notify:
                send_email(seller_email, 'Urgent: Local Pickup Required - Marketplace',
                          f'Dear {seller_username}, the buyer for order #{order_id} ("{item_title}") has not picked up the item.\n\nPlease contact the buyer to arrange pickup or contact support.\n\nIf no action is taken, the order will be auto-cancelled and refunded.')
            
            processed += 1
        
        # After 7 days, auto-cancel and refund
        if days_since_payment >= 7:
            c.execute("""SELECT stripe_payment_id FROM orders WHERE id = ? AND status = 'paid'""", (order_id,))
            stripe_info = c.fetchone()
            
            if stripe_info and stripe_info[0]:
                try:
                    stripe.Refund.create(payment_intent=stripe_info[0], amount=int(amount * 100))
                    c.execute("UPDATE orders SET status = 'refunded', cancelled_at = CURRENT_TIMESTAMP WHERE id = ?", (order_id,))
                    conn.commit()
                    
                    send_email(order[7], 'Order Auto-Refunded - Marketplace',
                              f'Your order #{order_id} for "{item_title}" has been auto-cancelled and refunded.\n\n${amount:.2f} will be returned to your original payment method.\n\nThe seller did not arrange pickup within 14 days.')
                    
                except Exception as e:
                    app.logger.error(f"Local pickup refund failed for order #{order_id}: {str(e)}")
            else:
                c.execute("UPDATE orders SET status = 'refunded', cancelled_at = CURRENT_TIMESTAMP WHERE id = ?", (order_id,))
                conn.commit()
            
            processed += 1
    
    conn.close()
    return f"Processed {processed} local pickup orders", 200

@app.before_request
def inject_user_alerts():
    if 'user_id' not in session:
        return
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # Check for open disputes (as buyer or seller)
    c.execute("SELECT COUNT(*) FROM orders WHERE (buyer_id = ? OR seller_id = ?) AND dispute_status = 'open'", 
              (session['user_id'], session['user_id']))
    open_disputes = c.fetchone()[0]
    
    # Check for reports on user's posts
    c.execute("SELECT COUNT(*) FROM reports r JOIN posts p ON r.post_id = p.id WHERE p.user_id = ?", 
              (session['user_id'],))
    post_reports = c.fetchone()[0]
    
    conn.close()
    
    g.open_disputes = open_disputes
    g.post_reports = post_reports

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}

def send_email(to_email, subject, body, html_body=None):
    app.logger.info(f"Attempting to send email to {to_email}")
    
    if not to_email:
        app.logger.warning(f"No recipient email provided for: {subject}")
        return False
    
    try:
        message = Mail(
            from_email=app.config.get('DEFAULT_FROM_EMAIL', 'ME-Tii Marketplace <noreply@me-tii.com>'),
            to_emails=to_email,
            subject=subject,
            html_content=html_body or body)
        
        sg = SendGridAPIClient(app.config.get('MAIL_PASSWORD'))
        response = sg.send(message)
        
        app.logger.info(f"Email sent to {to_email}: {subject} (status: {response.status_code})")
        return True
    except Exception as e:
        app.logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return False

def get_user_notification_prefs(user_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT COALESCE(email_notifications, 1), COALESCE(notify_order, 1), COALESCE(notify_dispute, 1), COALESCE(notify_return, 1), COALESCE(notify_message, 1) FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            'email_notifications': row[0],
            'notify_order': row[1],
            'notify_dispute': row[2],
            'notify_return': row[3],
            'notify_message': row[4]
        }
    return {
        'email_notifications': 1,
        'notify_order': 1,
        'notify_dispute': 1,
        'notify_return': 1,
        'notify_message': 1
    }

def get_unread_messages_count(user_id):
    if not user_id:
        return 0
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND is_read = 0", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                  (id INTEGER PRIMARY KEY, username TEXT UNIQUE, email TEXT UNIQUE, password TEXT)''')
    try:
        c.execute("ALTER TABLE users ADD COLUMN description TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        c.execute("ALTER TABLE users ADD COLUMN profile_picture TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        c.execute("ALTER TABLE users ADD COLUMN stripe_account_id TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        c.execute("ALTER TABLE users ADD COLUMN email_notifications INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        c.execute("ALTER TABLE users ADD COLUMN notify_order INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN notify_dispute INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN notify_return INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN notify_message INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN return_address TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN verification_token TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN verification_sent_at DATETIME")
    except sqlite3.OperationalError:
        pass
    c.execute("INSERT OR IGNORE INTO users (username, email, password) VALUES (?, ?, ?)", ('admin', 'admin@example.com', generate_password_hash('admin123')))
    c.execute('''CREATE TABLE IF NOT EXISTS posts
                 (id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, description TEXT, type TEXT, image TEXT, links TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    try:
        c.execute("ALTER TABLE posts ADD COLUMN price REAL")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        c.execute("ALTER TABLE posts ADD COLUMN shipping_available INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE posts ADD COLUMN local_pickup INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE posts ADD COLUMN shipping_cost REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE posts ADD COLUMN quantity INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE posts ADD COLUMN is_active INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE posts ADD COLUMN is_featured INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE posts ADD COLUMN featured_until DATETIME")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE posts ADD COLUMN featured_payment_id TEXT")
    except sqlite3.OperationalError:
        pass
    # Set default values for existing posts
    try:
        c.execute("UPDATE posts SET quantity = 1 WHERE quantity IS NULL")
    except:
        pass
    try:
        c.execute("UPDATE posts SET is_active = 1 WHERE is_active IS NULL")
    except:
        pass
    try:
        c.execute("UPDATE posts SET local_pickup = 1 WHERE local_pickup IS NULL")
    except:
        pass
    try:
        c.execute("UPDATE posts SET shipping_available = 0 WHERE shipping_available IS NULL")
    except:
        pass
    try:
        c.execute("UPDATE posts SET shipping_cost = 0 WHERE shipping_cost IS NULL")
    except:
        pass
    conn.commit()
    c.execute('''CREATE TABLE IF NOT EXISTS notices
                   (user_id INTEGER, post_id INTEGER, PRIMARY KEY (user_id, post_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS noticed_users
                   (user_id INTEGER, noticed_user_id INTEGER, PRIMARY KEY (user_id, noticed_user_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                   (id INTEGER PRIMARY KEY, sender_id INTEGER, receiver_id INTEGER, message TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    try:
        c.execute("ALTER TABLE messages ADD COLUMN attachment TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        c.execute("ALTER TABLE messages ADD COLUMN is_read BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    c.execute('''CREATE TABLE IF NOT EXISTS reports
                    (id INTEGER PRIMARY KEY, post_id INTEGER, reporter_id INTEGER, reason TEXT, description TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS ratings
                    (id INTEGER PRIMARY KEY, order_id INTEGER UNIQUE NOT NULL, seller_id INTEGER NOT NULL, buyer_id INTEGER NOT NULL, rating INTEGER NOT NULL, review TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (order_id) REFERENCES orders(id), FOREIGN KEY (seller_id) REFERENCES users(id), FOREIGN KEY (buyer_id) REFERENCES users(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS groups
                    (id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT, creator_id INTEGER NOT NULL, is_private BOOLEAN DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (creator_id) REFERENCES users(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS group_members
                    (id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL, user_id INTEGER NOT NULL, status TEXT DEFAULT 'pending', joined_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (group_id) REFERENCES groups(id), FOREIGN KEY (user_id) REFERENCES users(id), UNIQUE(group_id, user_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS group_posts
                    (id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL, user_id INTEGER NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL, type TEXT, image TEXT, links TEXT, price REAL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (group_id) REFERENCES groups(id), FOREIGN KEY (user_id) REFERENCES users(id))''')
    # Add new columns if not exist
    try:
        c.execute("ALTER TABLE group_posts ADD COLUMN type TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE group_posts ADD COLUMN links TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE group_posts ADD COLUMN price REAL")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE group_posts ADD COLUMN local_pickup INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE group_posts ADD COLUMN shipping_available INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE group_posts ADD COLUMN shipping_cost REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # Orders table
    c.execute('''CREATE TABLE IF NOT EXISTS orders
                 (id INTEGER PRIMARY KEY, post_id INTEGER, buyer_id INTEGER, seller_id INTEGER,
                  amount REAL, status TEXT DEFAULT 'pending', stripe_payment_id TEXT,
                  tracking_number TEXT, shipped_at DATETIME, delivered_at DATETIME,
                  dispute_status TEXT DEFAULT NULL,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    try:
        c.execute("ALTER TABLE orders ADD COLUMN tracking_number TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN shipped_at DATETIME")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN delivered_at DATETIME")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN shipping_method TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN dispute_status TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN dispute_reason TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN dispute_response TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN dispute_opened_at DATETIME")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN dispute_resolved_at DATETIME")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN dispute_resolution TEXT")
    except sqlite3.OperationalError:
        pass
    # Return fields
    try:
        c.execute("ALTER TABLE orders ADD COLUMN return_status TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN return_reason TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN return_response TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN return_tracking_number TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN return_requested_at DATETIME")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN return_shipped_at DATETIME")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN return_completed_at DATETIME")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN shipping_cost REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN return_shipping_covered INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN seller_at_fault INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # Auto-cancel fields
    try:
        c.execute("ALTER TABLE orders ADD COLUMN reminder_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN warning_sent_at DATETIME")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN cancelled_at DATETIME")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN refund_attempts INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN transaction_fee REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # Shipping addresses
    c.execute('''CREATE TABLE IF NOT EXISTS addresses
                 (id INTEGER PRIMARY KEY, user_id INTEGER, order_id INTEGER,
                  full_name TEXT, street TEXT, city TEXT, state TEXT, zip_code TEXT, country TEXT, phone TEXT)''')
    # Add sample posts if none exist
    c.execute("SELECT COUNT(*) FROM posts")
    if c.fetchone()[0] == 0:
        sample_posts = [
            (1, 'Laptop for Sale', 'Selling a used laptop in good condition.', 'sell', None, None, 500.0),
            (1, 'Buy Old Books', 'Looking to buy old books, any genre.', 'buy', None, None, None),
            (1, 'Community Event Notice', 'Join us for the community picnic next weekend.', 'notification', None, 'https://example.com/event', None),
            (1, 'Smartphone Cheap', 'Discounted smartphone, barely used.', 'sell', None, None, 200.0),
            (1, 'Need Carpenter Help', 'Looking for carpenter to fix my shelf.', 'buy', None, None, None),
            (1, 'Weather Alert', 'Heavy rain expected, stay indoors.', 'notification', None, None, None),
            (1, 'Bicycle for Sale', 'Mountain bike, excellent condition.', 'sell', None, None, 150.0),
            (1, 'Tutoring Services', 'Offering math tutoring for students.', 'sell', None, None, 20.0),
            (1, 'Lost Pet Notice', 'Lost cat, please contact if found.', 'notification', None, None, None),
            (1, 'Furniture Sale', 'Selling dining table and chairs.', 'sell', None, None, 300.0),
            (1, 'Trade Guitar for Drums', 'Looking to trade my guitar for a drum set.', 'trade', None, None, None),
        ]
        c.executemany("INSERT INTO posts (user_id, title, description, type, image, links, price) VALUES (?, ?, ?, ?, ?, ?, ?)", sample_posts)
    conn.commit()
    conn.close()

init_db()

@app.context_processor
def inject_user():
    user_id = session.get('user_id')
    if user_id:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE id = ?", (user_id,))
        user = c.fetchone()
        conn.close()
        if user:
            session['username'] = user[0]  # cache in session
            return {'current_username': user[0]}
    return {'current_username': None}


@app.route('/fix_notifications')
def fix_notifications():
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("UPDATE users SET email_notifications = 1 WHERE email_notifications IS NULL")
    c.execute("UPDATE users SET notify_order = 1 WHERE notify_order IS NULL")
    c.execute("UPDATE users SET notify_dispute = 1 WHERE notify_dispute IS NULL")
    c.execute("UPDATE users SET notify_return = 1 WHERE notify_return IS NULL")
    c.execute("UPDATE users SET notify_message = 1 WHERE notify_message IS NULL")
    conn.commit()
    rows = c.rowcount
    conn.close()
    return f'Fixed notification preferences for {rows} users'

@app.route('/test_email')
def test_email():
    if 'user_id' not in session:
        return redirect('/login')
    
    username = session.get('username') or 'admin'
    
    # Get email from database
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT email FROM users WHERE id = ?", (session['user_id'],))
    user = c.fetchone()
    conn.close()
    
    user_email = user[0] if user else None
    
    if not user_email:
        flash('No email address on your account.', 'danger')
        return redirect('/profile/' + username)
    
    success = send_email(user_email, 'Test Email - Marketplace', 
                        'This is a test email from ME-Tii Marketplace.')
    
    if success:
        flash(f'Test email sent to {user_email}!', 'success')
    else:
        flash('Failed to send test email. Check Render logs.', 'danger')
    
    return redirect('/profile/' + username)

@app.route('/update_admin_email')
def update_admin_email():
    if 'user_id' not in session:
        return redirect('/login')
    
    # Only allow admin to update
    if session.get('username') != 'admin':
        return 'Access denied', 403
    
    new_email = request.args.get('email')
    if not new_email:
        return 'Email parameter required', 400
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("UPDATE users SET email = ? WHERE username = 'admin'", (new_email,))
    conn.commit()
    conn.close()
    
    return f'Admin email updated to {new_email}'

@app.route('/terms')
def terms():
    return render_template('terms.html', unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/privacy')
def privacy():
    return render_template('privacy.html', unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/refund-policy')
def refund_policy():
    return render_template('refund_policy.html', unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/dispute-policy')
def dispute_policy():
    return render_template('dispute_policy.html', unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/shipping-policy')
def shipping_policy():
    return render_template('shipping_policy.html', unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/cookie-policy')
def cookie_policy():
    return render_template('cookie_policy.html', unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/connect/stripe')
def connect_stripe():
    if 'user_id' not in session:
        return redirect('/login')
    
    user_id = session['user_id']
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT stripe_account_id FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    
    if user and user[0]:
        flash('Stripe account already connected', 'info')
        return redirect('/profile')
    
    if not app.config['STRIPE_CONNECT_CLIENT_ID']:
        flash('Stripe Connect is not configured. Please contact the administrator.', 'danger')
        return redirect('/profile')
    
    redirect_uri = request.url_root + 'connect/stripe/callback'
    if request.is_secure or request.headers.get('X-Forwarded-Proto') == 'https':
        redirect_uri = redirect_uri.replace('http://', 'https://')
    
    stripe_auth_url = f"https://connect.stripe.com/oauth/authorize?response_type=code&client_id={app.config['STRIPE_CONNECT_CLIENT_ID']}&scope=read_write&redirect_uri={redirect_uri}"
    return redirect(stripe_auth_url)

@app.route('/connect/stripe/callback')
def connect_stripe_callback():
    if 'user_id' not in session:
        return redirect('/login')
    
    error = request.args.get('error')
    if error:
        flash(f'Stripe connection failed: {error}', 'danger')
        return redirect('/profile')
    
    code = request.args.get('code')
    if not code:
        flash('No authorization code received', 'danger')
        return redirect('/profile')
    
    try:
        response = stripe.OAuth.token(
            grant_type='authorization_code',
            code=code
        )
        stripe_account_id = response['stripe_user_id']
        
        user_id = session['user_id']
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("UPDATE users SET stripe_account_id = ? WHERE id = ?", (stripe_account_id, user_id))
        conn.commit()
        conn.close()
        
        flash('Stripe account connected successfully!', 'success')
    except Exception as e:
        flash(f'Failed to connect Stripe account: {str(e)}', 'danger')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id = ?", (session.get('user_id'),))
    user = c.fetchone()
    conn.close()
    return redirect(f'/profile/{user[0]}')

@app.route('/disconnect/stripe')
def disconnect_stripe():
    if 'user_id' not in session:
        return redirect('/login')
    
    user_id = session['user_id']
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("UPDATE users SET stripe_account_id = NULL WHERE id = ?", (user_id,))
    conn.commit()
    c.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    
    flash('Stripe account disconnected', 'info')
    return redirect(f'/profile/{user[0]}')


@app.route('/login')
def login_page():
    app.logger.info("Login page accessed")
    error = request.args.get('error')
    try:
        return render_template('login.html', error=error, unread_messages=get_unread_messages_count(session.get('user_id')))
    except Exception as e:
        app.logger.error(f"Error rendering login.html: {str(e)}")
        return f"Template error: {str(e)}", 500

@app.route('/register')
def register_page():
    app.logger.info("Register page accessed")
    try:
        return render_template('register.html', unread_messages=get_unread_messages_count(session.get('user_id')))
    except Exception as e:
        app.logger.error(f"Error rendering register.html: {str(e)}")
        return f"Template error: {str(e)}", 500

@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    confirm = request.form.get('confirm_password')
    terms = request.form.get('terms')
    description = request.form.get('description') or ''
    if not all([username, email, password, confirm]) or not terms:
        return 'All fields required', 400
    if password != confirm:
        return 'Passwords do not match', 400
    hashed = generate_password_hash(password)
    
    verification_token = secrets.token_urlsafe(32)
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, email, password, description, verification_token) VALUES (?, ?, ?, ?, ?)", 
                  (username, email, hashed, description, verification_token))
        conn.commit()
        
        base_url = os.environ.get('BASE_URL', request.url_root.rstrip('/'))
        verify_url = f"{base_url}/verify-email/{verification_token}"
        
        email_subject = 'Verify your email - Marketplace'
        email_body = f"""Welcome to Marketplace, {username}!

Thank you for registering. Please verify your email address by clicking the link below:

{verify_url}

This link will expire in 24 hours.

If you did not create an account, please ignore this email.

Best regards,
Marketplace Team"""
        
        send_email(email, email_subject, email_body)
        
        return redirect('/login?registered=1')
    except sqlite3.IntegrityError:
        return 'Username or email already exists', 400
    finally:
        conn.close()

@app.route('/login', methods=['POST'])
def login():
    app.logger.info("Login attempt")
    identifier = request.form.get('email')
    password = request.form.get('password')
    if not all([identifier, password]):
        app.logger.warning("Missing identifier or password")
        return 'Email/Username and password required', 400
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    if '@' in identifier:
        c.execute("SELECT id, password, username, email_verified FROM users WHERE email = ?", (identifier,))
    else:
        c.execute("SELECT id, password, username, email_verified FROM users WHERE username = ?", (identifier,))
    user = c.fetchone()
    conn.close()
    if user:
        app.logger.info(f"User found: {user[2]}, checking password")
        if check_password_hash(user[1], password):
            if not user[3] and user[2] not in ('admin', 'user1'):
                return redirect('/login?error=Email not verified. Please check your email for the verification link.')
            session['user_id'] = user[0]
            session['username'] = user[2]
            app.logger.info(f"Login successful for {user[2]}")
            return redirect('/dashboard')
        else:
            app.logger.warning(f"Invalid password for {user[2]}")
    else:
        app.logger.warning(f"User not found for identifier: {identifier}")
    return redirect('/login?error=Invalid credentials')

@app.route('/verify-email/<token>')
def verify_email(token):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, username, email, verification_sent_at FROM users WHERE verification_token = ? AND email_verified = 0", (token,))
    user = c.fetchone()
    
    if not user:
        conn.close()
        return render_template('message.html', 
                              title='Invalid Link' if session.get('lang') != 'de' else 'Ungültiger Link',
                              message='This verification link is invalid or has already been used.' if session.get('lang') != 'de' else 'Dieser Bestätigungslink ist ungültig oder wurde bereits verwendet.',
                              unread_messages=0)
    
    user_id, username, email, sent_at = user
    
    if sent_at:
        sent_time = datetime.strptime(sent_at, '%Y-%m-%d %H:%M:%S.%f')
        hours_elapsed = (datetime.now() - sent_time).total_seconds() / 3600
        if hours_elapsed > 24:
            conn.close()
            return render_template('message.html',
                                  title='Link Expired' if session.get('lang') != 'de' else 'Link abgelaufen',
                                  message='This verification link has expired. Please request a new one.' if session.get('lang') != 'de' else 'Dieser Bestätigungslink ist abgelaufen. Bitte fordern Sie einen neuen an.',
                                  unread_messages=0)
    
    c.execute("UPDATE users SET email_verified = 1, verification_token = NULL WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    return render_template('message.html',
                          title='Email Verified' if session.get('lang') != 'de' else 'E-Mail bestätigt',
                          message=f'Your email has been verified! You can now log in to your account.' if session.get('lang') != 'de' else f'Ihre E-Mail wurde bestätigt! Sie können sich jetzt in Ihrem Konto anmelden.',
                          unread_messages=0)

@app.route('/resend-verification', methods=['POST'])
def resend_verification():
    email = request.form.get('email')
    if not email:
        return redirect('/login?error=Email required')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, username, email_verified FROM users WHERE email = ?", (email,))
    user = c.fetchone()
    
    if not user:
        conn.close()
        return redirect('/login?error=Email not found')
    
    user_id, username, verified = user
    
    if verified:
        conn.close()
        return redirect('/login?info=Email already verified')
    
    new_token = secrets.token_urlsafe(32)
    c.execute("UPDATE users SET verification_token = ?, verification_sent_at = CURRENT_TIMESTAMP WHERE id = ?", (new_token, user_id))
    conn.commit()
    conn.close()
    
    base_url = os.environ.get('BASE_URL', request.url_root.rstrip('/'))
    verify_url = f"{base_url}/verify-email/{new_token}"
    
    email_subject = 'Verify your email - Marketplace'
    email_body = f"""Hello {username},

Please verify your email address by clicking the link below:

{verify_url}

This link will expire in 24 hours.

If you did not request this, please ignore this email.

Best regards,
Marketplace Team"""
    
    send_email(email, email_subject, email_body)
    
    return redirect('/login?info=Verification email sent. Please check your inbox.')

@app.route('/robots.txt')
def robots_txt():
    return send_from_directory('.', 'robots.txt')

@app.route('/sitemap.xml')
def sitemap():
    from flask import Response
    base_url = request.url_root.rstrip('/')
    urls = [
        {'loc': f'{base_url}/', 'lastmod': datetime.datetime.now().strftime('%Y-%m-%d'), 'changefreq': 'daily', 'priority': '1.0'},
        {'loc': f'{base_url}/groups', 'lastmod': datetime.datetime.now().strftime('%Y-%m-%d'), 'changefreq': 'weekly', 'priority': '0.8'},
    ]
    # Add dynamic URLs for posts, groups, profiles if needed
    # For now, static
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in urls:
        xml += f'  <url>\n    <loc>{url["loc"]}</loc>\n    <lastmod>{url["lastmod"]}</lastmod>\n    <changefreq>{url["changefreq"]}</changefreq>\n    <priority>{url["priority"]}</priority>\n  </url>\n'
    xml += '</urlset>'
    return Response(xml, mimetype='application/xml')

@app.route('/')
@app.route('/dashboard')
def dashboard():
    app.logger.info("Dashboard route called")
    query = request.args.get('q', '')
    type_filter = request.args.get('type', '')
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        base_query = "SELECT posts.id, posts.title, posts.description, posts.type, posts.image, posts.links, posts.price, posts.timestamp, users.username, posts.is_featured, posts.featured_until FROM posts JOIN users ON posts.user_id = users.id WHERE (posts.is_active = 1 OR posts.is_active IS NULL)"
        conditions = []
        params = []
        if query:
            conditions.append("(posts.title LIKE ? OR posts.description LIKE ? OR users.username LIKE ?)")
            params.extend(['%' + query + '%', '%' + query + '%', '%' + query + '%'])
        if type_filter:
            conditions.append("posts.type = ?")
            params.append(type_filter)
        if conditions:
            base_query += " AND " + " AND ".join(conditions)
        base_query += " ORDER BY posts.is_featured DESC, posts.timestamp DESC"
        c.execute(base_query, params)
        posts = c.fetchall()
        conn.close()
        app.logger.info(f"Dashboard loaded with {len(posts)} posts")
        return render_template('dashboard.html', posts=posts, query=query, type_filter=type_filter, unread_messages=get_unread_messages_count(session.get('user_id')))
    except Exception as e:
        app.logger.error(f"Error in dashboard: {str(e)}")
        return "Internal Server Error", 500

@app.route('/create_post_page')
def create_post_page():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('create_post.html', unread_messages=get_unread_messages_count(session['user_id']))

@app.route('/create_post', methods=['POST'])
def create_post():
    if 'user_id' not in session:
        return redirect('/login')
    title = request.form.get('title')
    description = request.form.get('description')
    post_type = request.form.get('type')
    links = request.form.get('links')
    price = request.form.get('price')
    local_pickup = 1 if request.form.get('local_pickup') else 0
    shipping_available = 1 if request.form.get('shipping_available') else 0
    shipping_cost = request.form.get('shipping_cost') or 0
    quantity = int(request.form.get('quantity') or 1)
    is_active = 1 if quantity > 0 else 0
    image_path = None
    if 'image' in request.files:
        file = request.files['image']
        if file.filename != '' and allowed_file(file.filename):
            mime = mimetypes.guess_type(file.filename)[0]
            if mime and mime.startswith('image/'):
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.root_path, 'static', 'pictures', filename)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                file.save(file_path)
                image_path = f'/static/pictures/{filename}'
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT INTO posts (user_id, title, description, type, image, links, price, local_pickup, shipping_available, shipping_cost, quantity, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
              (session['user_id'], title, description, post_type, image_path, links, price, local_pickup, shipping_available, shipping_cost, quantity, is_active))
    conn.commit()
    conn.close()
    return redirect('/dashboard')

@app.route('/profile/<username>')
def profile(username):
    query = request.args.get('q', '')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, description, profile_picture, stripe_account_id FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    if not user:
        conn.close()
        return 'User not found', 404
    user_id = user[0]
    description = user[1] or ''
    profile_picture = user[2] or None
    stripe_account_id = user[3] or None
    is_owner = session.get('user_id') == user_id
    
    # Get seller rating stats
    c.execute("SELECT COUNT(*), COALESCE(AVG(rating), 0) FROM ratings WHERE seller_id = ?", (user_id,))
    rating_stats = c.fetchone()
    total_ratings = rating_stats[0]
    avg_rating = round(rating_stats[1], 1) if rating_stats[1] else 0
    
    # Regular posts - show all to owner, only active to others
    if is_owner:
        posts_query = "SELECT posts.id, posts.title, posts.description, posts.type, posts.image, posts.links, posts.price, posts.timestamp, posts.quantity, posts.is_active, posts.is_featured, posts.featured_until, posts.local_pickup, posts.shipping_available FROM posts WHERE posts.user_id = ?"
    else:
        posts_query = "SELECT posts.id, posts.title, posts.description, posts.type, posts.image, posts.links, posts.price, posts.timestamp, posts.quantity, posts.is_active, posts.is_featured, posts.featured_until, posts.local_pickup, posts.shipping_available FROM posts WHERE posts.user_id = ? AND (posts.is_active = 1 OR posts.is_active IS NULL)"
    params = [user_id]
    if query:
        posts_query += " AND (posts.title LIKE ? OR posts.description LIKE ?)"
        params.extend(['%' + query + '%', '%' + query + '%'])
    posts_query += " ORDER BY posts.timestamp DESC"
    c.execute(posts_query, params)
    posts = c.fetchall()
    # Group posts - only show public groups or private groups where user is a member
    group_posts_query = """
        SELECT gp.id, gp.title, gp.content, gp.type, gp.image, gp.links, gp.price, gp.created_at, g.name, gp.user_id 
        FROM group_posts gp 
        JOIN groups g ON gp.group_id = g.id 
        LEFT JOIN group_members gm ON g.id = gm.group_id AND gm.user_id = ?
        WHERE gp.user_id = ? AND (g.is_private = 0 OR gm.status = 'accepted')
    """
    current_user_id = session.get('user_id')
    params = [current_user_id, user_id]
    if query:
        group_posts_query += " AND (gp.title LIKE ? OR gp.content LIKE ?)"
        params.extend(['%' + query + '%', '%' + query + '%'])
    group_posts_query += " ORDER BY gp.created_at DESC"
    c.execute(group_posts_query, params)
    group_posts = c.fetchall()
    is_noticed = False
    if 'user_id' in session and session['user_id'] != user_id:
        c.execute("SELECT 1 FROM noticed_users WHERE user_id = ? AND noticed_user_id = ?", (session['user_id'], user_id))
        is_noticed = c.fetchone() is not None
    # For admin, get all users with search and pagination
    all_users = []
    total_users = 0
    reports = []
    
    # Get notification preferences if owner
    notification_prefs = None
    if is_owner:
        notification_prefs = get_user_notification_prefs(user_id)
    
    search_term = request.args.get('search', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 5
    if username == 'admin' and session.get('user_id') == user_id:
        # Count total users
        count_query = "SELECT COUNT(*) FROM users"
        params = []
        if search_term:
            count_query += " WHERE username LIKE ? OR email LIKE ?"
            params.extend(['%' + search_term + '%', '%' + search_term + '%'])
        c.execute(count_query, params)
        total_users = c.fetchone()[0]
        # Get paginated users
        query = "SELECT username, email, password FROM users"
        if search_term:
            query += " WHERE username LIKE ? OR email LIKE ?"
        query += " ORDER BY username LIMIT ? OFFSET ?"
        params.extend([per_page, (page - 1) * per_page])
        c.execute(query, params)
        all_users = c.fetchall()
        # Get reported posts
        c.execute("SELECT posts.id, posts.title, reports.reason, reports.description, reports.id, reports.timestamp, users_reporter.username FROM reports JOIN posts ON reports.post_id = posts.id JOIN users AS users_reporter ON reports.reporter_id = users_reporter.id ORDER BY reports.timestamp DESC")
        reports = c.fetchall()
    conn.close()
    success = request.args.get('success')
    total_pages = (total_users + per_page - 1) // per_page if total_users > 0 else 1
    return render_template('profile.html', username=username, posts=posts, group_posts=group_posts, description=description, profile_picture=profile_picture, stripe_account_id=stripe_account_id, is_owner=is_owner, is_noticed=is_noticed, unread_messages=get_unread_messages_count(session.get('user_id')), success=success, all_users=all_users, search_term=search_term, current_page=page, total_pages=total_pages, per_page=per_page, reports=reports, query=query, notification_prefs=notification_prefs, total_ratings=total_ratings, avg_rating=avg_rating)

@app.route('/settings/notifications', methods=['POST'])
def update_notifications():
    if 'user_id' not in session:
        return redirect('/login')
    
    email_notifications = 1 if request.form.get('email_notifications') else 0
    notify_order = 1 if request.form.get('notify_order') else 0
    notify_dispute = 1 if request.form.get('notify_dispute') else 0
    notify_return = 1 if request.form.get('notify_return') else 0
    notify_message = 1 if request.form.get('notify_message') else 0
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("""UPDATE users SET 
                 email_notifications = ?,
                 notify_order = ?,
                 notify_dispute = ?,
                 notify_return = ?,
                 notify_message = ?
                 WHERE id = ?""",
              (email_notifications, notify_order, notify_dispute, notify_return, notify_message, session['user_id']))
    conn.commit()
    conn.close()
    
    flash('Notification preferences updated!', 'success')
    return redirect(f'/profile/{session.get("username")}')

@app.route('/delete_user/<username>', methods=['POST'])
def delete_user(username):
    if 'user_id' not in session:
        return redirect('/login')
    # Check if user is admin
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],))
    user = c.fetchone()
    if not user or user[0] != 'admin':
        conn.close()
        return 'Access denied', 403
    if username == 'admin':
        conn.close()
        return 'Cannot delete admin', 400
    # Delete user
    c.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    return redirect('/profile/admin')

@app.route('/switch_lang')
def switch_lang():
    lang = request.args.get('lang', 'en')
    if lang in ['en', 'de']:
        session['lang'] = lang
    return redirect(request.referrer or '/dashboard')

@app.route('/export_data')
def export_data():
    if 'user_id' not in session:
        return redirect('/login')
    # Check if user is admin
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],))
    user = c.fetchone()
    if not user or user[0] != 'admin':
        conn.close()
        return 'Access denied', 403
    # Export data
    c.execute("SELECT id, username, email, password, description, profile_picture, stripe_account_id FROM users")
    users = c.fetchall()
    c.execute("SELECT id, user_id, title, description, type, image, links, price, timestamp FROM posts")
    posts = c.fetchall()
    c.execute("SELECT id, sender_id, receiver_id, message, timestamp FROM messages")
    messages = c.fetchall()
    conn.close()
    data = {
        'users': users,
        'posts': posts,
        'messages': messages
    }
    import json
    from flask import Response
    response = Response(json.dumps(data, default=str), mimetype='application/json')
    response.headers['Content-Disposition'] = 'attachment; filename=data_export.json'
    return response

@app.route('/import_data', methods=['POST'])
def import_data():
    if 'user_id' not in session:
        return redirect('/login')
    # Check if user is admin
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],))
    user = c.fetchone()
    if not user or user[0] != 'admin':
        conn.close()
        return 'Access denied', 403
    if 'data_file' not in request.files:
        conn.close()
        return 'No file uploaded', 400
    file = request.files['data_file']
    if file.filename == '':
        conn.close()
        return 'No file selected', 400

    if file.filename.endswith('.zip'):
        # Handle full backup ZIP
        import zipfile
        import shutil
        import json
        try:
            with zipfile.ZipFile(file, 'r') as zip_ref:
                # Extract to temp
                temp_dir = 'static/temp_import'
                os.makedirs(temp_dir, exist_ok=True)
                zip_ref.extractall(temp_dir)
                # Look for data_export.json
                json_path = os.path.join(temp_dir, 'data_export.json')
                if os.path.exists(json_path):
                    with open(json_path, 'r') as f:
                        data = json.load(f)
                else:
                    shutil.rmtree(temp_dir)
                    conn.close()
                    return 'No data_export.json found in ZIP', 400
                # Import images: move all other files to pictures
                total_images = 0
                for root, dirs, files in os.walk(temp_dir):
                    for f in files:
                        if f != 'data_export.json':
                            src = os.path.join(root, f)
                            dst = os.path.join('static/pictures', f)
                            shutil.move(src, dst)
                            total_images += 1
                shutil.rmtree(temp_dir)
        except Exception as e:
            conn.close()
            return f'Error processing ZIP: {str(e)}', 400
    else:
        # Handle JSON file
        import json
        try:
            data = json.load(file)
        except:
            conn.close()
            return 'Invalid JSON file', 400

    # Clear existing data before importing (for clean state restore)
    c.execute("DELETE FROM posts")
    c.execute("DELETE FROM messages")
    c.execute("DELETE FROM groups")
    c.execute("DELETE FROM group_members")
    c.execute("DELETE FROM group_posts")
    c.execute("DELETE FROM orders")
    c.execute("DELETE FROM addresses")
    c.execute("DELETE FROM notices")
    c.execute("DELETE FROM noticed_users")

    # Import data
    import json
    users = data.get('users', [])
    posts = data.get('posts', [])
    messages = data.get('messages', [])
    groups = data.get('groups', [])
    group_members = data.get('group_members', [])
    group_posts_data = data.get('group_posts', [])
    orders = data.get('orders', [])
    addresses = data.get('addresses', [])
    notices = data.get('notices', [])
    noticed_users = data.get('noticed_users', [])
    for u in users:
        try:
            u_list = list(u)
            # Handle backup formats with/without password and stripe_account_id
            # Fields: id, username, email, password, description, profile_picture, stripe_account_id
            while len(u_list) < 7:
                u_list.append(None)
            if u_list[5]:  # profile_picture
                u_list[5] = '/static/pictures/' + os.path.basename(u_list[5])
            c.execute("INSERT INTO users (id, username, email, password, description, profile_picture, stripe_account_id) VALUES (?, ?, ?, ?, ?, ?, ?)", u_list[:7])
        except sqlite3.IntegrityError:
            pass
    for p in posts:
        try:
            p_list = list(p)
            if p_list[5]:  # image
                p_list[5] = '/static/pictures/' + os.path.basename(p_list[5])
            # Handle backup formats with different field counts (9 to 18 fields)
            while len(p_list) < 18:
                p_list.append(None)
            c.execute("""INSERT OR REPLACE INTO posts 
                         (id, user_id, title, description, type, image, links, price, timestamp, 
                          local_pickup, shipping_available, shipping_cost, quantity, is_active,
                          is_featured, featured_until, featured_payment_id) 
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", p_list[:17])
        except sqlite3.IntegrityError:
            pass
    for m in messages:
        try:
            c.execute("INSERT INTO messages (id, sender_id, receiver_id, message, timestamp) VALUES (?, ?, ?, ?, ?)", m)
        except sqlite3.IntegrityError:
            pass
    for g in groups:
        try:
            c.execute("INSERT INTO groups (id, name, description, creator_id, is_private, created_at) VALUES (?, ?, ?, ?, ?, ?)", g)
        except sqlite3.IntegrityError:
            pass
    for gm in group_members:
        try:
            c.execute("INSERT INTO group_members (id, group_id, user_id, status, joined_at) VALUES (?, ?, ?, ?, ?)", gm)
        except sqlite3.IntegrityError:
            pass
    for gp in group_posts_data:
        try:
            gp_list = list(gp)
            while len(gp_list) < 13:
                gp_list.append(None)
            c.execute("""INSERT OR REPLACE INTO group_posts 
                         (id, group_id, user_id, title, content, image, links, price, type, 
                          local_pickup, shipping_available, shipping_cost, created_at) 
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", gp_list[:13])
        except sqlite3.IntegrityError:
            pass
    for o in orders:
        try:
            o_list = list(o)
            # Handle backup formats with different field counts
            while len(o_list) < 34:
                o_list.append(None)
            c.execute("""INSERT OR REPLACE INTO orders 
                         (id, post_id, buyer_id, seller_id, amount, status, stripe_payment_id, tracking_number, 
                          shipped_at, delivered_at, dispute_status, shipping_method, created_at, dispute_reason, 
                          dispute_response, dispute_opened_at, dispute_resolved_at, dispute_resolution,
                          return_status, return_reason, return_response, return_tracking_number,
                          return_requested_at, return_shipped_at, return_completed_at,
                          shipping_cost, return_shipping_covered, seller_at_fault,
                          reminder_count, warning_sent_at, cancelled_at, refund_attempts, transaction_fee) 
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", o_list[:33])
        except sqlite3.IntegrityError:
            pass
    for a in addresses:
        try:
            c.execute("INSERT INTO addresses (id, user_id, order_id, full_name, street, city, state, zip_code, country, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", a)
        except sqlite3.IntegrityError:
            pass
    for n in notices:
        try:
            c.execute("INSERT OR IGNORE INTO notices (user_id, post_id) VALUES (?, ?)", (n[0], n[1]))
        except sqlite3.IntegrityError:
            pass
    for nu in noticed_users:
        try:
            c.execute("INSERT OR IGNORE INTO noticed_users (user_id, noticed_user_id) VALUES (?, ?)", nu)
        except sqlite3.IntegrityError:
            pass
    reports = data.get('reports', [])
    for r in reports:
        try:
            c.execute("INSERT OR IGNORE INTO reports (id, post_id, reporter_id, reason, description, timestamp) VALUES (?, ?, ?, ?, ?, ?)", r)
        except sqlite3.IntegrityError:
            pass
    ratings = data.get('ratings', [])
    for rating in ratings:
        try:
            c.execute("INSERT OR IGNORE INTO ratings (id, order_id, seller_id, buyer_id, rating, review, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", rating)
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    success_msg = 'Data imported successfully'
    if file.filename.endswith('.zip'):
        success_msg += f' ({total_images} images restored)'
    return redirect(f'/profile/admin?success={success_msg}')

@app.route('/export_all')
def export_all():
    if 'user_id' not in session:
        return redirect('/login')
    # Check if user is admin
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],))
    user = c.fetchone()
    if not user or user[0] != 'admin':
        conn.close()
        return 'Access denied', 403
    conn.close()
    import zipfile
    import io
    from flask import send_file
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Add data
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("""SELECT id, username, email, password, description, profile_picture, stripe_account_id, 
                     email_notifications, notify_order, notify_dispute, notify_return, notify_message,
                     return_address, email_verified, verification_token, verification_sent_at 
                     FROM users""")
        users = c.fetchall()
        c.execute("""SELECT id, user_id, title, description, type, image, links, price, timestamp, 
                     local_pickup, shipping_available, shipping_cost, quantity, is_active,
                     is_featured, featured_until, featured_payment_id 
                     FROM posts""")
        posts = c.fetchall()
        c.execute("SELECT id, sender_id, receiver_id, message, timestamp FROM messages")
        messages = c.fetchall()
        c.execute("SELECT id, name, description, creator_id, is_private, created_at FROM groups")
        groups = c.fetchall()
        c.execute("SELECT id, group_id, user_id, status, joined_at FROM group_members")
        group_members = c.fetchall()
        c.execute("""SELECT id, group_id, user_id, title, content, image, links, price, type, 
                     local_pickup, shipping_available, shipping_cost, created_at FROM group_posts""")
        group_posts_data = c.fetchall()
        c.execute("""SELECT id, post_id, buyer_id, seller_id, amount, status, stripe_payment_id, tracking_number, 
                     shipped_at, delivered_at, dispute_status, shipping_method, created_at, dispute_reason, 
                     dispute_response, dispute_opened_at, dispute_resolved_at, dispute_resolution,
                     return_status, return_reason, return_response, return_tracking_number,
                     return_requested_at, return_shipped_at, return_completed_at,
                     shipping_cost, return_shipping_covered, seller_at_fault,
                     reminder_count, warning_sent_at, cancelled_at, refund_attempts, transaction_fee
                     FROM orders""")
        orders = c.fetchall()
        c.execute("SELECT id, user_id, order_id, full_name, street, city, state, zip_code, country, phone FROM addresses")
        addresses = c.fetchall()
        c.execute("SELECT user_id, post_id FROM notices")
        notices = c.fetchall()
        c.execute("SELECT user_id, noticed_user_id FROM noticed_users")
        noticed_users = c.fetchall()
        c.execute("SELECT id, post_id, reporter_id, reason, description, timestamp FROM reports")
        reports = c.fetchall()
        c.execute("SELECT id, order_id, seller_id, buyer_id, rating, review, created_at FROM ratings")
        ratings = c.fetchall()
        conn.close()
        data = {
            'users': users,
            'posts': posts,
            'messages': messages,
            'groups': groups,
            'group_members': group_members,
            'group_posts': group_posts_data,
            'orders': orders,
            'addresses': addresses,
            'notices': notices,
            'noticed_users': noticed_users,
            'reports': reports,
            'ratings': ratings
        }
        import json
        zip_file.writestr('data_export.json', json.dumps(data, default=str))
        # Add images
        for dir_path in ['static/pictures', 'static/uploads']:
            if os.path.exists(dir_path):
                for root, dirs, files in os.walk(dir_path):
                    for file in files:
                        full_path = os.path.join(root, file)
                        arcname = os.path.relpath(full_path, dir_path)
                        zip_file.write(full_path, arcname)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='full_backup.zip', mimetype='application/zip')

@app.route('/export_images')
def export_images():
    if 'user_id' not in session:
        return redirect('/login')
    # Check if user is admin
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],))
    user = c.fetchone()
    if not user or user[0] != 'admin':
        conn.close()
        return 'Access denied', 403
    conn.close()
    import zipfile
    import io
    from flask import send_file
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for dir_path in ['static/pictures', 'static/uploads']:
            if os.path.exists(dir_path):
                for root, dirs, files in os.walk(dir_path):
                    for file in files:
                        full_path = os.path.join(root, file)
                        arcname = os.path.relpath(full_path, dir_path)
                        zip_file.write(full_path, arcname)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='images.zip', mimetype='application/zip')




@app.route('/groups')
def groups():
    if 'user_id' not in session:
        return redirect('/login')
    query = request.args.get('q', '')
    type_filter = request.args.get('type', '')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    # Build query with filters
    base_query = """
        SELECT g.id, g.name, g.description, g.is_private, g.creator_id, u.username,
               COUNT(gm.id) as member_count
        FROM groups g
        LEFT JOIN users u ON g.creator_id = u.id
        LEFT JOIN group_members gm ON g.id = gm.group_id AND gm.status = 'accepted'
    """
    # Backup test commit
    conditions = []
    params = []
    if query:
        conditions.append("(g.name LIKE ? OR g.description LIKE ?)")
        params.extend(['%' + query + '%', '%' + query + '%'])
    if type_filter:
        if type_filter == 'public':
            conditions.append("g.is_private = 0")
        elif type_filter == 'private':
            conditions.append("g.is_private = 1")
    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)
    base_query += " GROUP BY g.id ORDER BY g.created_at DESC"
    c.execute(base_query, params)
    groups_list = c.fetchall()
    # Get user's membership for each group
    user_groups = {}
    if session.get('user_id'):
        c.execute("SELECT group_id, status FROM group_members WHERE user_id = ?", (session['user_id'],))
        user_groups = dict(c.fetchall())
    conn.close()
    return render_template('groups.html', groups=groups_list, user_groups=user_groups, query=query, type_filter=type_filter, unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/create_group', methods=['GET', 'POST'])
def create_group():
    if 'user_id' not in session:
        return redirect('/login')
    if request.method == 'POST':
        name = request.form.get('name').strip()
        description = request.form.get('description').strip()
        is_private = request.form.get('is_private') == 'on'
        if not name:
            flash('Group name is required.', 'danger')
            return redirect('/create_group')
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        try:
            c.execute("INSERT INTO groups (name, description, creator_id, is_private) VALUES (?, ?, ?, ?)",
                      (name, description, session['user_id'], is_private))
            group_id = c.lastrowid
            c.execute("INSERT INTO group_members (group_id, user_id, status) VALUES (?, ?, 'accepted')",
                      (group_id, session['user_id']))
            conn.commit()
            flash('Group created successfully!', 'success')
            return redirect('/groups')
        except sqlite3.IntegrityError:
            flash('Group name already exists.', 'danger')
        finally:
            conn.close()
    return render_template('create_group.html', unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/join_group/<int:group_id>')
def join_group(group_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT is_private FROM groups WHERE id = ?", (group_id,))
    group = c.fetchone()
    if not group:
        conn.close()
        flash('Group not found.', 'danger')
        return redirect('/groups')
    status = 'pending' if group[0] else 'accepted'
    try:
        c.execute("INSERT INTO group_members (group_id, user_id, status) VALUES (?, ?, ?)",
                  (group_id, session['user_id'], status))
        conn.commit()
        if status == 'pending':
            flash('Join request sent. Waiting for approval.', 'info')
        else:
            flash('You have joined the group!', 'success')
    except sqlite3.IntegrityError:
        flash('You are already a member.', 'info')
    conn.close()
    return redirect('/groups')

@app.route('/leave_group/<int:group_id>')
def leave_group(group_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    # Check if user is the creator (can't leave)
    c.execute("SELECT creator_id FROM groups WHERE id = ?", (group_id,))
    group = c.fetchone()
    if group and group[0] == session['user_id']:
        flash('You cannot leave a group you created. Delete it instead.', 'danger')
        conn.close()
        return redirect('/groups')
    c.execute("DELETE FROM group_members WHERE group_id = ? AND user_id = ?", 
              (group_id, session['user_id']))
    conn.commit()
    flash('You have left the group.', 'success')
    conn.close()
    return redirect('/groups')

@app.route('/group/<int:group_id>')
def view_group(group_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    # Check membership
    c.execute("SELECT status FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, session['user_id']))
    membership = c.fetchone()
    if not membership or membership[0] != 'accepted':
        conn.close()
        flash('Access denied. You are not a member of this group.', 'danger')
        return redirect('/groups')
    # Get group info
    c.execute("SELECT g.name, g.description, g.creator_id, u.username, g.is_private FROM groups g JOIN users u ON g.creator_id = u.id WHERE g.id = ?", (group_id,))
    group = c.fetchone()
    if not group:
        conn.close()
        flash('Group not found.', 'danger')
        return redirect('/groups')
    # Get posts
    c.execute("""
        SELECT gp.id, gp.title, gp.content, gp.type, gp.image, gp.links, gp.price, gp.created_at, u.username
        FROM group_posts gp
        JOIN users u ON gp.user_id = u.id
        WHERE gp.group_id = ?
        ORDER BY gp.created_at DESC
    """, (group_id,))
    posts = c.fetchall()
    # Get members
    c.execute("SELECT u.username FROM group_members gm JOIN users u ON gm.user_id = u.id WHERE gm.group_id = ? AND gm.status = 'accepted' ORDER BY u.username", (group_id,))
    members = [row[0] for row in c.fetchall()]
    conn.close()
    is_creator = group[2] == session['user_id']
    return render_template('group_detail.html', group=group, posts=posts, members=members, group_id=group_id, is_creator=is_creator, unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/manage_group/<int:group_id>')
def manage_group(group_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT creator_id FROM groups WHERE id = ?", (group_id,))
    group = c.fetchone()
    if not group or group[0] != session['user_id']:
        conn.close()
        flash('Access denied.', 'danger')
        return redirect('/groups')
    # Get pending members
    c.execute("""
        SELECT gm.id, u.username
        FROM group_members gm
        JOIN users u ON gm.user_id = u.id
        WHERE gm.group_id = ? AND gm.status = 'pending'
    """, (group_id,))
    pending = c.fetchall()
    conn.close()
    return render_template('manage_group.html', group_id=group_id, pending=pending, unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/approve_member/<int:member_id>')
def approve_member(member_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    # Verify creator
    c.execute("""
        SELECT g.creator_id
        FROM group_members gm
        JOIN groups g ON gm.group_id = g.id
        WHERE gm.id = ?
    """, (member_id,))
    creator = c.fetchone()
    if not creator or creator[0] != session['user_id']:
        conn.close()
        flash('Access denied.', 'danger')
        return redirect('/groups')
    c.execute("UPDATE group_members SET status = 'accepted' WHERE id = ?", (member_id,))
    conn.commit()
    conn.close()
    flash('Member approved!', 'success')
    return redirect(request.referrer or '/groups')

@app.route('/deny_member/<int:member_id>')
def deny_member(member_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    # Verify creator
    c.execute("""
        SELECT g.creator_id
        FROM group_members gm
        JOIN groups g ON gm.group_id = g.id
        WHERE gm.id = ?
    """, (member_id,))
    creator = c.fetchone()
    if not creator or creator[0] != session['user_id']:
        conn.close()
        flash('Access denied.', 'danger')
        return redirect('/groups')
    c.execute("DELETE FROM group_members WHERE id = ?", (member_id,))
    conn.commit()
    conn.close()
    flash('Request denied.', 'info')
    return redirect(request.referrer or '/groups')

@app.route('/delete_group/<int:group_id>', methods=['POST'])
def delete_group(group_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT creator_id FROM groups WHERE id = ?", (group_id,))
    group = c.fetchone()
    if not group or group[0] != session['user_id']:
        conn.close()
        flash('Access denied.', 'danger')
        return redirect('/groups')
    # Delete related records first
    c.execute("DELETE FROM group_posts WHERE group_id = ?", (group_id,))
    c.execute("DELETE FROM group_members WHERE group_id = ?", (group_id,))
    c.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    conn.commit()
    conn.close()
    flash('Group deleted successfully.', 'success')
    return redirect('/groups')

@app.route('/toggle_group_privacy/<int:group_id>', methods=['POST'])
def toggle_group_privacy(group_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT creator_id, is_private FROM groups WHERE id = ?", (group_id,))
    group = c.fetchone()
    if not group or group[0] != session['user_id']:
        conn.close()
        flash('Access denied.', 'danger')
        return redirect('/groups')
    new_privacy = 1 if group[1] == 0 else 0
    c.execute("UPDATE groups SET is_private = ? WHERE id = ?", (new_privacy, group_id))
    conn.commit()
    conn.close()
    privacy_text = 'private' if new_privacy else 'public'
    flash(f'Group is now {privacy_text}.', 'success')
    return redirect(f'/group/{group_id}')

@app.route('/edit_group/<int:group_id>', methods=['GET', 'POST'])
def edit_group(group_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT creator_id FROM groups WHERE id = ?", (group_id,))
    group = c.fetchone()
    if not group or group[0] != session['user_id']:
        conn.close()
        flash('Access denied.', 'danger')
        return redirect('/groups')
    if request.method == 'POST':
        name = request.form.get('name').strip()
        description = request.form.get('description').strip()
        if not name:
            flash('Group name is required.', 'danger')
        else:
            c.execute("UPDATE groups SET name = ?, description = ? WHERE id = ?", (name, description, group_id))
            conn.commit()
            flash('Group updated successfully.', 'success')
            conn.close()
            return redirect(f'/group/{group_id}')
    else:
        c.execute("SELECT name, description FROM groups WHERE id = ?", (group_id,))
        group_data = c.fetchone()
    conn.close()
    return render_template('edit_group.html', group_id=group_id, group_data=group_data, unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/edit_group_post/<int:post_id>', methods=['GET', 'POST'])
def edit_group_post(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT gp.user_id, gp.title, gp.content, gp.type, gp.image, gp.links, gp.price, g.name FROM group_posts gp JOIN groups g ON gp.group_id = g.id WHERE gp.id = ?", (post_id,))
    post = c.fetchone()
    if not post or post[0] != session['user_id']:
        conn.close()
        flash('Access denied.', 'danger')
        return redirect('/profile/' + session.get('username'))
    if request.method == 'POST':
        title = request.form.get('title').strip()
        content = request.form.get('content').strip()
        post_type = request.form.get('type')
        links = request.form.get('links')
        price = request.form.get('price')
        image_path = post[4]  # Keep existing image unless new one
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.root_path, 'static', 'pictures', filename)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                file.save(file_path)
                image_path = f'/static/pictures/{filename}'
        if not title or not content:
            flash('Title and content are required.', 'danger')
        else:
            c.execute("UPDATE group_posts SET title = ?, content = ?, type = ?, image = ?, links = ?, price = ? WHERE id = ?", (title, content, post_type, image_path, links, price, post_id))
            conn.commit()
            flash('Post updated successfully.', 'success')
            conn.close()
            return redirect('/profile/' + session.get('username'))
    conn.close()
    return render_template('edit_group_post.html', post=post, unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/delete_group_post/<int:post_id>', methods=['POST'])
def delete_group_post(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM group_posts WHERE id = ?", (post_id,))
    post = c.fetchone()
    if not post or post[0] != session['user_id']:
        conn.close()
        flash('Access denied.', 'danger')
        return redirect('/profile/' + session.get('username'))
    c.execute("DELETE FROM group_posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
    flash('Post deleted successfully.', 'success')
    return redirect('/profile/' + session.get('username'))
    # Delete related records first
    c.execute("DELETE FROM group_posts WHERE group_id = ?", (group_id,))
    c.execute("DELETE FROM group_members WHERE group_id = ?", (group_id,))
    c.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    conn.commit()
    conn.close()
    flash('Group deleted successfully.', 'success')
    return redirect('/groups')

@app.route('/post_in_group/<int:group_id>', methods=['POST'])
def post_in_group(group_id):
    if 'user_id' not in session:
        return redirect('/login')
    # Check if user is member
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT status FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, session['user_id']))
    membership = c.fetchone()
    if not membership or membership[0] != 'accepted':
        conn.close()
        flash('Access denied.', 'danger')
        return redirect('/groups')
    title = request.form.get('title').strip()
    content = request.form.get('content').strip()
    post_type = request.form.get('type')
    links = request.form.get('links')
    price = request.form.get('price')
    local_pickup = 1 if request.form.get('local_pickup') else 0
    shipping_available = 1 if request.form.get('shipping_available') else 0
    shipping_cost = request.form.get('shipping_cost') or 0
    if not title or not content:
        flash('Title and content are required.', 'danger')
        return redirect(f'/group/{group_id}')
    image_path = None
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.root_path, 'static', 'pictures', filename)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            file.save(file_path)
            image_path = f'/static/pictures/{filename}'
    c.execute("INSERT INTO group_posts (group_id, user_id, title, content, type, image, links, price, local_pickup, shipping_available, shipping_cost) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (group_id, session['user_id'], title, content, post_type, image_path, links, price, local_pickup, shipping_available, shipping_cost))
    conn.commit()
    conn.close()
    flash('Post created!', 'success')
    return redirect(f'/group/{group_id}')


@app.route('/post/<int:post_id>')
def post_detail(post_id):
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT posts.id, posts.title, posts.description, posts.type, posts.image, posts.links, posts.price, posts.timestamp, posts.local_pickup, posts.shipping_available, posts.shipping_cost, posts.quantity, posts.is_active, users.username, posts.user_id, posts.is_featured, posts.featured_until FROM posts JOIN users ON posts.user_id = users.id WHERE posts.id = ?", (post_id,))
        post = c.fetchone()
        conn.close()
        if not post:
            return 'Post not found', 404
        return render_template('post_detail.html', post=post, unread_messages=get_unread_messages_count(session.get('user_id')))
    except Exception as e:
        app.logger.error(f"Error in post_detail for id {post_id}: {str(e)}")
        return "Internal Server Error", 500

@app.route('/report_post/<int:post_id>')
def report_post(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT posts.id, posts.title, posts.description, posts.type, posts.image, posts.links, posts.price, posts.timestamp, users.username FROM posts JOIN users ON posts.user_id = users.id WHERE posts.id = ?", (post_id,))
        post = c.fetchone()
        conn.close()
        if not post:
            return 'Post not found', 404
        return render_template('report_post.html', post=post, unread_messages=get_unread_messages_count(session.get('user_id')))
    except Exception as e:
        app.logger.error(f"Error in report_post for id {post_id}: {str(e)}")
        return "Internal Server Error", 500

@app.route('/submit_report/<int:post_id>', methods=['POST'])
def submit_report(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    reason = request.form.get('reason')
    description = request.form.get('description')
    if not reason:
        flash('Please select a reason.', 'danger')
        return redirect(f'/report_post/{post_id}')
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        # Assuming there's a reports table: id, post_id, reporter_id, reason, description, timestamp
        c.execute("INSERT INTO reports (post_id, reporter_id, reason, description, timestamp) VALUES (?, ?, ?, ?, datetime('now'))",
                  (post_id, session['user_id'], reason, description))
        conn.commit()
        conn.close()
        flash('Report submitted successfully.', 'success')
        return redirect('/dashboard')
    except Exception as e:
        app.logger.error(f"Error submitting report for post {post_id}: {str(e)}")
        flash('Error submitting report.', 'danger')
        return redirect(f'/report_post/{post_id}')

@app.route('/delete_report/<int:report_id>', methods=['POST'])
def delete_report(report_id):
    if 'user_id' not in session:
        return redirect('/login')
    # Check if user is admin
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],))
    user = c.fetchone()
    if not user or user[0] != 'admin':
        conn.close()
        return 'Access denied', 403
    # Delete report
    c.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()
    return redirect('/profile/admin')

@app.route('/delete_reported_post/<int:post_id>', methods=['POST'])
def delete_reported_post(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    # Check if user is admin
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],))
    user = c.fetchone()
    if not user or user[0] != 'admin':
        conn.close()
        return 'Access denied', 403
    # Delete the post
    c.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    # Also delete related notices and reports
    c.execute("DELETE FROM notices WHERE post_id = ?", (post_id,))
    c.execute("DELETE FROM reports WHERE post_id = ?", (post_id,))
    conn.commit()
    conn.close()
    return redirect('/profile/admin')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect('/')

@app.route('/crypto_analytics')
def crypto_analytics():
    if 'user_id' not in session:
        return redirect('/login')
    graph_url = None
    if request.args.get('load'):
        # Fetch data and generate graph
        try:
            # Fetch Bitcoin price data from CoinGecko
            url = 'https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=30&interval=daily'
            response = requests.get(url)
            data = response.json()
            prices = [point[1] for point in data['prices']]
            df = pd.DataFrame({'price': prices})
            # Normalize price to -1 to 1 for Fisher Transform
            df['normalized'] = 2 * (df['price'] - df['price'].min()) / (df['price'].max() - df['price'].min()) - 1
            # Apply Fisher Transform
            df['fisher'] = 0.5 * np.log((1 + df['normalized']) / (1 - df['normalized']))
            # Generate plot
            fig, ax = plt.subplots()
            ax.plot(df['fisher'], label='Fisher Transform')
            ax.set_title('Bitcoin Fisher Transform')
            ax.legend()
            buf = io.BytesIO()
            fig.savefig(buf, format='png')
            buf.seek(0)
            graph_url = 'data:image/png;base64,' + base64.b64encode(buf.read()).decode('utf-8')
            plt.close(fig)
        except Exception as e:
            app.logger.error(f"Error generating graph: {str(e)}")
            flash('Error loading data.', 'danger')
    return render_template('crypto_analytics.html', graph_url=graph_url, unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/notices')
def notices():
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT posts.id, posts.title, posts.description, posts.type, posts.image, posts.links, posts.price, posts.timestamp, users.username FROM notices JOIN posts ON notices.post_id = posts.id JOIN users ON posts.user_id = users.id WHERE notices.user_id = ? ORDER BY notices.post_id", (session['user_id'],))
    posts = c.fetchall()
    c.execute("SELECT users.username FROM noticed_users JOIN users ON noticed_users.noticed_user_id = users.id WHERE noticed_users.user_id = ? ORDER BY users.username", (session['user_id'],))
    noticed_users = [row[0] for row in c.fetchall()]
    conn.close()
    return render_template('notices.html', posts=posts, noticed_users=noticed_users, unread_messages=get_unread_messages_count(session['user_id']))

@app.route('/add_notice/<int:post_id>')
def add_notice(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO notices (user_id, post_id) VALUES (?, ?)", (session['user_id'], post_id))
    conn.commit()
    conn.close()
    return redirect(request.referrer or '/dashboard')

@app.route('/remove_notice/<int:post_id>')
def remove_notice(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("DELETE FROM notices WHERE user_id = ? AND post_id = ?", (session['user_id'], post_id))
    conn.commit()
    conn.close()
    return redirect('/notices')

@app.route('/add_notice_user/<username>')
def add_notice_user(username):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    if not user or user[0] == session['user_id']:
        conn.close()
        return redirect(request.referrer or '/dashboard')
    c.execute("INSERT OR IGNORE INTO noticed_users (user_id, noticed_user_id) VALUES (?, ?)", (session['user_id'], user[0]))
    conn.commit()
    conn.close()
    return redirect(request.referrer or '/dashboard')

@app.route('/remove_notice_user/<username>')
def remove_notice_user(username):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    if not user:
        conn.close()
        return redirect('/notices')
    c.execute("DELETE FROM noticed_users WHERE user_id = ? AND noticed_user_id = ?", (session['user_id'], user[0]))
    conn.commit()
    conn.close()
    return redirect('/notices')

@app.route('/edit_post/<int:post_id>')
def edit_post_page(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, title, description, type, image, links, price, local_pickup, shipping_available, shipping_cost FROM posts WHERE id = ? AND user_id = ?", (post_id, session['user_id']))
    post = c.fetchone()
    conn.close()
    if not post:
        return 'Post not found or not yours', 404
    return render_template('edit_post.html', post=post, unread_messages=get_unread_messages_count(session['user_id']))

@app.route('/edit_post/<int:post_id>', methods=['POST'])
def edit_post(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    title = request.form.get('title')
    description = request.form.get('description')
    post_type = request.form.get('type')
    links = request.form.get('links')
    price = request.form.get('price')
    local_pickup = 1 if request.form.get('local_pickup') else 0
    shipping_available = 1 if request.form.get('shipping_available') else 0
    shipping_cost = request.form.get('shipping_cost') or 0
    image_path = None
    if 'image' in request.files:
        file = request.files['image']
        if file.filename != '' and allowed_file(file.filename):
            mime = mimetypes.guess_type(file.filename)[0]
            if mime and mime.startswith('image/'):
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.root_path, 'static', 'uploads', filename)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                file.save(file_path)
                image_path = f'/static/uploads/{filename}'
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    if image_path:
        c.execute("UPDATE posts SET title = ?, description = ?, type = ?, image = ?, links = ?, price = ?, local_pickup = ?, shipping_available = ?, shipping_cost = ? WHERE id = ? AND user_id = ?", 
                  (title, description, post_type, image_path, links, price, local_pickup, shipping_available, shipping_cost, post_id, session['user_id']))
    else:
        c.execute("UPDATE posts SET title = ?, description = ?, type = ?, links = ?, price = ?, local_pickup = ?, shipping_available = ?, shipping_cost = ? WHERE id = ? AND user_id = ?", 
                  (title, description, post_type, links, price, local_pickup, shipping_available, shipping_cost, post_id, session['user_id']))
    conn.commit()
    conn.close()
    return redirect(f'/profile/{session.get("username")}')

@app.route('/delete_post/<int:post_id>', methods=['POST'])
def delete_post(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("DELETE FROM posts WHERE id = ? AND user_id = ?", (post_id, session['user_id']))
    conn.commit()
    conn.close()
    return redirect(f'/profile/{session.get("username")}')

@app.route('/restock_post/<int:post_id>', methods=['POST'])
def restock_post(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    new_quantity = request.form.get('quantity')
    if not new_quantity or int(new_quantity) < 1:
        flash('Please enter a valid quantity.', 'danger')
        return redirect(f'/profile/{session.get("username")}')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    # Verify ownership
    c.execute("SELECT user_id FROM posts WHERE id = ?", (post_id,))
    post = c.fetchone()
    
    if not post or post[0] != session['user_id']:
        conn.close()
        return 'Access denied', 403
    
    c.execute("UPDATE posts SET quantity = ?, is_active = 1 WHERE id = ?", (int(new_quantity), post_id))
    conn.commit()
    conn.close()
    
    flash(f'Post restocked! New quantity: {new_quantity}', 'success')
    return redirect(f'/profile/{session.get("username")}')

@app.route('/edit_quantity/<int:post_id>', methods=['POST'])
def edit_quantity(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    new_quantity = request.form.get('quantity')
    if not new_quantity or int(new_quantity) < 1:
        flash('Please enter a valid quantity.', 'danger')
        return redirect(f'/profile/{session.get("username")}')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    # Verify ownership
    c.execute("SELECT user_id FROM posts WHERE id = ?", (post_id,))
    post = c.fetchone()
    
    if not post or post[0] != session['user_id']:
        conn.close()
        return 'Access denied', 403
    
    c.execute("UPDATE posts SET quantity = ? WHERE id = ?", (int(new_quantity), post_id))
    conn.commit()
    conn.close()
    
    flash(f'Quantity updated to {new_quantity}!', 'success')
    return redirect(f'/profile/{session.get("username")}')

@app.route('/edit_profile')
def edit_profile_page():
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT description, profile_picture, return_address FROM users WHERE id = ?", (session['user_id'],))
    user = c.fetchone()
    conn.close()
    description = user[0] if user else ''
    profile_picture = user[1] if user else None
    return_address = user[2] if user else ''
    error = request.args.get('error')
    return_to_order = request.args.get('return_to_order')
    return render_template('edit_profile.html', description=description, profile_picture=profile_picture, return_address=return_address, unread_messages=get_unread_messages_count(session['user_id']), error=error, return_to_order=return_to_order)

@app.route('/edit_profile', methods=['POST'])
def edit_profile():
    if 'user_id' not in session:
        return redirect('/login')
    description = request.form.get('description') or ''
    profile_picture_path = None
    if 'profile_picture' in request.files:
        file = request.files['profile_picture']
        if file.filename != '':
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.root_path, 'static', 'uploads', filename)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            file.save(file_path)
            profile_picture_path = f'/static/uploads/{filename}'
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    password_error = None
    if current_password or new_password or confirm_password:
        if not current_password or not new_password or not confirm_password:
            password_error = 'All password fields are required.'
        elif new_password != confirm_password:
            password_error = 'New passwords do not match.'
        else:
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute("SELECT password FROM users WHERE id = ?", (session['user_id'],))
            user = c.fetchone()
            conn.close()
            if not user or not check_password_hash(user[0], current_password):
                password_error = 'Current password is incorrect.'
            else:
                hashed_new = generate_password_hash(new_password)
                conn = sqlite3.connect('database.db')
                c = conn.cursor()
                c.execute("UPDATE users SET password = ? WHERE id = ?", (hashed_new, session['user_id']))
                conn.commit()
                conn.close()
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    return_address = request.form.get('return_address') or ''
    if profile_picture_path:
        c.execute("UPDATE users SET description = ?, profile_picture = ?, return_address = ? WHERE id = ?", (description, profile_picture_path, return_address, session['user_id']))
    else:
        c.execute("UPDATE users SET description = ?, return_address = ? WHERE id = ?", (description, return_address, session['user_id']))
    conn.commit()
    conn.close()
    if password_error:
        return redirect(f'/edit_profile?error={password_error}')
    return_to_order = request.form.get('return_to_order')
    if return_to_order:
        return redirect(f'/order/{return_to_order}')
    return redirect(f'/profile/{session.get("username")}')

@app.route('/chat/<username>')
def chat(username):
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    if not user:
        conn.close()
        return 'User not found', 404
    other_user_id = user[0]
    if other_user_id == session['user_id']:
        conn.close()
        return redirect('/messages')
    c.execute("SELECT messages.message, messages.timestamp, users.username, messages.attachment FROM messages JOIN users ON messages.sender_id = users.id WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?) ORDER BY timestamp", (session['user_id'], other_user_id, other_user_id, session['user_id']))
    messages = c.fetchall()
    # Mark messages as read
    c.execute("UPDATE messages SET is_read = 1 WHERE receiver_id = ? AND sender_id = ?", (session['user_id'], other_user_id))
    conn.commit()
    new_unread = get_unread_messages_count(session['user_id'])
    # Get conversations for sidebar
    c.execute("SELECT DISTINCT u.username FROM messages m JOIN users u ON u.id = CASE WHEN m.sender_id = ? THEN m.receiver_id ELSE m.sender_id END WHERE m.sender_id = ? OR m.receiver_id = ?", (session['user_id'], session['user_id'], session['user_id']))
    conversations = [row[0] for row in c.fetchall()]
    conversations_unread = {}
    for conv in conversations:
        c.execute("SELECT id FROM users WHERE username = ?", (conv,))
        user = c.fetchone()
        if user:
            c.execute("SELECT COUNT(*) FROM messages WHERE sender_id = ? AND receiver_id = ? AND is_read = 0", (user[0], session['user_id']))
            conversations_unread[conv] = c.fetchone()[0]
    conn.close()
    return render_template('chat.html', username=username, messages=messages, conversations=conversations, conversations_unread=conversations_unread, unread_messages=new_unread)

@app.route('/send_message/<username>', methods=['POST'])
def send_message(username):
    if 'user_id' not in session:
        return redirect('/login')
    message = request.form.get('message')
    attachment_path = None
    if 'attachment' in request.files:
        file = request.files['attachment']
        if file.filename != '':
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.root_path, 'static', 'uploads', filename)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            file.save(file_path)
            attachment_path = f'/static/uploads/{filename}'
    if not message and not attachment_path:
        return redirect(request.referrer or f'/messages?chat={username}')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    if not user:
        conn.close()
        return 'User not found', 404
    receiver_id = user[0]
    c.execute("INSERT INTO messages (sender_id, receiver_id, message, attachment) VALUES (?, ?, ?, ?)", (session['user_id'], receiver_id, message, attachment_path))
    
    # Check if receiver is admin - notify admin of new message
    if username == 'admin':
        c.execute("SELECT notify_message FROM users WHERE username = 'admin'")
        notify = c.fetchone()
        if not notify or notify[0]:
            c.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],))
            sender = c.fetchone()
            send_email(app.config['ADMIN_EMAIL'], 'New Message Received - Marketplace', 
                      f'You have a new message from {sender[0] if sender else "Unknown"}: {message[:100]}...')
    
    conn.commit()
    conn.close()
    return redirect(request.referrer or f'/messages?chat={username}')

@app.route('/search_users')
def search_users():
    if 'user_id' not in session:
        return redirect('/login')
    query = request.args.get('q', '')
    users = []
    if query:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE username LIKE ? AND id != ?", ('%' + query + '%', session['user_id']))
        users = [row[0] for row in c.fetchall()]
        conn.close()
    return render_template('search_users.html', query=query, users=users, unread_messages=get_unread_messages_count(session['user_id']))

@app.route('/messages')
def messages():
    if 'user_id' not in session:
        return redirect('/login')
    selected_chat = request.args.get('chat')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    post_preview = None
    if 'post_id' in request.args:
        post_id = request.args.get('post_id')
        c.execute("SELECT title, description FROM posts WHERE id = ?", (post_id,))
        post = c.fetchone()
        if post:
            post_preview = {'title': post[0], 'description': post[1]}
    c.execute("SELECT DISTINCT u.username FROM messages m JOIN users u ON u.id = CASE WHEN m.sender_id = ? THEN m.receiver_id ELSE m.sender_id END WHERE m.sender_id = ? OR m.receiver_id = ?", (session['user_id'], session['user_id'], session['user_id']))
    conversations = [row[0] for row in c.fetchall()]
    conversations_unread = {}
    for conv in conversations:
        c.execute("SELECT id FROM users WHERE username = ?", (conv,))
        user = c.fetchone()
        if user:
            c.execute("SELECT COUNT(*) FROM messages WHERE sender_id = ? AND receiver_id = ? AND is_read = 0", (user[0], session['user_id']))
            conversations_unread[conv] = c.fetchone()[0]
    messages_data = []
    if selected_chat:
        c.execute("SELECT id FROM users WHERE username = ?", (selected_chat,))
        user = c.fetchone()
        if user:
            other_user_id = user[0]
            c.execute("SELECT messages.message, messages.timestamp, users.username, messages.attachment FROM messages JOIN users ON messages.sender_id = users.id WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?) ORDER BY timestamp", (session['user_id'], other_user_id, other_user_id, session['user_id']))
            messages_data = c.fetchall()
            # Mark messages as read
            c.execute("UPDATE messages SET is_read = 1 WHERE receiver_id = ? AND sender_id = ?", (session['user_id'], other_user_id))
            conn.commit()
    new_unread = get_unread_messages_count(session['user_id'])
    conn.close()
    return render_template('messages.html', conversations=conversations, conversations_unread=conversations_unread, selected_chat=selected_chat, messages=messages_data, unread_messages=new_unread, post_preview=post_preview)

@app.route('/buy_now/<int:post_id>')
def buy_now(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, user_id, title, price, local_pickup, shipping_available, shipping_cost, quantity, is_active FROM posts WHERE id = ?", (post_id,))
    post = c.fetchone()
    
    if not post:
        conn.close()
        return 'Post not found', 404
    
    if not post[1] or not post[3]:
        conn.close()
        return 'Post not available', 400
    
    if post[7] == 0 or (post[8] is not None and post[8] <= 0):
        conn.close()
        flash('This item is no longer available.', 'danger')
        return redirect(f'/post/{post_id}')
    
    if post[1] == session['user_id']:
        conn.close()
        flash('You cannot buy your own item.', 'warning')
        return redirect(f'/post/{post_id}')
    
    # Only local pickup available - skip checkout form
    if post[4] == 1 and (post[5] == 0 or post[5] is None):
        total_amount = post[3]
        transaction_fee = total_amount * 0.10
        
        c.execute("INSERT INTO orders (post_id, buyer_id, seller_id, amount, status, shipping_method, shipping_cost, transaction_fee) VALUES (?, ?, ?, ?, 'pending', 'local_pickup', 0, ?)",
                  (post_id, session['user_id'], post[1], total_amount, transaction_fee))
        order_id = c.lastrowid
        conn.commit()
        conn.close()
        
        session['current_order_id'] = order_id
        return redirect(f'/create_checkout_session/{post_id}')
    
    conn.close()
    return redirect(f'/checkout/{post_id}')

@app.route('/checkout/<int:post_id>')
def checkout(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT title, price, user_id, local_pickup, shipping_available, shipping_cost, quantity, is_active FROM posts WHERE id = ?", (post_id,))
    post = c.fetchone()
    
    if not post or not post[1]:
        conn.close()
        return 'Post not found or has no price', 404
    
    if post[7] == 0 or (post[6] is not None and post[6] <= 0):
        conn.close()
        flash('This item is no longer available.', 'danger')
        return redirect(f'/post/{post_id}')
    
    if post[2] == session['user_id']:
        conn.close()
        flash('You cannot buy your own item.', 'warning')
        return redirect(f'/post/{post_id}')
    
    c.execute("SELECT * FROM orders WHERE post_id = ? AND buyer_id = ? AND status = 'pending'", (post_id, session['user_id']))
    existing_order = c.fetchone()
    
    c.execute("SELECT * FROM addresses WHERE user_id = ? ORDER BY id DESC LIMIT 1", (session['user_id'],))
    saved_address = c.fetchone()
    conn.close()
    
    return render_template('checkout.html', post=post, post_id=post_id, existing_order=existing_order, saved_address=saved_address, unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/process_checkout/<int:post_id>', methods=['POST'])
def process_checkout(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    delivery_method = request.form.get('delivery_method')
    
    if not delivery_method:
        flash('Please select a delivery method.', 'danger')
        return redirect(f'/checkout/{post_id}')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT title, price, user_id, local_pickup, shipping_available, shipping_cost FROM posts WHERE id = ?", (post_id,))
    post = c.fetchone()
    
    if not post or not post[1]:
        conn.close()
        return 'Post not found or has no price', 404
    
    if post[2] == session['user_id']:
        conn.close()
        flash('You cannot buy your own item.', 'warning')
        return redirect(f'/post/{post_id}')
    
    # Validate delivery method matches available options
    if delivery_method == 'local_pickup' and not post[3]:
        flash('Local pickup is not available for this item.', 'danger')
        return redirect(f'/checkout/{post_id}')
    if delivery_method == 'shipping' and not post[4]:
        flash('Shipping is not available for this item.', 'danger')
        return redirect(f'/checkout/{post_id}')
    
    total_amount = post[1]
    shipping_cost = 0
    if delivery_method == 'shipping' and post[4]:
        shipping_cost = post[5] or 0
        total_amount += shipping_cost
    
    transaction_fee = total_amount * 0.10
    
    if delivery_method == 'local_pickup':
        full_name = request.form.get('full_name')
        street = ''
        city = ''
        state = ''
        zip_code = ''
        country = ''
        phone = request.form.get('phone') or ''
    else:
        full_name = request.form.get('full_name')
        street = request.form.get('street')
        city = request.form.get('city')
        state = request.form.get('state')
        zip_code = request.form.get('zip_code')
        country = request.form.get('country')
        phone = request.form.get('phone')
    
    save_address = request.form.get('save_address')
    
    c.execute("INSERT INTO orders (post_id, buyer_id, seller_id, amount, status, shipping_method, shipping_cost, transaction_fee) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
              (post_id, session['user_id'], post[2], total_amount, delivery_method, shipping_cost, transaction_fee))
    order_id = c.lastrowid
    
    # Only save address for shipping orders, not local pickup
    if save_address and full_name and delivery_method == 'shipping':
        c.execute("""INSERT INTO addresses (user_id, order_id, full_name, street, city, state, zip_code, country, phone)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (session['user_id'], order_id, full_name, street, city, state, zip_code, country, phone))
    
    conn.commit()
    conn.close()
    
    session['current_order_id'] = order_id
    return redirect(f'/create_checkout_session/{post_id}')

@app.route('/create_checkout_session/<int:post_id>')
def create_checkout_session(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    if not app.config['STRIPE_SECRET_KEY']:
        flash('Stripe is not configured.', 'danger')
        return redirect(f'/post/{post_id}')
    
    order_id = session.get('current_order_id')
    if not order_id:
        flash('Please complete checkout form first.', 'warning')
        return redirect(f'/checkout/{post_id}')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT amount, shipping_method FROM orders WHERE id = ?", (order_id,))
    order = c.fetchone()
    c.execute("SELECT title, price, user_id FROM posts WHERE id = ?", (post_id,))
    post = c.fetchone()
    conn.close()
    
    if not post or not post[1] or not order:
        return 'Post or order not found', 404
    
    total_amount = order[0]
    shipping_method = order[1]
    
    session.pop('current_order_id', None)
    
    seller_id = post[2]
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT u.username, u.stripe_account_id FROM users u JOIN posts p ON p.user_id = u.id WHERE p.id = ?", (post_id,))
    seller_info = c.fetchone()
    conn.close()
    
    seller_username = seller_info[0] if seller_info else None
    seller_stripe = seller_info[1] if seller_info else None
    
    app.logger.info(f"DEBUG: seller_info={seller_info}, seller_username={seller_username}, seller_stripe={seller_stripe}")
    
    # Check if seller has Stripe connected for automatic payouts
    use_seller_payout = seller_stripe
    
    if not use_seller_payout:
        # Seller not connected - redirect to contact page for manual payment
        flash('Seller has not set up online payments. Please contact seller to arrange payment.', 'info')
        return redirect(f'/messages?chat={seller_username}&post_id={post_id}')
    
    transfer_data = {'destination': seller_stripe}
    
    app.logger.info(f"Creating checkout session for order {order_id}, amount: {total_amount}, seller: {seller_username}")
    
    try:
        if not app.config['STRIPE_SECRET_KEY']:
            flash('Stripe is not configured. Please contact the administrator.', 'danger')
            return redirect(f'/post/{post_id}')
        
        session_params = {
            'payment_method_types': ['card'],
            'line_items': [{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': post[0]
                    },
                    'unit_amount': int(total_amount * 100),
                },
                'quantity': 1,
            }],
            'mode': 'payment',
            'success_url': request.url_root + f'payment_success?post_id={post_id}&order_id={order_id}',
            'cancel_url': request.url_root + f'post/{post_id}',
            'metadata': {'order_id': order_id, 'post_id': post_id}
        }
        
        if use_seller_payout:
            session_params['payment_intent_data'] = {
                'transfer_data': {'destination': seller_stripe},
                'application_fee_amount': int(total_amount * 100 * 0.10)
            }
        
        session_stripe = stripe.checkout.Session.create(**session_params)
        return redirect(session_stripe.url, code=303)
    except Exception as e:
        flash(f'Payment error: {str(e)}', 'danger')
        return redirect(f'/post/{post_id}')

@app.route('/payment_success')
def payment_success():
    post_id = request.args.get('post_id')
    order_id = request.args.get('order_id')
    
    if not post_id:
        return redirect('/dashboard')
    
    if order_id:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))
        
        # Decrement quantity after payment
        c.execute("UPDATE posts SET quantity = quantity - 1 WHERE id = ?", (post_id,))
        
        # Check if quantity is 0, then deactivate post
        c.execute("UPDATE posts SET is_active = 0 WHERE id = ? AND quantity <= 0", (post_id,))
        
        # Send email notifications
        app.logger.info(f"Sending payment emails for order {order_id}")
        c.execute("""SELECT o.buyer_id, o.seller_id, o.amount, p.title, buyer.email, seller.email,
                     COALESCE(buyer.email_notifications, 1), COALESCE(buyer.notify_order, 1),
                     COALESCE(seller.email_notifications, 1), COALESCE(seller.notify_order, 1)
                     FROM orders o
                     JOIN posts p ON o.post_id = p.id
                     JOIN users buyer ON o.buyer_id = buyer.id
                     JOIN users seller ON o.seller_id = seller.id
                     WHERE o.id = ?""", (order_id,))
        order_info = c.fetchone()
        app.logger.info(f"Order info: {order_info}")
        
        if order_info:
            buyer_email = order_info[4]
            seller_email = order_info[5]
            buyer_email_notif = order_info[6]
            buyer_notify = order_info[7]
            seller_email_notif = order_info[8]
            seller_notify = order_info[9]
            post_title = order_info[3]
            amount = order_info[2]
            
            app.logger.info(f"Buyer email: {buyer_email}, notify: {buyer_email_notif and buyer_notify}")
            app.logger.info(f"Seller email: {seller_email}, notify: {seller_email_notif and seller_notify}")
            
            if buyer_email_notif and buyer_notify:
                send_email(buyer_email, 'Payment Confirmed - Marketplace', 
                          f'Your payment of ${amount:.2f} for "{post_title}" has been confirmed. The seller will ship your order soon.')
            if seller_email_notif and seller_notify:
                send_email(seller_email, 'New Order - Marketplace', 
                          f'You have a new order for "{post_title}". Payment of ${amount:.2f} received. Please ship the item.')
        
        conn.commit()
        conn.close()
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT title, price FROM posts WHERE id = ?", (post_id,))
    post = c.fetchone()
    conn.close()
    return render_template('payment_success.html', post=post, order_id=order_id, unread_messages=get_unread_messages_count(session.get('user_id')))

FEATURED_PRICE = 2.99

@app.route('/feature/<int:post_id>')
def feature_post(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT user_id, title, is_featured, featured_until FROM posts WHERE id = ?", (post_id,))
    post = c.fetchone()
    
    if not post:
        conn.close()
        return 'Post not found', 404
    
    if post[0] != session['user_id']:
        conn.close()
        return 'Access denied', 403
    
    if post[2] and post[3]:
        featured_time = datetime.strptime(post[3], '%Y-%m-%d %H:%M:%S.%f') if isinstance(post[3], str) else post[3]
        if featured_time > datetime.now():
            conn.close()
            flash('This post is already featured.', 'info')
            return redirect(f'/post/{post_id}')
    
    conn.close()
    
    # Free for admin
    if session.get('username') == 'admin':
        from datetime import timedelta
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        featured_until = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S.%f')
        c.execute("UPDATE posts SET is_featured = 1, featured_until = ? WHERE id = ?", (featured_until, post_id))
        conn.commit()
        conn.close()
        flash('Your listing is now featured for 7 days!', 'success')
        return redirect(f'/post/{post_id}')
    
    return render_template('feature_checkout.html', post_id=post_id, title=post[1], price=FEATURED_PRICE, unread_messages=0)

@app.route('/create_featured_session/<int:post_id>')
def create_featured_session(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT user_id, title FROM posts WHERE id = ?", (post_id,))
    post = c.fetchone()
    
    if not post or post[0] != session['user_id']:
        conn.close()
        return 'Post not found or access denied', 404
    conn.close()
    
    try:
        session_stripe = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': f'Featured Listing: {post[1]}'
                    },
                    'unit_amount': int(FEATURED_PRICE * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.url_root + f'featured_success?post_id={post_id}',
            cancel_url=request.url_root + f'post/{post_id}',
            metadata={'post_id': post_id, 'type': 'featured'}
        )
        return redirect(session_stripe.url, code=303)
    except Exception as e:
        flash(f'Payment error: {str(e)}', 'danger')
        return redirect(f'/post/{post_id}')

@app.route('/featured_success')
def featured_success():
    post_id = request.args.get('post_id')
    
    if not post_id:
        return redirect('/dashboard')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    from datetime import timedelta
    featured_until = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S.%f')
    
    c.execute("UPDATE posts SET is_featured = 1, featured_until = ? WHERE id = ?", (featured_until, post_id))
    conn.commit()
    conn.close()
    
    flash('Your listing is now featured for 7 days!', 'success')
    return redirect(f'/post/{post_id}')

@app.route('/orders')
def orders():
    if 'user_id' not in session:
        return redirect('/login')
    
    user_id = int(session['user_id'])
    app.logger.info(f"Orders page - user_id: {user_id}")
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    # Get purchases (orders where user is buyer)
    c.execute("""SELECT o.id, o.post_id, o.buyer_id, o.seller_id, o.amount, o.status, o.created_at,
                 p.title, p.image, u.username as seller_username
                 FROM orders o
                 JOIN posts p ON o.post_id = p.id
                 JOIN users u ON o.seller_id = u.id
                 WHERE o.buyer_id = ?
                 ORDER BY o.created_at DESC""", (user_id,))
    purchases = c.fetchall()
    
    # Get sales (orders where user is seller)
    c.execute("""SELECT o.id, o.post_id, o.buyer_id, o.seller_id, o.amount, o.status, o.created_at,
                 p.title, p.image, u.username as buyer_username
                 FROM orders o
                 JOIN posts p ON o.post_id = p.id
                 JOIN users u ON o.buyer_id = u.id
                 WHERE o.seller_id = ?
                 ORDER BY o.created_at DESC""", (user_id,))
    sales = c.fetchall()
    
    app.logger.info(f"Orders: {len(purchases)} purchases, {len(sales)} sales for user_id {user_id}")
    conn.close()
    return render_template('orders.html', purchases=purchases, sales=sales, unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/order/<int:order_id>')
def order_detail(order_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("""SELECT o.id, o.post_id, o.buyer_id, o.seller_id, o.amount, o.status, o.created_at,
                 o.tracking_number, o.shipped_at, o.delivered_at, o.dispute_status, o.shipping_method,
                 p.title, p.image, p.description,
                 buyer.username, buyer.email,
                 seller.username, seller.email, seller.return_address,
                 a.full_name, a.street, a.city, a.state, a.zip_code, a.country, a.phone,
                 o.dispute_reason, o.dispute_response, o.dispute_opened_at, o.dispute_resolved_at, o.dispute_resolution,
                 o.return_status, o.return_reason, o.return_response, o.return_tracking_number, o.return_requested_at, o.return_shipped_at, o.return_completed_at,
                 o.shipping_cost, o.seller_at_fault
                 FROM orders o
                 JOIN posts p ON o.post_id = p.id
                 JOIN users buyer ON o.buyer_id = buyer.id
                 JOIN users seller ON o.seller_id = seller.id
                 LEFT JOIN addresses a ON a.order_id = o.id AND a.user_id = o.buyer_id
                 WHERE o.id = ? AND (o.buyer_id = ? OR o.seller_id = ?)""", 
                (order_id, session['user_id'], session['user_id']))
    order = c.fetchone()
    conn.close()
    
    if not order:
        return 'Order not found', 404
    
    return render_template('order_detail.html', order=order, unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/order/<int:order_id>/ship', methods=['POST'])
def mark_shipped(order_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    tracking_number = request.form.get('tracking_number')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT seller_id, status FROM orders WHERE id = ?", (order_id,))
    order = c.fetchone()
    
    if not order:
        conn.close()
        return 'Order not found', 404
    
    if order[0] != session['user_id']:
        conn.close()
        return 'Access denied', 403
    
    if order[1] != 'paid':
        conn.close()
        flash('Order must be paid before shipping.', 'warning')
        return redirect(f'/order/{order_id}')
    
    c.execute("UPDATE orders SET status = 'shipped', tracking_number = ?, shipped_at = CURRENT_TIMESTAMP WHERE id = ?", (tracking_number, order_id))
    
    # Get buyer email for notification
    c.execute("""SELECT buyer.email, buyer.email_notifications, buyer.notify_order, p.title
                 FROM orders o
                 JOIN users buyer ON o.buyer_id = buyer.id
                 JOIN posts p ON o.post_id = p.id
                 WHERE o.id = ?""", (order_id,))
    buyer_info = c.fetchone()
    if buyer_info and buyer_info[1] and buyer_info[2]:
        send_email(buyer_info[0], 'Your Order Has Been Shipped - Marketplace', 
                  f'Your order "{buyer_info[3]}" has been shipped! Tracking: {tracking_number or "Not provided"}')
    
    conn.commit()
    conn.close()
    
    flash('Order marked as shipped!', 'success')
    return redirect(f'/order/{order_id}')

@app.route('/order/<int:order_id>/picked_up', methods=['POST'])
def mark_picked_up(order_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT seller_id, status, shipping_method FROM orders WHERE id = ?", (order_id,))
    order = c.fetchone()
    
    if not order:
        conn.close()
        return 'Order not found', 404
    
    if order[0] != session['user_id']:
        conn.close()
        return 'Access denied', 403
    
    if order[1] != 'paid' or order[2] != 'local_pickup':
        flash('Cannot mark as picked up.', 'warning')
        conn.close()
        return redirect(f'/order/{order_id}')
    
    c.execute("UPDATE orders SET status = 'delivered', delivered_at = datetime('now') WHERE id = ?", (order_id,))
    
    c.execute("""SELECT buyer.email, buyer.email_notifications, p.title FROM orders o 
                 JOIN users buyer ON o.buyer_id = buyer.id 
                 JOIN posts p ON o.post_id = p.id WHERE o.id = ?""", (order_id,))
    buyer_info = c.fetchone()
    if buyer_info and buyer_info[1]:
        send_email(buyer_info[0], 'Order Picked Up - Marketplace',
                  f'Your order "{buyer_info[2]}" has been picked up! Thank you for your purchase.')
    
    conn.commit()
    conn.close()
    
    flash('Order marked as picked up!', 'success')
    return redirect(f'/order/{order_id}')

@app.route('/order/<int:order_id>/buyer_cancel')
def buyer_cancel_local_pickup(order_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT buyer_id, seller_id, status, shipping_method, amount, stripe_payment_id FROM orders WHERE id = ?", (order_id,))
    order = c.fetchone()
    
    if not order:
        conn.close()
        return 'Order not found', 404
    
    if order[0] != session['user_id']:
        conn.close()
        return 'Access denied', 403
    
    if order[2] != 'paid' or order[3] != 'local_pickup':
        flash('Cannot request cancellation for this order.', 'warning')
        conn.close()
        return redirect(f'/order/{order_id}')
    
    # Process refund
    if order[5]:  # Has Stripe payment ID
        try:
            stripe.Refund.create(payment_intent=order[5], amount=int(order[4] * 100))
            c.execute("UPDATE orders SET status = 'refunded', cancelled_at = CURRENT_TIMESTAMP WHERE id = ?", (order_id,))
            flash('Refund has been processed. Your money will be returned within 5-10 business days.', 'success')
        except Exception as e:
            app.logger.error(f"Refund failed for order #{order_id}: {str(e)}")
            flash('Refund processing failed. Please contact support.', 'danger')
    else:
        c.execute("UPDATE orders SET status = 'refunded', cancelled_at = CURRENT_TIMESTAMP WHERE id = ?", (order_id,))
        flash('Order cancelled and refunded.', 'success')
    
    conn.commit()
    conn.close()
    
    return redirect('/orders')

@app.route('/cancel_order/<int:order_id>', methods=['POST'])
def cancel_order(order_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT buyer_id, status FROM orders WHERE id = ?", (order_id,))
    order = c.fetchone()
    
    if not order:
        conn.close()
        return 'Order not found', 404
    
    if order[0] != session['user_id']:
        conn.close()
        return 'Access denied', 403
    
    if order[1] not in ['pending', 'paid']:
        flash('Cannot cancel order in current status.', 'warning')
        conn.close()
        return redirect(f'/order/{order_id}')
    
    c.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()
    
    flash('Order cancelled.', 'success')
    return redirect('/orders')

@app.route('/order/<int:order_id>/delivered', methods=['POST'])
def mark_delivered(order_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT buyer_id, status FROM orders WHERE id = ?", (order_id,))
    order = c.fetchone()
    
    if not order:
        conn.close()
        return 'Order not found', 404
    
    if order[0] != session['user_id']:
        conn.close()
        return 'Access denied', 403
    
    c.execute("UPDATE orders SET status = 'delivered', delivered_at = CURRENT_TIMESTAMP WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()
    
    flash('Order marked as delivered!', 'success')
    return redirect(f'/order/{order_id}')

@app.route('/order/<int:order_id>/rate', methods=['POST'])
def submit_rating(order_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    rating = request.form.get('rating')
    review = request.form.get('review', '')
    
    if not rating or int(rating) < 1 or int(rating) > 5:
        flash('Please select a valid rating (1-5 stars).', 'danger')
        return redirect(f'/order/{order_id}')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT buyer_id, seller_id, status FROM orders WHERE id = ?", (order_id,))
    order = c.fetchone()
    
    if not order:
        conn.close()
        return 'Order not found', 404
    
    if order[0] != session['user_id']:
        conn.close()
        return 'Access denied', 403
    
    if order[2] != 'delivered':
        flash('You can only rate completed orders.', 'warning')
        conn.close()
        return redirect(f'/order/{order_id}')
    
    c.execute("SELECT id FROM ratings WHERE order_id = ?", (order_id,))
    if c.fetchone():
        conn.close()
        flash('You have already rated this order.', 'warning')
        return redirect(f'/order/{order_id}')
    
    c.execute("INSERT INTO ratings (order_id, seller_id, buyer_id, rating, review) VALUES (?, ?, ?, ?, ?)",
              (order_id, order[1], order[0], int(rating), review))
    conn.commit()
    conn.close()
    
    flash('Thank you for your rating!', 'success')
    return redirect(f'/order/{order_id}')

@app.route('/profile/<username>/ratings')
def seller_ratings(username):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    
    if not user:
        conn.close()
        return 'User not found', 404
    
    c.execute("""SELECT r.rating, r.review, r.created_at, buyer.username 
                 FROM ratings r 
                 JOIN users buyer ON r.buyer_id = buyer.id 
                 WHERE r.seller_id = ? 
                 ORDER BY r.created_at DESC""", (user[0],))
    ratings = c.fetchall()
    
    c.execute("SELECT COUNT(*), COALESCE(AVG(rating), 0) FROM ratings WHERE seller_id = ?", (user[0],))
    stats = c.fetchone()
    conn.close()
    
    return render_template('seller_ratings.html', username=username, ratings=ratings, 
                         total_ratings=stats[0], avg_rating=round(stats[1], 1),
                         unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/order/<int:order_id>/dispute', methods=['POST'])
def open_dispute(order_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    reason = request.form.get('reason')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT buyer_id, seller_id, status FROM orders WHERE id = ?", (order_id,))
    order = c.fetchone()
    
    if not order:
        conn.close()
        return 'Order not found', 404
    
    # Only buyer can open dispute, and only if paid or shipped
    if session['user_id'] != order[0]:
        conn.close()
        return 'Access denied', 403
    
    if order[2] not in ['paid', 'shipped']:
        flash('Cannot open dispute for this order status.', 'warning')
        conn.close()
        return redirect(f'/order/{order_id}')
    
    c.execute("""UPDATE orders SET 
                 dispute_status = 'open', 
                 dispute_reason = ?,
                 dispute_opened_at = CURRENT_TIMESTAMP 
                 WHERE id = ?""", (reason, order_id))
    
    # Get order info for admin notification
    c.execute("""SELECT p.title FROM orders o JOIN posts p ON o.post_id = p.id WHERE o.id = ?""", (order_id,))
    order_info = c.fetchone()
    
    # Notify admin
    send_email(app.config['ADMIN_EMAIL'], 'New Dispute Opened - Marketplace', 
              f'A dispute has been opened for order #{order_id}: "{order_info[0] if order_info else "Unknown"}". Reason: {reason}')
    
    conn.commit()
    conn.close()
    
    flash('Dispute opened! An admin will review your case.', 'warning')
    return redirect(f'/order/{order_id}')

@app.route('/order/<int:order_id>/dispute/respond', methods=['POST'])
def respond_to_dispute(order_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    response = request.form.get('response')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT buyer_id, seller_id, dispute_status FROM orders WHERE id = ?", (order_id,))
    order = c.fetchone()
    
    if not order:
        conn.close()
        return 'Order not found', 404
    
    if order[2] != 'open':
        conn.close()
        flash('No active dispute to respond to.', 'warning')
        return redirect(f'/order/{order_id}')
    
    if session['user_id'] != order[1]:
        conn.close()
        return 'Access denied', 403
    
    c.execute("UPDATE orders SET dispute_response = ? WHERE id = ?", (response, order_id))
    conn.commit()
    conn.close()
    
    flash('Response submitted!', 'success')
    return redirect(f'/order/{order_id}')

# Dispute resolution routes for admin
@app.route('/admin/disputes')
def admin_disputes():
    if 'user_id' not in session or session.get('username') != 'admin':
        return 'Access denied', 403
    
    status_filter = request.args.get('status', '')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    query = """
        SELECT o.id, o.amount, o.dispute_status, o.dispute_reason, o.dispute_opened_at,
               buyer.username, seller.username, p.title
        FROM orders o
        JOIN users buyer ON o.buyer_id = buyer.id
        JOIN users seller ON o.seller_id = seller.id
        JOIN posts p ON o.post_id = p.id
        WHERE o.dispute_status IS NOT NULL
    """
    params = []
    
    if status_filter:
        query += " AND o.dispute_status = ?"
        params.append(status_filter)
    
    query += " ORDER BY o.dispute_opened_at DESC"
    
    c.execute(query, params)
    disputes = c.fetchall()
    conn.close()
    
    return render_template('admin_disputes.html', disputes=disputes, status_filter=status_filter, unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/admin/dispute/<int:order_id>', methods=['GET', 'POST'])
def admin_dispute_detail(order_id):
    if 'user_id' not in session or session.get('username') != 'admin':
        return 'Access denied', 403
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    if request.method == 'POST':
        action = request.form.get('action')
        resolution_note = request.form.get('resolution_note', '')
        
        if action in ['refund', 'release', 'partial']:
            # Process the resolution
            if action == 'refund':
                new_status = 'refunded'
                resolution = 'full_refund'
            elif action == 'release':
                new_status = 'paid'
                resolution = 'released'
            else:  # partial
                new_status = 'refunded'
                resolution = 'partial_refund'
            
            # Get payment info
            c.execute("SELECT stripe_payment_id FROM orders WHERE id = ?", (order_id,))
            payment = c.fetchone()
            
            if payment and payment[0] and app.config.get('STRIPE_SECRET_KEY'):
                try:
                    if action in ['refund', 'partial']:
                        # Process Stripe refund
                        stripe.Refund.create(payment_intent=payment[0])
                except Exception as e:
                    flash(f'Stripe refund failed: {str(e)}', 'danger')
                    conn.close()
                    return redirect(f'/admin/dispute/{order_id}')
            
            # Update order
            c.execute("""UPDATE orders SET 
                        dispute_status = ?, 
                        dispute_resolution = ?,
                        dispute_resolved_at = CURRENT_TIMESTAMP,
                        status = ?
                        WHERE id = ?""", 
                      (new_status, resolution + ': ' + resolution_note, new_status, order_id))
            conn.commit()
            flash(f'Dispute resolved: {resolution}', 'success')
            conn.close()
            return redirect('/admin/disputes')
    
    # Get order details
    c.execute("""SELECT o.*, buyer.username, seller.username, p.title, p.image
                 FROM orders o
                 JOIN users buyer ON o.buyer_id = buyer.id
                 JOIN users seller ON o.seller_id = seller.id
                 JOIN posts p ON o.post_id = p.id
                 WHERE o.id = ?""", (order_id,))
    order = c.fetchone()
    conn.close()
    
    return render_template('admin_dispute_detail.html', order=order, unread_messages=get_unread_messages_count(session.get('user_id')))

# Return routes
@app.route('/order/<int:order_id>/return', methods=['POST'])
def request_return(order_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    reason = request.form.get('reason')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT buyer_id, seller_id, status, return_status FROM orders WHERE id = ?", (order_id,))
    order = c.fetchone()
    
    if not order:
        conn.close()
        return 'Order not found', 404
    
    if order[0] != session['user_id']:
        conn.close()
        return 'Access denied', 403
    
    if order[2] not in ['shipped', 'delivered']:
        flash('Cannot request return for this order status.', 'warning')
        conn.close()
        return redirect(f'/order/{order_id}')
    
    if order[3] in ['requested', 'approved']:
        flash('Return already requested.', 'warning')
        conn.close()
        return redirect(f'/order/{order_id}')
    
    c.execute("""UPDATE orders SET 
                 return_status = 'requested', 
                 return_reason = ?,
                 return_requested_at = CURRENT_TIMESTAMP,
                 status = 'return_requested'
                 WHERE id = ?""", (reason, order_id))
    
    # Get seller and admin info for notifications
    c.execute("""SELECT seller.email, seller.email_notifications, seller.notify_return, p.title
                 FROM orders o
                 JOIN users seller ON o.seller_id = seller.id
                 JOIN posts p ON o.post_id = p.id
                 WHERE o.id = ?""", (order_id,))
    seller_info = c.fetchone()
    if seller_info and seller_info[1] and seller_info[2]:
        send_email(seller_info[0], 'Return Requested - Marketplace', 
                  f'A buyer has requested a return for "{seller_info[3]}".\n\nReason: {reason}')
    
    # Notify admin
    send_email(app.config['ADMIN_EMAIL'], 'New Return Request - Marketplace', 
              f'A return request has been made for order #{order_id}: "{seller_info[2] if seller_info else "Unknown"}"')
    
    conn.commit()
    conn.close()
    
    flash('Return requested! The seller will review your request.', 'success')
    return redirect(f'/order/{order_id}')

@app.route('/order/<int:order_id>/return/respond', methods=['POST'])
def respond_return(order_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    action = request.form.get('action')
    response = request.form.get('response')
    seller_at_fault = request.form.get('seller_at_fault') == 'on'
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT seller_id, return_status, seller.return_address FROM orders o JOIN users seller ON o.seller_id = seller.id WHERE o.id = ?", (order_id,))
    order = c.fetchone()
    
    if not order:
        conn.close()
        return 'Order not found', 404
    
    if order[0] != session['user_id']:
        conn.close()
        return 'Access denied', 403
    
    if order[1] != 'requested':
        conn.close()
        flash('No return request to respond to.', 'warning')
        return redirect(f'/order/{order_id}')
    
    if action == 'approve':
        if not order[2]:
            conn.close()
            flash('Please add a return address in your profile before approving returns.', 'warning')
            return redirect(f'/edit_profile?return_to_order={order_id}')
        new_status = 'approved'
    else:
        new_status = 'rejected'
        seller_at_fault = False
    
    c.execute("""UPDATE orders SET 
                 return_status = ?, 
                 status = 'delivered',
                 return_response = ?,
                 seller_at_fault = ?
                 WHERE id = ?""", (new_status, response, 1 if seller_at_fault else 0, order_id))
    
    # Get buyer info and seller return address for notification
    c.execute("""SELECT buyer.email, buyer.email_notifications, buyer.notify_return, p.title, seller.return_address
                 FROM orders o
                 JOIN users buyer ON o.buyer_id = buyer.id
                 JOIN posts p ON o.post_id = p.id
                 JOIN users seller ON o.seller_id = seller.id
                 WHERE o.id = ?""", (order_id,))
    buyer_info = c.fetchone()
    if buyer_info and buyer_info[1] and buyer_info[2]:
        if new_status == 'approved':
            email_body = f'Your return request for "{buyer_info[3]}" has been APPROVED. Please ship the item back to the seller.'
            if buyer_info[4]:
                email_body += f'\n\nReturn Address:\n{buyer_info[4]}'
            send_email(buyer_info[0], 'Return Approved - Marketplace', email_body)
        else:
            send_email(buyer_info[0], 'Return Rejected - Marketplace', 
                      f'Your return request for "{buyer_info[3]}" has been REJECTED. Contact the seller for more details.')
    
    conn.commit()
    conn.close()
    
    flash(f'Return {new_status}!', 'success')
    return redirect(f'/order/{order_id}')

@app.route('/order/<int:order_id>/return/mark_shipped', methods=['POST'])
def mark_return_shipped(order_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    tracking_number = request.form.get('tracking_number')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT buyer_id, return_status FROM orders WHERE id = ?", (order_id,))
    order = c.fetchone()
    
    if not order:
        conn.close()
        return 'Order not found', 404
    
    if order[0] != session['user_id']:
        conn.close()
        return 'Access denied', 403
    
    if order[1] != 'approved':
        conn.close()
        flash('Return must be approved first.', 'warning')
        return redirect(f'/order/{order_id}')
    
    c.execute("""UPDATE orders SET 
                 return_status = 'shipped_back',
                 return_tracking_number = ?,
                 return_shipped_at = CURRENT_TIMESTAMP 
                 WHERE id = ?""", (tracking_number, order_id))
    conn.commit()
    conn.close()
    
    flash('Return shipment marked! The seller will process your refund.', 'success')
    return redirect(f'/order/{order_id}')

@app.route('/order/<int:order_id>/return/refund', methods=['POST'])
def refund_return(order_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT seller_id, return_status, stripe_payment_id, amount, shipping_cost, seller_at_fault FROM orders WHERE id = ?", (order_id,))
    order = c.fetchone()
    
    if not order:
        conn.close()
        return 'Order not found', 404
    
    # Only seller or admin can issue refund
    if session.get('username') != 'admin' and order[0] != session['user_id']:
        conn.close()
        return 'Access denied', 403
    
    if order[1] != 'shipped_back':
        conn.close()
        flash('Return must be approved before refund.', 'warning')
        return redirect(f'/order/{order_id}')
    
    total_amount = order[3] or 0
    shipping_cost = order[4] or 0
    seller_at_fault = order[5] or 0
    
    # Calculate refund:
    # - Seller at fault: refund = item_price + 2x shipping (full refund + extra for return shipping)
    # - Buyer at fault: refund = item_price only (buyer pays return shipping)
    item_price = total_amount - shipping_cost
    if seller_at_fault:
        refund_amount = item_price + (shipping_cost * 2)
    else:
        refund_amount = item_price
    
    # Process Stripe refund if payment exists
    if order[2] and app.config.get('STRIPE_SECRET_KEY'):
        try:
            stripe.Refund.create(payment_intent=order[2], amount=int(refund_amount * 100))
            if seller_at_fault:
                flash(f'Refund issued: ${refund_amount:.2f} (item ${item_price:.2f} + return shipping ${shipping_cost:.2f} x2)', 'success')
            else:
                flash(f'Refund issued: ${refund_amount:.2f} (item price, buyer pays return shipping)', 'success')
        except Exception as e:
            flash(f'Stripe refund failed: {str(e)}', 'danger')
            conn.close()
            return redirect(f'/order/{order_id}')
    else:
        if seller_at_fault:
            flash(f'Refund issued: ${refund_amount:.2f} (item ${item_price:.2f} + return shipping ${shipping_cost:.2f} x2)', 'success')
        else:
            flash(f'Refund issued: ${refund_amount:.2f} (item price, buyer pays return shipping)', 'success')
    
    c.execute("""UPDATE orders SET 
                 return_status = 'completed',
                 return_completed_at = CURRENT_TIMESTAMP,
                 status = 'refunded'
                 WHERE id = ?""", (order_id,))
    
    # Notify buyer of refund
    c.execute("""SELECT buyer.email, buyer.email_notifications, buyer.notify_return, p.title
                 FROM orders o
                 JOIN users buyer ON o.buyer_id = buyer.id
                 JOIN posts p ON o.post_id = p.id
                 WHERE o.id = ?""", (order_id,))
    buyer_info = c.fetchone()
    if buyer_info and buyer_info[1] and buyer_info[2]:
        send_email(buyer_info[0], 'Refund Issued - Marketplace', 
                  f'Your refund of ${refund_amount:.2f} for "{buyer_info[3]}" has been processed. The refund will appear on your payment method within 5-10 business days.')
    
    conn.commit()
    conn.close()
    
    return redirect(f'/order/{order_id}')

# One-time migration: update image paths
conn = sqlite3.connect('database.db')
c = conn.cursor()
c.execute("UPDATE posts SET image = REPLACE(image, '/static/uploads/', '/static/pictures/') WHERE image LIKE '/static/uploads/%'")
c.execute("UPDATE users SET profile_picture = REPLACE(profile_picture, '/static/uploads/', '/static/pictures/') WHERE profile_picture LIKE '/static/uploads/%'")
c.execute("UPDATE messages SET attachment = REPLACE(attachment, '/static/uploads/', '/static/pictures/') WHERE attachment LIKE '/static/uploads/%'")
conn.commit()
conn.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)