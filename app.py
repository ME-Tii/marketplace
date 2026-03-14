from flask import Flask, request, redirect, url_for, render_template, session, flash, send_from_directory, Response
import sqlite3
import os
import logging
import mimetypes
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

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key_change_this')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['STRIPE_PUBLIC_KEY'] = os.environ.get('STRIPE_PUBLIC_KEY', 'pk_test_51T8PWW8gWUxTvhfMrWiSGibJDmrQslPZlxNN25Gpxup3pBVQoBg50DGh3pIGbXfJdIhfyzJ1G9bMraRfcIraBjSL00wJ9BQESt')
app.config['STRIPE_SECRET_KEY'] = os.environ.get('STRIPE_SECRET_KEY', '')
app.config['STRIPE_CONNECT_CLIENT_ID'] = os.environ.get('STRIPE_CONNECT_CLIENT_ID', '')
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
            conn.commit()
            conn.close()
    
    return '', 200

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}

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
    c.execute("INSERT OR IGNORE INTO users (username, email, password) VALUES (?, ?, ?)", ('admin', 'admin@example.com', generate_password_hash('admin123')))
    c.execute('''CREATE TABLE IF NOT EXISTS posts
                 (id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, description TEXT, type TEXT, image TEXT, links TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    try:
        c.execute("ALTER TABLE posts ADD COLUMN price REAL")
    except sqlite3.OperationalError:
        pass  # column already exists
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
        c.execute("ALTER TABLE orders ADD COLUMN dispute_status TEXT")
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


@app.route('/terms')
def terms():
    return render_template('terms.html', unread_messages=get_unread_messages_count(session.get('user_id')))

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
    
    return redirect('/profile')

@app.route('/disconnect/stripe')
def disconnect_stripe():
    if 'user_id' not in session:
        return redirect('/login')
    
    user_id = session['user_id']
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("UPDATE users SET stripe_account_id = NULL WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    flash('Stripe account disconnected', 'info')
    return redirect('/profile')


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
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, email, password, description) VALUES (?, ?, ?, ?)", (username, email, hashed, description))
        conn.commit()
        return redirect('/login')
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
        c.execute("SELECT id, password, username FROM users WHERE email = ?", (identifier,))
    else:
        c.execute("SELECT id, password, username FROM users WHERE username = ?", (identifier,))
    user = c.fetchone()
    conn.close()
    if user:
        app.logger.info(f"User found: {user[2]}, checking password")
        if check_password_hash(user[1], password):
            session['user_id'] = user[0]
            session['username'] = user[2]
            app.logger.info(f"Login successful for {user[2]}")
            return redirect('/dashboard')
        else:
            app.logger.warning(f"Invalid password for {user[2]}")
    else:
        app.logger.warning(f"User not found for identifier: {identifier}")
    return redirect('/login?error=Invalid credentials')

@app.route('/robots.txt')
def robots_txt():
    return send_from_directory('.', 'robots.txt')

@app.route('/sitemap.xml')
def sitemap():
    from flask import Response
    import datetime
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
        base_query = "SELECT posts.id, posts.title, posts.description, posts.type, posts.image, posts.links, posts.price, posts.timestamp, users.username FROM posts JOIN users ON posts.user_id = users.id"
        conditions = []
        params = []
        if query:
            conditions.append("(posts.title LIKE ? OR posts.description LIKE ? OR users.username LIKE ?)")
            params.extend(['%' + query + '%', '%' + query + '%', '%' + query + '%'])
        if type_filter:
            conditions.append("posts.type = ?")
            params.append(type_filter)
        if conditions:
            base_query += " WHERE " + " AND ".join(conditions)
        base_query += " ORDER BY posts.timestamp DESC"
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
    c.execute("INSERT INTO posts (user_id, title, description, type, image, links, price) VALUES (?, ?, ?, ?, ?, ?, ?)", (session['user_id'], title, description, post_type, image_path, links, price))
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
    # Regular posts
    posts_query = "SELECT posts.id, posts.title, posts.description, posts.type, posts.image, posts.links, posts.price, posts.timestamp FROM posts WHERE posts.user_id = ?"
    params = [user_id]
    if query:
        posts_query += " AND (posts.title LIKE ? OR posts.description LIKE ?)"
        params.extend(['%' + query + '%', '%' + query + '%'])
    posts_query += " ORDER BY posts.timestamp DESC"
    c.execute(posts_query, params)
    posts = c.fetchall()
    # Group posts
    group_posts_query = "SELECT gp.id, gp.title, gp.content, gp.type, gp.image, gp.links, gp.price, gp.created_at, g.name FROM group_posts gp JOIN groups g ON gp.group_id = g.id WHERE gp.user_id = ?"
    params = [user_id]
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
    is_owner = session.get('user_id') == user_id
    success = request.args.get('success')
    total_pages = (total_users + per_page - 1) // per_page if total_users > 0 else 1
    return render_template('profile.html', username=username, posts=posts, group_posts=group_posts, description=description, profile_picture=profile_picture, stripe_account_id=stripe_account_id, is_owner=is_owner, is_noticed=is_noticed, unread_messages=get_unread_messages_count(session.get('user_id')), success=success, all_users=all_users, search_term=search_term, current_page=page, total_pages=total_pages, per_page=per_page, reports=reports, query=query)

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
    c.execute("SELECT id, username, email, description, profile_picture FROM users")
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

    # Import data
    import json
    users = data.get('users', [])
    posts = data.get('posts', [])
    messages = data.get('messages', [])
    groups = data.get('groups', [])
    group_members = data.get('group_members', [])
    group_posts_data = data.get('group_posts', [])
    for u in users:
        try:
            u_list = list(u)
            if u_list[4]:  # profile_picture
                u_list[4] = '/static/pictures/' + os.path.basename(u_list[4])
            c.execute("INSERT INTO users (id, username, email, description, profile_picture) VALUES (?, ?, ?, ?, ?)", u_list)
        except sqlite3.IntegrityError:
            pass
    for p in posts:
        try:
            p_list = list(p)
            if p_list[5]:  # image
                p_list[5] = '/static/pictures/' + os.path.basename(p_list[5])
            c.execute("INSERT INTO posts (id, user_id, title, description, type, image, links, price, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", p_list)
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
            c.execute("INSERT INTO group_posts (id, group_id, user_id, title, content, image, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", gp)
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
        c.execute("SELECT id, username, email, description, profile_picture FROM users")
        users = c.fetchall()
        c.execute("SELECT id, user_id, title, description, type, image, links, price, timestamp FROM posts")
        posts = c.fetchall()
        c.execute("SELECT id, sender_id, receiver_id, message, timestamp FROM messages")
        messages = c.fetchall()
        c.execute("SELECT id, name, description, creator_id, is_private, created_at FROM groups")
        groups = c.fetchall()
        c.execute("SELECT id, group_id, user_id, status, joined_at FROM group_members")
        group_members = c.fetchall()
        c.execute("SELECT id, group_id, user_id, title, content, image, created_at FROM group_posts")
        group_posts_data = c.fetchall()
        conn.close()
        data = {
            'users': users,
            'posts': posts,
            'messages': messages,
            'groups': groups,
            'group_members': group_members,
            'group_posts': group_posts_data
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
        SELECT g.id, g.name, g.description, g.is_private, u.username,
               COUNT(gm.id) as member_count
        FROM groups g
        LEFT JOIN users u ON g.creator_id = u.id
        LEFT JOIN group_members gm ON g.id = gm.group_id AND gm.status = 'accepted'
    """
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
            flash('Successfully joined the group!', 'success')
    except sqlite3.IntegrityError:
        flash('You are already a member or have a pending request.', 'warning')
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
    c.execute("INSERT INTO group_posts (group_id, user_id, title, content, type, image, links, price) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (group_id, session['user_id'], title, content, post_type, image_path, links, price))
    conn.commit()
    conn.close()
    flash('Post created!', 'success')
    return redirect(f'/group/{group_id}')


@app.route('/post/<int:post_id>')
def post_detail(post_id):
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT posts.id, posts.title, posts.description, posts.type, posts.image, posts.links, posts.price, posts.timestamp, users.username FROM posts JOIN users ON posts.user_id = users.id WHERE posts.id = ?", (post_id,))
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
    c.execute("SELECT id, title, description, type, image, links, price FROM posts WHERE id = ? AND user_id = ?", (post_id, session['user_id']))
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
        c.execute("UPDATE posts SET title = ?, description = ?, type = ?, image = ?, links = ?, price = ? WHERE id = ? AND user_id = ?", (title, description, post_type, image_path, links, price, post_id, session['user_id']))
    else:
        c.execute("UPDATE posts SET title = ?, description = ?, type = ?, links = ?, price = ? WHERE id = ? AND user_id = ?", (title, description, post_type, links, price, post_id, session['user_id']))
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

@app.route('/edit_profile')
def edit_profile_page():
    if 'user_id' not in session:
        return redirect('/login')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT description, profile_picture FROM users WHERE id = ?", (session['user_id'],))
    user = c.fetchone()
    conn.close()
    description = user[0] if user else ''
    profile_picture = user[1] if user else None
    error = request.args.get('error')
    return render_template('edit_profile.html', description=description, profile_picture=profile_picture, unread_messages=get_unread_messages_count(session['user_id']), error=error)

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
    if profile_picture_path:
        c.execute("UPDATE users SET description = ?, profile_picture = ? WHERE id = ?", (description, profile_picture_path, session['user_id']))
    else:
        c.execute("UPDATE users SET description = ? WHERE id = ?", (description, session['user_id']))
    conn.commit()
    conn.close()
    if password_error:
        return redirect(f'/edit_profile?error={password_error}')
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

@app.route('/checkout/<int:post_id>')
def checkout(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT title, price, user_id FROM posts WHERE id = ?", (post_id,))
    post = c.fetchone()
    
    if not post or not post[1]:
        conn.close()
        return 'Post not found or has no price', 404
    
    if post[2] == session['user_id']:
        conn.close()
        flash('You cannot buy your own item.', 'warning')
        return redirect(f'/post/{post_id}')
    
    c.execute("SELECT * FROM orders WHERE post_id = ? AND buyer_id = ? AND status = 'pending'", (post_id, session['user_id']))
    existing_order = c.fetchone()
    conn.close()
    
    return render_template('checkout.html', post=post, post_id=post_id, existing_order=existing_order, unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/process_checkout/<int:post_id>', methods=['POST'])
def process_checkout(post_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    full_name = request.form.get('full_name')
    street = request.form.get('street')
    city = request.form.get('city')
    state = request.form.get('state')
    zip_code = request.form.get('zip_code')
    country = request.form.get('country')
    phone = request.form.get('phone')
    save_address = request.form.get('save_address')
    
    if not all([full_name, street, city, zip_code, country, phone]):
        flash('Please fill in all required fields.', 'danger')
        return redirect(f'/checkout/{post_id}')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT title, price, user_id FROM posts WHERE id = ?", (post_id,))
    post = c.fetchone()
    
    if not post or not post[1]:
        conn.close()
        return 'Post not found or has no price', 404
    
    if post[2] == session['user_id']:
        conn.close()
        flash('You cannot buy your own item.', 'warning')
        return redirect(f'/post/{post_id}')
    
    c.execute("INSERT INTO orders (post_id, buyer_id, seller_id, amount, status) VALUES (?, ?, ?, ?, 'pending')",
              (post_id, session['user_id'], post[2], post[1]))
    order_id = c.lastrowid
    
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
    c.execute("SELECT title, price, user_id FROM posts WHERE id = ?", (post_id,))
    post = c.fetchone()
    conn.close()
    
    if not post or not post[1]:
        return 'Post not found or has no price', 404
    
    session.pop('current_order_id', None)
    
    seller_id = post[2]
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT stripe_account_id FROM users WHERE id = ?", (seller_id,))
    seller = c.fetchone()
    conn.close()
    
    transfer_data = None
    if seller and seller[0]:
        transfer_data = {'destination': seller[0]}
    
    try:
        session_params = {
            'payment_method_types': ['card'],
            'line_items': [{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': post[0]
                    },
                    'unit_amount': int(post[1] * 100),
                },
                'quantity': 1,
            }],
            'mode': 'payment',
            'success_url': request.url_root + f'payment_success?post_id={post_id}&order_id={order_id}',
            'cancel_url': request.url_root + f'post/{post_id}',
            'metadata': {'order_id': order_id, 'post_id': post_id}
        }
        
        if transfer_data:
            session_params['transfer_data'] = transfer_data
            session_params['application_fee_amount'] = int(post[1] * 100 * 0.10)  # 10% platform fee
        
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
        conn.commit()
        conn.close()
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT title, price FROM posts WHERE id = ?", (post_id,))
    post = c.fetchone()
    conn.close()
    return render_template('payment_success.html', post=post, order_id=order_id, unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/orders')
def orders():
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("""SELECT o.id, o.post_id, o.buyer_id, o.seller_id, o.amount, o.status, o.created_at,
                 p.title, p.image, u.username as seller_username
                 FROM orders o
                 JOIN posts p ON o.post_id = p.id
                 JOIN users u ON o.seller_id = u.id
                 WHERE o.buyer_id = ? OR o.seller_id = ?
                 ORDER BY o.created_at DESC""", (session['user_id'], session['user_id']))
    orders = c.fetchall()
    conn.close()
    return render_template('orders.html', orders=orders, unread_messages=get_unread_messages_count(session.get('user_id')))

@app.route('/order/<int:order_id>')
def order_detail(order_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("""SELECT o.id, o.post_id, o.buyer_id, o.seller_id, o.amount, o.status, o.created_at,
                 o.tracking_number, o.shipped_at, o.delivered_at, o.dispute_status,
                 p.title, p.image, p.description,
                 buyer.username, buyer.email,
                 seller.username, seller.email,
                 a.full_name, a.street, a.city, a.state, a.zip_code, a.country, a.phone
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