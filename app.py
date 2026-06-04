import os
from datetime import datetime, date, time
from functools import wraps

import pymysql
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from config import Config

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'doc', 'docx'}
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
REACTION_EMOJIS = ['👍', '❤️', '🔥', '👏', '🎉', '😊']
ROLES = {'admin': 'Администратор', 'editor': 'Редактор', 'employee': 'Сотрудник'}

app = Flask(__name__)
app.config.from_object(Config)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def connect(with_db=True):
    kwargs = dict(
        host=app.config['MYSQL_HOST'],
        port=app.config['MYSQL_PORT'],
        user=app.config['MYSQL_USER'],
        password=app.config['MYSQL_PASSWORD'],
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )
    if with_db:
        kwargs['database'] = app.config['MYSQL_DATABASE']
    return pymysql.connect(**kwargs)


def table_columns(cur, table):
    cur.execute(f"SHOW COLUMNS FROM `{table}`")
    return {row['Field'] for row in cur.fetchall()}


def ensure_column(cur, table, column, ddl):
    if column not in table_columns(cur, table):
        cur.execute(f"ALTER TABLE `{table}` ADD COLUMN {ddl}")


def init_db():
    db_name = app.config['MYSQL_DATABASE']
    with connect(with_db=False) as conn, conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")

    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(80) NOT NULL UNIQUE,
                full_name VARCHAR(160) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role ENUM('admin','editor','employee') NOT NULL DEFAULT 'employee',
                email VARCHAR(160), department VARCHAR(120), position VARCHAR(120), phone VARCHAR(40),
                avatar_path VARCHAR(255), about TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(120) NOT NULL UNIQUE,
                description VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(220) NOT NULL,
                short_text VARCHAR(350) NOT NULL,
                body TEXT NOT NULL,
                category_id INT NOT NULL,
                author_id INT NOT NULL,
                image_path VARCHAR(255),
                department VARCHAR(120),
                published_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NULL,
                is_important BOOLEAN NOT NULL DEFAULT FALSE,
                FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT,
                FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE,
                INDEX idx_posts_published_at (published_at),
                FULLTEXT KEY ft_posts_search (title, short_text, body)
            ) ENGINE=InnoDB
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS post_likes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                post_id INT NOT NULL, user_id INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_post_like (post_id, user_id),
                FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS post_reactions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                post_id INT NOT NULL, user_id INT NOT NULL, emoji VARCHAR(10) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_post_reaction (post_id, user_id, emoji),
                FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id INT AUTO_INCREMENT PRIMARY KEY,
                post_id INT NOT NULL, user_id INT NOT NULL, parent_id INT NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                INDEX idx_comments_post_id (post_id), INDEX idx_comments_parent_id (parent_id)
            ) ENGINE=InnoDB
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS post_photos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                post_id INT NOT NULL, file_path VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
                INDEX idx_post_photos_post_id (post_id)
            ) ENGINE=InnoDB
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(80) NOT NULL UNIQUE
            ) ENGINE=InnoDB
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS post_tags (
                post_id INT NOT NULL, tag_id INT NOT NULL,
                PRIMARY KEY (post_id, tag_id),
                FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            ) ENGINE=InnoDB
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(220) NOT NULL,
                description TEXT,
                event_date DATE NOT NULL,
                event_time TIME NULL,
                location VARCHAR(180),
                department VARCHAR(120),
                created_by INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE,
                INDEX idx_events_date (event_date)
            ) ENGINE=InnoDB
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS post_views (
                id INT AUTO_INCREMENT PRIMARY KEY,
                post_id INT NOT NULL,
                user_id INT NULL,
                viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
                INDEX idx_post_views_post_id (post_id)
            ) ENGINE=InnoDB
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS portal_settings (
                setting_key VARCHAR(80) PRIMARY KEY,
                setting_value TEXT
            ) ENGINE=InnoDB
        """)

        for col, ddl in {
            'email': 'email VARCHAR(160) NULL', 'department': 'department VARCHAR(120) NULL',
            'position': 'position VARCHAR(120) NULL', 'phone': 'phone VARCHAR(40) NULL',
            'avatar_path': 'avatar_path VARCHAR(255) NULL', 'about': 'about TEXT NULL'
        }.items():
            ensure_column(cur, 'users', col, ddl)
        ensure_column(cur, 'posts', 'department', 'department VARCHAR(120) NULL')
        ensure_column(cur, 'comments', 'parent_id', 'parent_id INT NULL')

        cur.execute("SELECT COUNT(*) AS total FROM users")
        if cur.fetchone()['total'] == 0:
            users = [
                ('admin', 'Администратор портала', generate_password_hash('admin123'), 'admin', 'Администрация', 'Руководитель портала'),
                ('editor', 'Редактор новостей', generate_password_hash('editor123'), 'editor', 'PR-отдел', 'Редактор'),
                ('employee', 'Сотрудник компании', generate_password_hash('employee123'), 'employee', 'IT-отдел', 'Специалист'),
            ]
            cur.executemany("INSERT INTO users(username, full_name, password_hash, role, department, position) VALUES (%s,%s,%s,%s,%s,%s)", users)

        cur.execute("SELECT COUNT(*) AS total FROM categories")
        if cur.fetchone()['total'] == 0:
            categories = [
                ('Новости компании', 'Основные события организации'), ('Объявления', 'Важные объявления для сотрудников'),
                ('IT-уведомления', 'Сообщения IT-отдела'), ('Кадровая информация', 'Информация отдела персонала'),
                ('Важные сообщения', 'Срочные и приоритетные публикации'),
            ]
            cur.executemany("INSERT INTO categories(name, description) VALUES (%s,%s)", categories)

        cur.execute("SELECT COUNT(*) AS total FROM posts")
        if cur.fetchone()['total'] == 0:
            cur.execute("SELECT id FROM users WHERE username='admin'")
            admin_id = cur.fetchone()['id']
            cur.execute("SELECT id FROM categories WHERE name='Новости компании'")
            cat_id = cur.fetchone()['id']
            cur.execute("""
                INSERT INTO posts(title, short_text, body, category_id, author_id, is_important, department)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                'Добро пожаловать на корпоративный портал',
                'Здесь публикуются новости, объявления, события и уведомления компании.',
                'Корпоративный портал используется для информирования сотрудников, обсуждения публикаций, просмотра событий и работы с внутренними материалами.',
                cat_id, admin_id, True, 'Все подразделения'
            ))

        defaults = {
            'notifications_enabled': '1',
            'notification_email': '',
            'notification_text': 'Уведомления о важных корпоративных новостях включены.'
        }
        for key, value in defaults.items():
            cur.execute("INSERT IGNORE INTO portal_settings(setting_key, setting_value) VALUES (%s,%s)", (key, value))


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def is_image(filename):
    return filename and '.' in filename and filename.rsplit('.', 1)[1].lower() in IMAGE_EXTENSIONS


def current_user():
    if 'user_id' not in session:
        return None
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, username, full_name, role, email, department, position, phone, avatar_path, about, created_at FROM users WHERE id=%s", (session['user_id'],))
        return cur.fetchone()


@app.context_processor
def inject_user():
    user = current_user()
    settings = {
        'notifications_enabled': '1',
        'notification_text': 'Опубликована важная корпоративная новость.'
    }
    latest_important_post = None

    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT setting_key, setting_value
            FROM portal_settings
            WHERE setting_key IN ('notifications_enabled', 'notification_text')
        """)
        for row in cur.fetchall():
            settings[row['setting_key']] = row['setting_value']

        if user:
            cur.execute("""
                SELECT id, title, short_text
                FROM posts
                WHERE is_important=1
                ORDER BY published_at DESC
                LIMIT 1
            """)
            latest_important_post = cur.fetchone()

    return {
        'current_user': user,
        'now': datetime.now,
        'reaction_emojis': REACTION_EMOJIS,
        'roles': ROLES,
        'notification_settings': settings,
        'latest_important_post': latest_important_post,
    }


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('Войдите в систему, чтобы открыть портал.', 'warning')
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper


def roles_required(*roles):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user or user['role'] not in roles:
                abort(403)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def get_departments(cur):
    cur.execute("""
        SELECT department FROM users WHERE department IS NOT NULL AND department<>''
        UNION
        SELECT department FROM posts WHERE department IS NOT NULL AND department<>''
        UNION
        SELECT department FROM events WHERE department IS NOT NULL AND department<>''
        ORDER BY department
    """)
    return [row['department'] for row in cur.fetchall()]


def parse_tags(text):
    raw = text.replace('#', '').replace(';', ',').split(',')
    tags = []
    for item in raw:
        tag = item.strip().lower()
        if tag and tag not in tags:
            tags.append(tag[:80])
    return tags[:12]


def sync_post_tags(cur, post_id, tag_text):
    cur.execute("DELETE FROM post_tags WHERE post_id=%s", (post_id,))
    for tag in parse_tags(tag_text):
        cur.execute("INSERT IGNORE INTO tags(name) VALUES (%s)", (tag,))
        cur.execute("SELECT id FROM tags WHERE name=%s", (tag,))
        tag_id = cur.fetchone()['id']
        cur.execute("INSERT IGNORE INTO post_tags(post_id, tag_id) VALUES (%s,%s)", (post_id, tag_id))


def get_post_tags(cur, post_id):
    cur.execute("""
        SELECT t.name FROM tags t
        JOIN post_tags pt ON pt.tag_id=t.id
        WHERE pt.post_id=%s ORDER BY t.name
    """, (post_id,))
    return [row['name'] for row in cur.fetchall()]


def enrich_posts(posts):
    if not posts:
        return posts
    with connect() as conn, conn.cursor() as cur:
        for post in posts:
            cur.execute("SELECT emoji, COUNT(*) AS cnt FROM post_reactions WHERE post_id=%s GROUP BY emoji ORDER BY cnt DESC, emoji", (post['id'],))
            post['reaction_summary'] = cur.fetchall()
            post['tags'] = get_post_tags(cur, post['id'])
    return posts


def get_post(post_id, user_id=None):
    if user_id is None:
        user_id = session.get('user_id', 0)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT p.*, c.name AS category_name, u.full_name AS author_name, u.id AS author_id,
                   (SELECT COUNT(*) FROM post_likes pl WHERE pl.post_id = p.id) AS likes_count,
                   (SELECT COUNT(*) FROM comments cm WHERE cm.post_id = p.id) AS comments_count,
                   (SELECT COUNT(*) FROM post_views pv WHERE pv.post_id = p.id) AS views_count,
                   EXISTS(SELECT 1 FROM post_likes pl2 WHERE pl2.post_id = p.id AND pl2.user_id = %s) AS current_user_liked
            FROM posts p
            JOIN categories c ON c.id = p.category_id
            JOIN users u ON u.id = p.author_id
            WHERE p.id=%s
        """, (user_id, post_id))
        post = cur.fetchone()
        if not post:
            return None
        cur.execute("""
            SELECT emoji, COUNT(*) AS cnt, MAX(CASE WHEN user_id=%s THEN 1 ELSE 0 END) AS reacted_by_me
            FROM post_reactions WHERE post_id=%s GROUP BY emoji ORDER BY cnt DESC, emoji
        """, (user_id, post_id))
        post['reaction_summary'] = cur.fetchall()
        post['tags'] = get_post_tags(cur, post_id)
    return post


@app.route('/uploads/<path:filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE username=%s", (username,))
            user = cur.fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            flash('Вы успешно вошли в систему.', 'success')
            return redirect(url_for('index'))
        flash('Неверный логин или пароль.', 'danger')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    flash('Самостоятельная регистрация отключена. Учётные записи сотрудников создаёт администратор портала.', 'info')
    return redirect(url_for('login'))


@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    q = request.args.get('q', '').strip()
    category_id = request.args.get('category', '').strip()
    department = request.args.get('department', '').strip()
    tag = request.args.get('tag', '').strip().lower()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    user_id = session.get('user_id', 0)

    where = []
    params = [user_id]
    if q:
        where.append("(p.title LIKE %s OR p.short_text LIKE %s OR p.body LIKE %s)")
        params.extend([f'%{q}%', f'%{q}%', f'%{q}%'])
    if category_id:
        where.append("p.category_id=%s")
        params.append(category_id)
    if department:
        where.append("(p.department=%s OR p.department='Все подразделения' OR p.department IS NULL OR p.department='')")
        params.append(department)
    if tag:
        where.append("EXISTS(SELECT 1 FROM post_tags pt JOIN tags t ON t.id=pt.tag_id WHERE pt.post_id=p.id AND t.name=%s)")
        params.append(tag)
    if date_from:
        where.append("DATE(p.published_at) >= %s")
        params.append(date_from)
    if date_to:
        where.append("DATE(p.published_at) <= %s")
        params.append(date_to)

    sql = """
        SELECT p.*, c.name AS category_name, u.full_name AS author_name,
               (SELECT COUNT(*) FROM post_likes pl WHERE pl.post_id = p.id) AS likes_count,
               (SELECT COUNT(*) FROM comments cm WHERE cm.post_id = p.id) AS comments_count,
               (SELECT COUNT(*) FROM post_views pv WHERE pv.post_id = p.id) AS views_count,
               EXISTS(SELECT 1 FROM post_likes pl2 WHERE pl2.post_id = p.id AND pl2.user_id = %s) AS current_user_liked
        FROM posts p
        JOIN categories c ON c.id = p.category_id
        JOIN users u ON u.id = p.author_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.is_important DESC, p.published_at DESC"

    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        posts = cur.fetchall()
        cur.execute("""
            SELECT c.*, COUNT(p.id) AS posts_count
            FROM categories c LEFT JOIN posts p ON p.category_id = c.id
            GROUP BY c.id ORDER BY c.name
        """)
        categories = cur.fetchall()
        cur.execute("SELECT COUNT(*) AS total FROM posts")
        posts_total = cur.fetchone()['total']
        departments = get_departments(cur)
        cur.execute("SELECT t.name, COUNT(pt.post_id) AS cnt FROM tags t LEFT JOIN post_tags pt ON pt.tag_id=t.id GROUP BY t.id ORDER BY cnt DESC, t.name LIMIT 20")
        tags = cur.fetchall()
    enrich_posts(posts)
    return render_template('index.html', posts=posts, categories=categories, departments=departments, tags=tags, filters=request.args, posts_total=posts_total)


@app.route('/post/<int:post_id>')
@login_required
def post_detail(post_id):
    user_id = session.get('user_id')
    with connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO post_views(post_id, user_id) VALUES (%s,%s)", (post_id, user_id))
    post = get_post(post_id)
    if not post:
        abort(404)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT c.id, c.parent_id, c.body, c.created_at, u.full_name, u.role, u.avatar_path, u.id AS user_id
            FROM comments c JOIN users u ON u.id = c.user_id
            WHERE c.post_id=%s ORDER BY c.created_at ASC
        """, (post_id,))
        all_comments = cur.fetchall()
        cur.execute("SELECT id, file_path FROM post_photos WHERE post_id=%s ORDER BY id", (post_id,))
        photos = cur.fetchall()
    comments = [c for c in all_comments if c['parent_id'] is None]
    replies = {}
    for c in all_comments:
        if c['parent_id'] is not None:
            replies.setdefault(c['parent_id'], []).append(c)
    return render_template('post_detail.html', post=post, comments=comments, replies=replies, photos=photos)


@app.route('/post/new', methods=['GET', 'POST'])
@login_required
@roles_required('admin', 'editor')
def post_new():
    return save_post()


@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
@roles_required('admin', 'editor')
def post_edit(post_id):
    return save_post(post_id)


def save_uploaded_image(prefix, file):
    if file and file.filename and is_image(file.filename):
        filename = f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{secure_filename(file.filename)}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return filename
    return None


def save_post_photos(cur, post_id, files, set_cover_if_empty=False):
    saved = []
    for file in files:
        filename = save_uploaded_image(f"post_{post_id}", file)
        if filename:
            cur.execute("INSERT INTO post_photos(post_id, file_path) VALUES (%s,%s)", (post_id, filename))
            saved.append(filename)
    if saved and set_cover_if_empty:
        cur.execute("UPDATE posts SET image_path=%s WHERE id=%s AND (image_path IS NULL OR image_path='')", (saved[0], post_id))
    return saved


def save_post(post_id=None):
    user = current_user()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM categories ORDER BY name")
        categories = cur.fetchall()
        departments = get_departments(cur)
        post = None
        tag_string = ''
        if post_id:
            cur.execute("SELECT * FROM posts WHERE id=%s", (post_id,))
            post = cur.fetchone()
            if not post:
                abort(404)
            if user['role'] != 'admin' and post['author_id'] != user['id']:
                abort(403)
            tag_string = ', '.join(get_post_tags(cur, post_id))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        short_text = request.form.get('short_text', '').strip()
        body = request.form.get('body', '').strip()
        category_id = request.form.get('category_id')
        department = request.form.get('department', '').strip() or 'Все подразделения'
        tags = request.form.get('tags', '').strip()
        is_important = 1 if request.form.get('is_important') else 0
        image_path = post['image_path'] if post else None

        file = request.files.get('image')
        if file and file.filename:
            if not allowed_file(file.filename):
                flash('Недопустимый формат файла.', 'danger')
                return render_template('post_form.html', categories=categories, departments=departments, post=post, tag_string=tag_string)
            filename = f"main_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{secure_filename(file.filename)}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_path = filename

        if not title or not short_text or not body or not category_id:
            flash('Заполните обязательные поля.', 'warning')
            return render_template('post_form.html', categories=categories, departments=departments, post=post, tag_string=tags)

        with connect() as conn, conn.cursor() as cur:
            if post_id:
                cur.execute("""
                    UPDATE posts SET title=%s, short_text=%s, body=%s, category_id=%s, department=%s,
                    image_path=%s, is_important=%s, updated_at=NOW() WHERE id=%s
                """, (title, short_text, body, category_id, department, image_path, is_important, post_id))
                sync_post_tags(cur, post_id, tags)
                save_post_photos(cur, post_id, request.files.getlist('photos'), set_cover_if_empty=True)
                flash('Новость обновлена.', 'success')
            else:
                cur.execute("""
                    INSERT INTO posts(title, short_text, body, category_id, author_id, image_path, is_important, department)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """, (title, short_text, body, category_id, user['id'], image_path, is_important, department))
                new_id = cur.lastrowid
                sync_post_tags(cur, new_id, tags)
                if image_path and is_image(image_path):
                    cur.execute("INSERT INTO post_photos(post_id, file_path) VALUES (%s,%s)", (new_id, image_path))
                save_post_photos(cur, new_id, request.files.getlist('photos'), set_cover_if_empty=True)
                flash('Новость опубликована.', 'success')
        return redirect(url_for('index'))
    return render_template('post_form.html', categories=categories, departments=departments, post=post, tag_string=tag_string)


@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
@roles_required('admin', 'editor')
def post_delete(post_id):
    user = current_user()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM posts WHERE id=%s", (post_id,))
        post = cur.fetchone()
        if not post:
            abort(404)
        if user['role'] != 'admin' and post['author_id'] != user['id']:
            abort(403)
        cur.execute("DELETE FROM posts WHERE id=%s", (post_id,))
    flash('Новость удалена.', 'info')
    return redirect(url_for('index'))


@app.route('/post/<int:post_id>/like', methods=['POST'])
@login_required
def post_like(post_id):
    user_id = session['user_id']
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM posts WHERE id=%s", (post_id,))
        if not cur.fetchone(): abort(404)
        cur.execute("SELECT id FROM post_likes WHERE post_id=%s AND user_id=%s", (post_id, user_id))
        exists = cur.fetchone()
        if exists:
            cur.execute("DELETE FROM post_likes WHERE id=%s", (exists['id'],))
        else:
            cur.execute("INSERT INTO post_likes(post_id, user_id) VALUES (%s,%s)", (post_id, user_id))
    return redirect(request.args.get('next') or request.referrer or url_for('post_detail', post_id=post_id))


@app.route('/post/<int:post_id>/reaction', methods=['POST'])
@login_required
def post_reaction(post_id):
    user_id = session['user_id']
    emoji = request.form.get('emoji', '')
    if emoji not in REACTION_EMOJIS:
        flash('Недопустимая реакция.', 'warning')
        return redirect(request.args.get('next') or request.referrer or url_for('post_detail', post_id=post_id))
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM posts WHERE id=%s", (post_id,))
        if not cur.fetchone(): abort(404)
        cur.execute("SELECT id FROM post_reactions WHERE post_id=%s AND user_id=%s AND emoji=%s", (post_id, user_id, emoji))
        existing = cur.fetchone()
        if existing:
            cur.execute("DELETE FROM post_reactions WHERE id=%s", (existing['id'],))
        else:
            cur.execute("INSERT INTO post_reactions(post_id, user_id, emoji) VALUES (%s,%s,%s)", (post_id, user_id, emoji))
    return redirect(request.args.get('next') or request.referrer or url_for('post_detail', post_id=post_id))


@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def post_comment(post_id):
    body = request.form.get('body', '').strip()
    parent_id = request.form.get('parent_id') or None
    if not body:
        flash('Комментарий не может быть пустым.', 'warning')
        return redirect(url_for('post_detail', post_id=post_id))
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM posts WHERE id=%s", (post_id,))
        if not cur.fetchone(): abort(404)
        if parent_id:
            cur.execute("SELECT id FROM comments WHERE id=%s AND post_id=%s", (parent_id, post_id))
            if not cur.fetchone(): parent_id = None
        cur.execute("INSERT INTO comments(post_id, user_id, parent_id, body) VALUES (%s,%s,%s,%s)", (post_id, session['user_id'], parent_id, body))
    flash('Комментарий добавлен.', 'success')
    return redirect(url_for('post_detail', post_id=post_id) + '#comments')


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    return employee_profile(session['user_id'], editable=True)


@app.route('/employees')
@login_required
def employees():
    q = request.args.get('q', '').strip()
    department = request.args.get('department', '').strip()
    where, params = [], []
    if q:
        where.append("(full_name LIKE %s OR username LIKE %s OR position LIKE %s OR email LIKE %s)")
        params.extend([f'%{q}%', f'%{q}%', f'%{q}%', f'%{q}%'])
    if department:
        where.append("department=%s")
        params.append(department)
    sql = "SELECT id, username, full_name, role, email, department, position, phone, avatar_path FROM users"
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY full_name"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        users = cur.fetchall()
        departments = get_departments(cur)
    return render_template('employees.html', users=users, departments=departments, filters=request.args)


@app.route('/employee/<int:user_id>')
@login_required
def employee_public(user_id):
    return employee_profile(user_id, editable=False)


def employee_profile(user_id, editable=False):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, username, full_name, role, email, department, position, phone, avatar_path, about, created_at FROM users WHERE id=%s", (user_id,))
        user = cur.fetchone()
        if not user: abort(404)
        cur.execute("SELECT COUNT(*) AS total FROM posts WHERE author_id=%s", (user_id,)); posts_count = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) AS total FROM comments WHERE user_id=%s", (user_id,)); comments_count = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) AS total FROM post_likes WHERE user_id=%s", (user_id,)); likes_count = cur.fetchone()['total']
        cur.execute("""
            SELECT p.id, p.title, p.published_at, c.name AS category_name,
                   (SELECT COUNT(*) FROM post_views pv WHERE pv.post_id=p.id) AS views_count
            FROM posts p JOIN categories c ON c.id=p.category_id
            WHERE p.author_id=%s ORDER BY p.published_at DESC LIMIT 10
        """, (user_id,))
        authored_posts = cur.fetchall()
        cur.execute("""
            SELECT 'comment' AS type, c.created_at AS created_at, p.id AS post_id, p.title AS post_title, c.body AS text
            FROM comments c JOIN posts p ON p.id=c.post_id WHERE c.user_id=%s
            UNION ALL
            SELECT 'like' AS type, pl.created_at AS created_at, p.id AS post_id, p.title AS post_title, '' AS text
            FROM post_likes pl JOIN posts p ON p.id=pl.post_id WHERE pl.user_id=%s
            ORDER BY created_at DESC LIMIT 12
        """, (user_id, user_id))
        activity = cur.fetchall()

    if editable and request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        department = request.form.get('department', '').strip()
        position = request.form.get('position', '').strip()
        phone = request.form.get('phone', '').strip()
        about = request.form.get('about', '').strip()
        avatar_path = user.get('avatar_path')
        file = request.files.get('avatar')
        if file and file.filename:
            filename = save_uploaded_image(f"avatar_{user_id}", file)
            if not filename:
                flash('Для профиля можно загрузить только изображение.', 'danger')
                return redirect(url_for('profile'))
            avatar_path = filename
        if not full_name:
            flash('ФИО не может быть пустым.', 'warning')
            return redirect(url_for('profile'))
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE users SET full_name=%s, email=%s, department=%s, position=%s, phone=%s, about=%s, avatar_path=%s
                WHERE id=%s
            """, (full_name, email, department, position, phone, about, avatar_path, user_id))
        flash('Профиль обновлён.', 'success')
        return redirect(url_for('profile'))

    stats = {'posts_count': posts_count, 'comments_count': comments_count, 'likes_count': likes_count}
    return render_template('profile.html', user=user, stats=stats, editable=editable, authored_posts=authored_posts, activity=activity)


@app.route('/events', methods=['GET', 'POST'])
@login_required
def events():
    user = current_user()
    if request.method == 'POST':
        if user['role'] not in ['admin', 'editor']:
            abort(403)
        title = request.form.get('title', '').strip()
        event_date = request.form.get('event_date', '').strip()
        event_time = request.form.get('event_time', '').strip() or None
        location = request.form.get('location', '').strip()
        department = request.form.get('department', '').strip() or 'Все подразделения'
        description = request.form.get('description', '').strip()
        if not title or not event_date:
            flash('Укажите название и дату события.', 'warning')
            return redirect(url_for('events'))
        with connect() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO events(title, description, event_date, event_time, location, department, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (title, description, event_date, event_time, location, department, user['id']))
        flash('Событие добавлено.', 'success')
        return redirect(url_for('events'))
    month = request.args.get('month', '').strip()
    department = request.args.get('department', '').strip()
    where, params = [], []
    if month:
        where.append("DATE_FORMAT(event_date, '%%Y-%%m')=%s"); params.append(month)
    if department:
        where.append("(department=%s OR department='Все подразделения')"); params.append(department)
    sql = "SELECT e.*, u.full_name AS author_name FROM events e JOIN users u ON u.id=e.created_by"
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY event_date ASC, event_time ASC"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        events_list = cur.fetchall()
        departments = get_departments(cur)
    return render_template('events.html', events=events_list, departments=departments, filters=request.args)


@app.route('/events/<int:event_id>/delete', methods=['POST'])
@login_required
@roles_required('admin', 'editor')
def event_delete(event_id):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM events WHERE id=%s", (event_id,))
    flash('Событие удалено.', 'info')
    return redirect(url_for('events'))


@app.route('/search')
@login_required
def portal_search():
    q = request.args.get('q', '').strip()
    results = {'posts': [], 'users': [], 'events': []}
    if q:
        like = f'%{q}%'
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT p.id, p.title, p.short_text, p.published_at, c.name AS category_name
                FROM posts p JOIN categories c ON c.id=p.category_id
                WHERE p.title LIKE %s OR p.short_text LIKE %s OR p.body LIKE %s
                ORDER BY p.published_at DESC LIMIT 20
            """, (like, like, like))
            results['posts'] = cur.fetchall()
            cur.execute("""
                SELECT id, full_name, username, department, position, avatar_path FROM users
                WHERE full_name LIKE %s OR username LIKE %s OR department LIKE %s OR position LIKE %s OR email LIKE %s
                ORDER BY full_name LIMIT 20
            """, (like, like, like, like, like))
            results['users'] = cur.fetchall()
            cur.execute("""
                SELECT id, title, description, event_date, event_time, location, department FROM events
                WHERE title LIKE %s OR description LIKE %s OR location LIKE %s OR department LIKE %s
                ORDER BY event_date DESC LIMIT 20
            """, (like, like, like, like))
            results['events'] = cur.fetchall()
    return render_template('search.html', q=q, results=results)


@app.route('/admin/dashboard')
@login_required
@roles_required('admin')
def admin_dashboard():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM posts"); posts_total = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) AS total FROM users"); users_total = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) AS total FROM comments"); comments_total = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) AS total FROM post_views"); views_total = cur.fetchone()['total']
        cur.execute("""
            SELECT p.id, p.title, COUNT(v.id) AS views_count
            FROM posts p LEFT JOIN post_views v ON v.post_id=p.id
            GROUP BY p.id ORDER BY views_count DESC, p.published_at DESC LIMIT 8
        """)
        popular_posts = cur.fetchall()
        cur.execute("""
            SELECT COALESCE(NULLIF(p.department,''),'Все подразделения') AS department, COUNT(*) AS cnt
            FROM posts p GROUP BY COALESCE(NULLIF(p.department,''),'Все подразделения') ORDER BY cnt DESC
        """)
        popular_departments = cur.fetchall()
        cur.execute("""
            SELECT c.name, COUNT(p.id) AS cnt FROM categories c
            LEFT JOIN posts p ON p.category_id=c.id GROUP BY c.id ORDER BY cnt DESC
        """)
        popular_categories = cur.fetchall()
        cur.execute("""
            SELECT u.id, u.full_name, u.department,
                   COUNT(DISTINCT p.id) AS posts_count,
                   COUNT(DISTINCT cm.id) AS comments_count,
                   COUNT(DISTINCT pl.id) AS likes_count
            FROM users u
            LEFT JOIN posts p ON p.author_id=u.id
            LEFT JOIN comments cm ON cm.user_id=u.id
            LEFT JOIN post_likes pl ON pl.user_id=u.id
            GROUP BY u.id ORDER BY (posts_count + comments_count + likes_count) DESC LIMIT 10
        """)
        employee_activity = cur.fetchall()
    stats = {'posts_total': posts_total, 'users_total': users_total, 'comments_total': comments_total, 'views_total': views_total}
    return render_template('admin_dashboard.html', stats=stats, popular_posts=popular_posts, popular_departments=popular_departments, popular_categories=popular_categories, employee_activity=employee_activity)


@app.route('/admin/categories', methods=['GET', 'POST'])
@login_required
@roles_required('admin', 'editor')
def categories_admin():
    with connect() as conn, conn.cursor() as cur:
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            if name:
                try:
                    cur.execute("INSERT INTO categories(name, description) VALUES (%s,%s)", (name, description))
                    flash('Категория добавлена.', 'success')
                except pymysql.err.IntegrityError:
                    flash('Такая категория уже существует.', 'warning')
            return redirect(url_for('categories_admin'))
        cur.execute("SELECT * FROM categories ORDER BY name")
        categories = cur.fetchall()
    return render_template('categories.html', categories=categories)


@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
def users_admin():
    with connect() as conn, conn.cursor() as cur:
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            full_name = request.form.get('full_name', '').strip()
            password = request.form.get('password', '')
            role = request.form.get('role', 'employee')
            department = request.form.get('department', '').strip()
            position = request.form.get('position', '').strip()
            if username and full_name and password and role in ROLES:
                try:
                    cur.execute("""
                        INSERT INTO users(username, full_name, password_hash, role, department, position)
                        VALUES (%s,%s,%s,%s,%s,%s)
                    """, (username, full_name, generate_password_hash(password), role, department, position))
                    flash('Пользователь создан.', 'success')
                except pymysql.err.IntegrityError:
                    flash('Пользователь с таким логином уже существует.', 'warning')
            return redirect(url_for('users_admin'))
        cur.execute("SELECT id, username, full_name, role, email, department, position, created_at FROM users ORDER BY id")
        users = cur.fetchall()
    return render_template('users.html', users=users)


@app.route('/admin/users/<int:user_id>/role', methods=['POST'])
@login_required
@roles_required('admin')
def user_role_update(user_id):
    role = request.form.get('role')
    if role not in ROLES:
        flash('Некорректная роль.', 'warning')
        return redirect(url_for('users_admin'))
    with connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET role=%s WHERE id=%s", (role, user_id))
    flash('Роль пользователя обновлена.', 'success')
    return redirect(url_for('users_admin'))


@app.route('/admin/content')
@login_required
@roles_required('admin', 'editor')
def admin_content():
    user = current_user()
    with connect() as conn, conn.cursor() as cur:
        sql = """
            SELECT p.id, p.title, p.published_at, p.is_important, p.department, c.name AS category_name, u.full_name AS author_name,
                   (SELECT COUNT(*) FROM post_views pv WHERE pv.post_id=p.id) AS views_count,
                   (SELECT COUNT(*) FROM comments cm WHERE cm.post_id=p.id) AS comments_count
            FROM posts p JOIN categories c ON c.id=p.category_id JOIN users u ON u.id=p.author_id
        """
        params = []
        if user['role'] != 'admin':
            sql += " WHERE p.author_id=%s"; params.append(user['id'])
        sql += " ORDER BY p.published_at DESC"
        cur.execute(sql, params)
        posts = cur.fetchall()
    return render_template('admin_content.html', posts=posts)


@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
def admin_settings():
    with connect() as conn, conn.cursor() as cur:
        if request.method == 'POST':
            values = {
                'notifications_enabled': '1' if request.form.get('notifications_enabled') else '0',
                'notification_text': request.form.get('notification_text', '').strip() or 'Опубликована важная корпоративная новость.',
            }
            for key, value in values.items():
                cur.execute("REPLACE INTO portal_settings(setting_key, setting_value) VALUES (%s,%s)", (key, value))
            flash('Настройки всплывающих оповещений сохранены.', 'success')
            return redirect(url_for('admin_settings'))
        cur.execute("SELECT setting_key, setting_value FROM portal_settings")
        settings = {row['setting_key']: row['setting_value'] for row in cur.fetchall()}
    return render_template('admin_settings.html', settings=settings)


@app.errorhandler(403)
def forbidden(_):
    return render_template('error.html', code=403, message='Недостаточно прав для выполнения действия.'), 403


@app.errorhandler(404)
def not_found(_):
    return render_template('error.html', code=404, message='Страница не найдена.'), 404


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
