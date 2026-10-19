"""One-command database setup:  python database/setup_db.py   (add --reset to wipe and rebuild)

1. creates the schema from schema.sql
2. creates demo users (admin + user)
3. seeds movies, theatres, seats and 5 days of shows (only if the movies table is empty)
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mysql.connector
from werkzeug.security import generate_password_hash
import config

HERE = os.path.dirname(os.path.abspath(__file__))
DB = config.DB_CONFIG["database"]

MOVIES = [
    ("Interstellar Echoes", "Sci-Fi", "English", 169, 8.7, "A crew follows a fading signal through a wormhole to find a new home for humanity."),
    ("Monsoon Melodies", "Romance", "Hindi", 142, 7.9, "Two strangers share a rented flat in Mumbai, and a monsoon that will not end."),
    ("The Last Heist", "Thriller", "English", 118, 8.1, "A retired safecracker takes one final job and finds the crew was assembled to fail."),
    ("Dhoom Highway", "Action", "Hindi", 155, 7.4, "A highway patrol officer chases a gang that never appears on any camera."),
    ("Laugh Riot", "Comedy", "Hindi", 130, 7.1, "A wedding planner's worst weekend, told in real time."),
    ("Orbit Zero", "Sci-Fi", "English", 126, 7.8, "A repair mission on a silent space station becomes a race against its own AI."),
    ("Kerala Backwaters", "Drama", "Malayalam", 138, 8.4, "A ferryman's family is tested when the last boat route is closed."),
    ("Shadow Protocol", "Action", "English", 124, 7.6, "An analyst discovers her own name on a kill list."),
]
THEATRES = [("CineSync Grand", "Rajpur Road, Dehradun", 8, 12),
            ("CineSync Plaza", "Mussoorie Road, Dehradun", 6, 10),
            ("CineSync Imax Hall", "Haridwar Bypass, Dehradun", 10, 14)]
SLOTS = ["11:00:00", "15:00:00", "19:00:00", "22:00:00"]
PRICES = [180, 220, 260, 300]


def run_schema(cur):
    with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if not ln.strip().startswith("--")]
    for stmt in "\n".join(lines).split(";"):
        if stmt.strip():
            cur.execute(stmt)


def make_seats(cur, theatre_id, rows, per_row):
    data = []
    for r in range(rows):
        label = chr(65 + r)
        stype = "PREMIUM" if r >= rows - 2 else "REGULAR"
        for c in range(1, per_row + 1):
            data.append((theatre_id, label, c, f"{label}{c}", stype))
    cur.executemany("INSERT INTO seats(theatre_id,row_label,col_no,seat_number,seat_type) VALUES(%s,%s,%s,%s,%s)", data)


def main():
    cfg = {k: v for k, v in config.DB_CONFIG.items() if k != "database"}
    con = mysql.connector.connect(**cfg)
    cur = con.cursor()
    if "--reset" in sys.argv:
        cur.execute(f"DROP DATABASE IF EXISTS `{DB}`")
        print("Old database dropped.")
    run_schema(cur)
    cur.execute(f"USE `{DB}`")

    users = [("Admin", "admin@movie.com", "admin123", "9999999999", "ADMIN"),
             ("Demo User", "user@movie.com", "user123", "8888888888", "USER")]
    for name, email, pw, phone, role in users:
        cur.execute("""INSERT INTO users(name,email,password_hash,phone,role) VALUES(%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE password_hash=VALUES(password_hash), role=VALUES(role)""",
                    (name, email, generate_password_hash(pw), phone, role))

    cur.execute("SELECT COUNT(*) FROM movies")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT INTO movies(title,genre,language,duration_min,rating,description) VALUES(%s,%s,%s,%s,%s,%s)", MOVIES)
        cur.execute("SELECT movie_id FROM movies ORDER BY movie_id")
        movie_ids = [r[0] for r in cur.fetchall()]
        today = date.today()
        for ti, (name, loc, rows, per_row) in enumerate(THEATRES):
            cur.execute("INSERT INTO theatres(name,location) VALUES(%s,%s)", (name, loc))
            tid = cur.lastrowid
            make_seats(cur, tid, rows, per_row)
            for d in range(5):
                for si, slot in enumerate(SLOTS):
                    mid = movie_ids[(ti * 3 + si + d) % len(movie_ids)]
                    cur.execute("INSERT INTO shows(movie_id,theatre_id,show_date,start_time,ticket_price) VALUES(%s,%s,%s,%s,%s)",
                                (mid, tid, today + timedelta(days=d), slot, PRICES[si]))
        print("Sample movies, theatres, seats and shows created.")
    con.commit()
    cur.close(); con.close()
    print("Database ready.\n  Admin: admin@movie.com / admin123\n  User : user@movie.com / user123")


if __name__ == "__main__":
    main()
