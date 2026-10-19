"""CineSync - Smart Movie Ticket Booking & Resource Allocation System (Flask + MySQL + OS simulator)

Layers (matches the architecture diagram):
  Presentation  -> templates/ + static/
  Application   -> this file: User, Movie&Show, Booking, Report services + API routes
  Database      -> MySQL (database/schema.sql)
  OS Simulator  -> os_module/ (scheduler, synchronization, deadlock)
  External      -> simulated payment gateway + notification outbox
"""
import secrets
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps

import mysql.connector
from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from mysql.connector import Error, pooling
from werkzeug.security import check_password_hash, generate_password_hash

import config
from os_module.deadlock import build_wait_for_graph, detect_deadlock
from os_module.scheduling import schedule
from os_module.sync import simulate_seat_lock

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


# ----------------------------------------------------------------------------------------------
# Database helpers (connection pool = shared, limited resource)
# ----------------------------------------------------------------------------------------------
_pool = None


def db():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(pool_name="cinesync", pool_size=config.POOL_SIZE, **config.DB_CONFIG)
    return _pool.get_connection()


def q(sql, args=(), one=False):
    """Run a SELECT and return dict rows."""
    con = db()
    cur = con.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return cur.fetchone() if one else cur.fetchall()
    finally:
        cur.close()
        con.close()


def run(sql, args=()):
    """Run one INSERT/UPDATE/DELETE in its own transaction; returns lastrowid."""
    con = db()
    cur = con.cursor()
    try:
        cur.execute(sql, args)
        con.commit()
        return cur.lastrowid
    except Exception:
        con.rollback()
        raise
    finally:
        cur.close()
        con.close()


class BookingError(Exception):
    """A business-rule failure that is safe to show to the user."""


# ----------------------------------------------------------------------------------------------
# Template helpers, CSRF protection, error pages
# ----------------------------------------------------------------------------------------------
def _hm(v):
    if isinstance(v, timedelta):
        mins = int(v.total_seconds() // 60)
        return (mins // 60) % 24, mins % 60
    return v.hour, v.minute


@app.template_filter("tfmt")
def tfmt(v):
    h, m = _hm(v)
    return datetime(2000, 1, 1, h, m).strftime("%I:%M %p").lstrip("0")


@app.template_filter("dfmt")
def dfmt(v):
    return v.strftime("%a, %d %b")


@app.template_filter("inr")
def inr(v):
    return "\u20b9{:,.2f}".format(float(v or 0))


@app.template_filter("dtfmt")
def dtfmt(v):
    return v.strftime("%d %b %Y, %I:%M %p")


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def csrf_protect():
    if request.method == "POST":
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        if not secrets.compare_digest(sent, session.get("_csrf", "")):
            abort(400, "Your session expired. Refresh the page and try again.")


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
def http_error(e):
    return render_template("error.html", code=e.code, message=getattr(e, "description", "")), e.code


@app.errorhandler(Error)
def db_error(e):
    app.logger.exception("Database error")
    return render_template("error.html", code=500,
                           message="The database is not reachable. Check config.py and that MySQL is running."), 500


def show_start(show):
    return datetime.combine(show["show_date"], datetime.min.time()) + show["start_time"]


# ----------------------------------------------------------------------------------------------
# Auth decorators
# ----------------------------------------------------------------------------------------------
def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("user_id"):
            flash("Please log in first.")
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if session.get("role") != "ADMIN":
            abort(403, "Only administrators can open this page.")
        return fn(*a, **kw)
    return wrapper


def api_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("user_id"):
            return jsonify(error="Please log in first."), 401
        return fn(*a, **kw)
    return wrapper


# ----------------------------------------------------------------------------------------------
# External services (simulated): payment gateway + e-mail notifications
# ----------------------------------------------------------------------------------------------
def simulate_gateway(mode, amount):
    """Stand-in for a real payment gateway. Replace the body with Razorpay/Stripe calls for production."""
    return {"status": "SUCCESS", "transaction_id": "TXN-" + uuid.uuid4().hex[:12].upper(), "mode": mode, "amount": amount}


def notify(cur, user_id, subject, message):
    cur.execute("INSERT INTO notifications(user_id,subject,message) VALUES(%s,%s,%s)", (user_id, subject, message))
    app.logger.info("[MAIL to user %s] %s", user_id, subject)


# ----------------------------------------------------------------------------------------------
# User service: home, register, login, profile
# ----------------------------------------------------------------------------------------------
@app.route("/")
def home():
    s, g = request.args.get("q", "").strip(), request.args.get("genre", "").strip()
    sql = """SELECT m.*, (SELECT COUNT(*) FROM shows sh WHERE sh.movie_id=m.movie_id AND sh.show_date>=CURDATE()) upcoming
             FROM movies m WHERE 1=1"""
    args = []
    if s:
        sql += " AND m.title LIKE %s"
        args.append(f"%{s}%")
    if g:
        sql += " AND m.genre=%s"
        args.append(g)
    movies = q(sql + " ORDER BY m.rating DESC, m.title", args)
    genres = [r["genre"] for r in q("SELECT DISTINCT genre FROM movies WHERE genre IS NOT NULL ORDER BY genre")]
    return render_template("home.html", movies=movies, genres=genres, search=s, genre=g)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        if not name or "@" not in email:
            flash("Enter your name and a valid email address.")
        elif len(password) < 6:
            flash("Password must contain at least 6 characters.")
        else:
            try:
                run("INSERT INTO users(name,email,password_hash,phone,role) VALUES(%s,%s,%s,%s,'USER')",
                    (name, email, generate_password_hash(password), phone))
                flash("Account created. You can log in now.")
                return redirect(url_for("login"))
            except mysql.connector.IntegrityError:
                flash("That email is already registered. Try logging in instead.")
        return redirect(url_for("register"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = q("SELECT * FROM users WHERE email=%s", (request.form.get("email", "").strip().lower(),), one=True)
        if u and check_password_hash(u["password_hash"], request.form.get("password", "")):
            session.clear()
            session.update(user_id=u["user_id"], name=u["name"], role=u["role"])
            return redirect(url_for("admin") if u["role"] == "ADMIN" else url_for("home"))
        flash("Wrong email or password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    uid = session["user_id"]
    if request.method == "POST":
        action = request.form.get("action")
        if action == "details":
            name = request.form.get("name", "").strip()
            if not name:
                flash("Name cannot be empty.")
            else:
                run("UPDATE users SET name=%s, phone=%s WHERE user_id=%s", (name, request.form.get("phone", "").strip(), uid))
                session["name"] = name
                flash("Profile updated.")
        elif action == "password":
            u = q("SELECT password_hash FROM users WHERE user_id=%s", (uid,), one=True)
            new = request.form.get("new_password", "")
            if not check_password_hash(u["password_hash"], request.form.get("current_password", "")):
                flash("Current password is incorrect.")
            elif len(new) < 6:
                flash("New password must contain at least 6 characters.")
            else:
                run("UPDATE users SET password_hash=%s WHERE user_id=%s", (generate_password_hash(new), uid))
                flash("Password changed.")
        return redirect(url_for("profile"))
    user = q("SELECT * FROM users WHERE user_id=%s", (uid,), one=True)
    stats = q("""SELECT COUNT(*) total, COALESCE(SUM(status='CONFIRMED'),0) active,
                        COALESCE(SUM(CASE WHEN status='CONFIRMED' THEN amount END),0) spent
                 FROM bookings WHERE user_id=%s""", (uid,), one=True)
    notes = q("SELECT * FROM notifications WHERE user_id=%s ORDER BY notification_id DESC LIMIT 10", (uid,))
    return render_template("profile.html", user=user, stats=stats, notes=notes)


# ----------------------------------------------------------------------------------------------
# Movie & Show service (customer side)
# ----------------------------------------------------------------------------------------------
@app.route("/shows/<int:movie_id>")
def shows(movie_id):
    movie = q("SELECT * FROM movies WHERE movie_id=%s", (movie_id,), one=True)
    if not movie:
        abort(404, "Movie not found.")
    rows = q("""SELECT sh.*, t.name theatre, t.location,
                       (SELECT COUNT(*) FROM seats s WHERE s.theatre_id=sh.theatre_id) total,
                       (SELECT COUNT(*) FROM bookings b WHERE b.show_id=sh.show_id AND b.status='CONFIRMED') sold
                FROM shows sh JOIN theatres t ON sh.theatre_id=t.theatre_id
                WHERE sh.movie_id=%s AND sh.show_date>=CURDATE()
                ORDER BY sh.show_date, sh.start_time""", (movie_id,))
    now = datetime.now()
    days = {}
    for r in rows:
        if show_start(r) > now:
            days.setdefault(r["show_date"], []).append(r)
    return render_template("shows.html", movie=movie, days=days)


# ----------------------------------------------------------------------------------------------
# Booking service: seat map, booking (ACID transaction + row locks), ticket, cancellation
# ----------------------------------------------------------------------------------------------
@app.route("/seats/<int:show_id>")
@login_required
def seats(show_id):
    show = q("""SELECT sh.show_id, sh.theatre_id, sh.show_date, sh.start_time, sh.ticket_price,
                       m.title, m.duration_min, t.name theatre, t.location
                FROM shows sh JOIN movies m ON sh.movie_id=m.movie_id
                JOIN theatres t ON sh.theatre_id=t.theatre_id WHERE sh.show_id=%s""", (show_id,), one=True)
    if not show:
        abort(404, "Show not found.")
    rows = q("""SELECT s.seat_id, s.seat_number, s.row_label, s.seat_type,
                       (b.booking_id IS NOT NULL) AS booked
                FROM seats s LEFT JOIN bookings b
                  ON b.seat_id=s.seat_id AND b.show_id=%s AND b.status='CONFIRMED'
                WHERE s.theatre_id=%s ORDER BY s.row_label, s.col_no""", (show_id, show["theatre_id"]))
    layout = {}
    for r in rows:
        layout.setdefault(r["row_label"], []).append(r)
    mult = Decimal(config.PREMIUM_MULTIPLIER)
    return render_template("seats.html", show=show, layout=layout,
                           regular=show["ticket_price"], premium=show["ticket_price"] * mult,
                           available=sum(1 for r in rows if not r["booked"]), total=len(rows),
                           max_seats=config.MAX_SEATS_PER_BOOKING, modes=config.PAYMENT_MODES,
                           started=show_start(show) <= datetime.now())


@app.post("/book/<int:show_id>")
@login_required
def book(show_id):
    try:
        seat_ids = sorted({int(x) for x in request.form.getlist("seat_ids")})
    except ValueError:
        seat_ids = []
    mode = request.form.get("payment_mode", "DEMO")
    if mode not in config.PAYMENT_MODES:
        mode = "DEMO"
    if not seat_ids or len(seat_ids) > config.MAX_SEATS_PER_BOOKING:
        flash(f"Pick between 1 and {config.MAX_SEATS_PER_BOOKING} seats.")
        return redirect(url_for("seats", show_id=show_id))

    con = db()
    cur = con.cursor(dictionary=True)
    try:
        con.start_transaction()
        cur.execute("SELECT * FROM shows WHERE show_id=%s", (show_id,))
        show = cur.fetchone()
        if not show:
            raise BookingError("Show not found.")
        if show_start(show) <= datetime.now():
            raise BookingError("This show has already started.")

        marks = ",".join(["%s"] * len(seat_ids))
        # CRITICAL SECTION: lock seat rows in ascending id order. Every request uses the same order,
        # so two bookings can never wait on each other in a cycle (deadlock prevention).
        cur.execute(f"""SELECT seat_id, seat_number, seat_type FROM seats
                        WHERE theatre_id=%s AND seat_id IN ({marks}) ORDER BY seat_id FOR UPDATE""",
                    (show["theatre_id"], *seat_ids))
        seat_rows = cur.fetchall()
        if len(seat_rows) != len(seat_ids):
            raise BookingError("One or more seats do not belong to this show.")

        cur.execute(f"""SELECT seat_id FROM bookings
                        WHERE show_id=%s AND status='CONFIRMED' AND seat_id IN ({marks}) FOR UPDATE""",
                    (show_id, *seat_ids))
        taken = {r["seat_id"] for r in cur.fetchall()}
        if taken:
            names = ", ".join(s["seat_number"] for s in seat_rows if s["seat_id"] in taken)
            raise BookingError(f"Seat {names} was just booked by someone else. Pick different seats.")

        mult = Decimal(config.PREMIUM_MULTIPLIER)
        ids = []
        for s in seat_rows:
            amount = show["ticket_price"] * (mult if s["seat_type"] == "PREMIUM" else 1)
            gw = simulate_gateway(mode, amount)
            if gw["status"] != "SUCCESS":
                raise BookingError("Payment failed. You were not charged.")
            cur.execute("""INSERT INTO bookings(user_id,show_id,seat_id,booking_time,status,amount)
                           VALUES(%s,%s,%s,NOW(),'CONFIRMED',%s)""",
                        (session["user_id"], show_id, s["seat_id"], amount))
            bid = cur.lastrowid
            ids.append(bid)
            cur.execute("""INSERT INTO payments(booking_id,amount,payment_mode,payment_status,transaction_id)
                           VALUES(%s,%s,%s,'SUCCESS',%s)""", (bid, amount, mode, gw["transaction_id"]))
        label = ", ".join(s["seat_number"] for s in seat_rows)
        notify(cur, session["user_id"], "Booking confirmed",
               f"Your seat(s) {label} are confirmed for show #{show_id}. Booking id(s): {', '.join('#' + str(i) for i in ids)}.")
        con.commit()
    except BookingError as e:
        con.rollback()
        flash(str(e))
        return redirect(url_for("seats", show_id=show_id))
    except mysql.connector.IntegrityError:
        con.rollback()           # backstop: UNIQUE(show_id, seat_id, active_key) rejected a double booking
        flash("Someone booked one of those seats a moment ago. Pick different seats.")
        return redirect(url_for("seats", show_id=show_id))
    except Error:
        con.rollback()
        app.logger.exception("Booking transaction failed")
        flash("The booking could not be completed. Nothing was charged. Please try again.")
        return redirect(url_for("seats", show_id=show_id))
    finally:
        cur.close()
        con.close()
    if len(ids) == 1:
        return redirect(url_for("ticket", booking_id=ids[0]))
    flash(f"{len(ids)} seats booked. Open any booking to see its ticket.")
    return redirect(url_for("my_bookings"))


@app.route("/ticket/<int:booking_id>")
@login_required
def ticket(booking_id):
    b = q("""SELECT b.*, u.name user_name, m.title, m.duration_min, t.name theatre, t.location,
                    s.seat_number, s.seat_type, sh.show_date, sh.start_time, p.transaction_id, p.payment_status, p.payment_mode
             FROM bookings b JOIN users u ON b.user_id=u.user_id
             JOIN shows sh ON b.show_id=sh.show_id JOIN movies m ON sh.movie_id=m.movie_id
             JOIN theatres t ON sh.theatre_id=t.theatre_id JOIN seats s ON b.seat_id=s.seat_id
             LEFT JOIN payments p ON b.booking_id=p.booking_id WHERE b.booking_id=%s""", (booking_id,), one=True)
    if not b or (b["user_id"] != session["user_id"] and session.get("role") != "ADMIN"):
        abort(404, "Ticket not found.")
    return render_template("ticket.html", b=b)


@app.route("/my-bookings")
@login_required
def my_bookings():
    rows = q("""SELECT b.*, m.title, s.seat_number, t.name theatre, sh.show_date, sh.start_time, p.payment_status
                FROM bookings b JOIN shows sh ON b.show_id=sh.show_id
                JOIN movies m ON sh.movie_id=m.movie_id JOIN seats s ON b.seat_id=s.seat_id
                JOIN theatres t ON sh.theatre_id=t.theatre_id LEFT JOIN payments p ON p.booking_id=b.booking_id
                WHERE b.user_id=%s ORDER BY b.booking_id DESC""", (session["user_id"],))
    now = datetime.now()
    for r in rows:
        r["can_cancel"] = r["status"] == "CONFIRMED" and show_start(r) > now
    return render_template("bookings.html", bookings=rows)


@app.post("/cancel/<int:booking_id>")
@login_required
def cancel(booking_id):
    con = db()
    cur = con.cursor(dictionary=True)
    try:
        con.start_transaction()
        cur.execute("""SELECT b.*, sh.show_date, sh.start_time FROM bookings b
                       JOIN shows sh ON sh.show_id=b.show_id WHERE b.booking_id=%s FOR UPDATE""", (booking_id,))
        b = cur.fetchone()
        if not b or (b["user_id"] != session["user_id"] and session.get("role") != "ADMIN"):
            raise BookingError("Booking not found.")
        if b["status"] != "CONFIRMED":
            raise BookingError("This booking is already cancelled.")
        if show_start(b) <= datetime.now():
            raise BookingError("Shows that have started cannot be cancelled.")
        cur.execute("UPDATE bookings SET status='CANCELLED' WHERE booking_id=%s", (booking_id,))
        cur.execute("UPDATE payments SET payment_status='REFUND_PENDING' WHERE booking_id=%s", (booking_id,))
        notify(cur, b["user_id"], "Booking cancelled",
               f"Booking #{booking_id} was cancelled. Your refund of {inr(b['amount'])} is pending.")
        con.commit()
        flash("Booking cancelled. The seat is available again and your refund is pending.")
    except BookingError as e:
        con.rollback()
        flash(str(e))
    except Error:
        con.rollback()
        flash("Cancellation failed. Please try again.")
    finally:
        cur.close()
        con.close()
    return redirect(url_for("my_bookings") if session.get("role") != "ADMIN" else (request.referrer or url_for("admin")))


# ----------------------------------------------------------------------------------------------
# Report service + Admin panel (manage movies, theatres, shows)
# ----------------------------------------------------------------------------------------------
OCCUPANCY_SQL = """SELECT sh.show_id, m.title, t.name theatre, sh.show_date, sh.start_time,
        (SELECT COUNT(*) FROM seats s WHERE s.theatre_id=sh.theatre_id) total,
        (SELECT COUNT(*) FROM bookings b WHERE b.show_id=sh.show_id AND b.status='CONFIRMED') sold
    FROM shows sh JOIN movies m ON sh.movie_id=m.movie_id JOIN theatres t ON sh.theatre_id=t.theatre_id
    WHERE sh.show_date>=CURDATE() ORDER BY sh.show_date, sh.start_time LIMIT %s"""


@app.route("/admin")
@login_required
@admin_required
def admin():
    c = lambda sql: q(sql, one=True)["c"]
    stats = {
        "users": c("SELECT COUNT(*) c FROM users WHERE role='USER'"),
        "movies": c("SELECT COUNT(*) c FROM movies"),
        "shows": c("SELECT COUNT(*) c FROM shows WHERE show_date>=CURDATE()"),
        "confirmed": c("SELECT COUNT(*) c FROM bookings WHERE status='CONFIRMED'"),
        "cancelled": c("SELECT COUNT(*) c FROM bookings WHERE status='CANCELLED'"),
        "revenue": q("SELECT COALESCE(SUM(amount),0) c FROM bookings WHERE status='CONFIRMED'", one=True)["c"],
        "refunds": q("""SELECT COALESCE(SUM(amount),0) c FROM payments WHERE payment_status='REFUND_PENDING'""", one=True)["c"],
    }
    by_movie = q("""SELECT m.title, COUNT(b.booking_id) tickets, COALESCE(SUM(b.amount),0) revenue
                    FROM movies m LEFT JOIN shows sh ON sh.movie_id=m.movie_id
                    LEFT JOIN bookings b ON b.show_id=sh.show_id AND b.status='CONFIRMED'
                    GROUP BY m.movie_id, m.title ORDER BY revenue DESC, m.title""")
    top = max([r["revenue"] for r in by_movie] + [1])
    occupancy = q(OCCUPANCY_SQL, (12,))
    recent = q("""SELECT b.booking_id, u.name, m.title, s.seat_number, b.amount, b.status, b.booking_time
                  FROM bookings b JOIN users u ON b.user_id=u.user_id JOIN shows sh ON b.show_id=sh.show_id
                  JOIN movies m ON sh.movie_id=m.movie_id JOIN seats s ON b.seat_id=s.seat_id
                  ORDER BY b.booking_id DESC LIMIT 15""")
    return render_template("admin.html", stats=stats, by_movie=by_movie, top=top, occupancy=occupancy, recent=recent)


@app.route("/admin/movies", methods=["GET", "POST"])
@login_required
@admin_required
def admin_movies():
    if request.method == "POST":
        f = request.form
        try:
            run("""INSERT INTO movies(title,genre,language,duration_min,rating,description) VALUES(%s,%s,%s,%s,%s,%s)""",
                (f["title"].strip(), f.get("genre", "").strip(), f.get("language", "English").strip() or "English",
                 int(f["duration_min"]), Decimal(f.get("rating") or "0"), f.get("description", "").strip()))
            flash("Movie added.")
        except (ValueError, ArithmeticError, KeyError, Error):
            flash("Could not add the movie. Check the title, duration (minutes) and rating (0 to 10).")
        return redirect(url_for("admin_movies"))
    return render_template("admin_movies.html", movies=q("SELECT * FROM movies ORDER BY movie_id DESC"))


@app.post("/admin/movies/<int:movie_id>/delete")
@login_required
@admin_required
def admin_movie_delete(movie_id):
    try:
        run("DELETE FROM movies WHERE movie_id=%s", (movie_id,))
        flash("Movie deleted.")
    except Error:
        flash("This movie still has shows and cannot be deleted. Delete its shows first.")
    return redirect(url_for("admin_movies"))


@app.route("/admin/theatres", methods=["GET", "POST"])
@login_required
@admin_required
def admin_theatres():
    if request.method == "POST":
        f = request.form
        con = db()
        cur = con.cursor()
        try:
            rows, per_row = int(f["rows"]), int(f["per_row"])
            if not (1 <= rows <= 26 and 1 <= per_row <= 30):
                raise ValueError
            cur.execute("INSERT INTO theatres(name,location) VALUES(%s,%s)", (f["name"].strip(), f["location"].strip()))
            tid = cur.lastrowid
            data = [(tid, chr(65 + r), c, f"{chr(65 + r)}{c}", "PREMIUM" if r >= rows - 2 else "REGULAR")
                    for r in range(rows) for c in range(1, per_row + 1)]
            cur.executemany("INSERT INTO seats(theatre_id,row_label,col_no,seat_number,seat_type) VALUES(%s,%s,%s,%s,%s)", data)
            con.commit()
            flash(f"Theatre added with {len(data)} seats.")
        except (ValueError, KeyError):
            con.rollback()
            flash("Rows must be 1 to 26 and seats per row 1 to 30.")
        except Error:
            con.rollback()
            flash("A theatre with that name and location already exists.")
        finally:
            cur.close()
            con.close()
        return redirect(url_for("admin_theatres"))
    rows = q("""SELECT t.*, COUNT(s.seat_id) seat_count FROM theatres t LEFT JOIN seats s ON s.theatre_id=t.theatre_id
                GROUP BY t.theatre_id ORDER BY t.theatre_id""")
    return render_template("admin_theatres.html", theatres=rows)


@app.route("/admin/shows", methods=["GET", "POST"])
@login_required
@admin_required
def admin_shows():
    if request.method == "POST":
        f = request.form
        try:
            run("INSERT INTO shows(movie_id,theatre_id,show_date,start_time,ticket_price) VALUES(%s,%s,%s,%s,%s)",
                (int(f["movie_id"]), int(f["theatre_id"]), f["show_date"], f["start_time"], Decimal(f["ticket_price"])))
            flash("Show scheduled.")
        except mysql.connector.IntegrityError:
            flash("That theatre already has a show at that date and time.")
        except (ValueError, ArithmeticError, KeyError, Error):
            flash("Could not schedule the show. Check every field.")
        return redirect(url_for("admin_shows"))
    rows = q("""SELECT sh.*, m.title, t.name theatre,
                       (SELECT COUNT(*) FROM bookings b WHERE b.show_id=sh.show_id AND b.status='CONFIRMED') sold
                FROM shows sh JOIN movies m ON sh.movie_id=m.movie_id JOIN theatres t ON sh.theatre_id=t.theatre_id
                WHERE sh.show_date>=CURDATE() ORDER BY sh.show_date, sh.start_time""")
    return render_template("admin_shows.html", shows=rows, movies=q("SELECT movie_id,title FROM movies ORDER BY title"),
                           theatres=q("SELECT theatre_id,name FROM theatres ORDER BY name"),
                           today=datetime.now().strftime("%Y-%m-%d"))


@app.post("/admin/shows/<int:show_id>/delete")
@login_required
@admin_required
def admin_show_delete(show_id):
    try:
        run("DELETE FROM shows WHERE show_id=%s", (show_id,))
        flash("Show deleted.")
    except Error:
        flash("This show has bookings. Cancel them first.")
    return redirect(url_for("admin_shows"))


# ----------------------------------------------------------------------------------------------
# OS Simulator layer: page + JSON API routes
# ----------------------------------------------------------------------------------------------
@app.route("/os")
@login_required
def os_dashboard():
    return render_template("os_dashboard.html")


@app.post("/api/schedule")
@api_required
def api_schedule():
    d = request.get_json(silent=True) or {}
    try:
        return jsonify(schedule(d.get("algorithm", "FCFS"), d.get("processes", []), int(d.get("quantum", 2))))
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400


@app.post("/api/sync")
@api_required
def api_sync():
    d = request.get_json(silent=True) or {}
    try:
        return jsonify(simulate_seat_lock(d.get("requests", []), bool(d.get("use_lock", True))))
    except ValueError as e:
        return jsonify(error=str(e)), 400


@app.post("/api/deadlock")
@api_required
def api_deadlock():
    d = request.get_json(silent=True) or {}
    try:
        graph = build_wait_for_graph(d.get("holds"), d.get("requests")) if "holds" in d or "requests" in d else d.get("graph", {})
        return jsonify(detect_deadlock(graph))
    except (ValueError, TypeError, AttributeError) as e:
        return jsonify(error=str(e) or "Invalid graph."), 400


@app.get("/api/resources")
@api_required
def api_resources():
    """Resource monitor: every seat is a limited resource; report how many are allocated per show."""
    shows_ = q(OCCUPANCY_SQL, (10,))
    out = [{"show_id": r["show_id"], "title": r["title"], "theatre": r["theatre"],
            "when": f"{dfmt(r['show_date'])} {tfmt(r['start_time'])}", "total": r["total"], "sold": r["sold"],
            "free": r["total"] - r["sold"], "pct": round(100 * r["sold"] / r["total"]) if r["total"] else 0} for r in shows_]
    pool_size = config.POOL_SIZE
    return jsonify(shows=out, totals={"seats": sum(r["total"] for r in out), "allocated": sum(r["sold"] for r in out)},
                   db_pool=pool_size, server_time=datetime.now().strftime("%H:%M:%S"))


if __name__ == "__main__":
    app.run(debug=True)
