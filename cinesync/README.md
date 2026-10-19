# CineSync: Smart Movie Ticket Booking & Resource Allocation System
College-level DBMS + OS project (Flask, MySQL, OS simulator)

## Quick start (Windows)
1. Install **Python 3.10+** and **MySQL 8+** (keep the MySQL service running).
2. Open this folder in VS Code. Open `config.py` and replace `YOUR_MYSQL_PASSWORD` with your MySQL root password.
3. In the VS Code terminal:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   python database/setup_db.py
   python app.py
   ```
4. Open http://127.0.0.1:5000

`setup_db.py` creates the database, all tables, demo users, 8 movies, 3 theatres with seats and 5 days of shows.
Use `python database/setup_db.py --reset` to wipe and rebuild everything.
(Prefer Workbench? Run `database/schema.sql` there, then run `setup_db.py` once for the seed data.)

Demo accounts: `user@movie.com / user123`  and  `admin@movie.com / admin123`

## How it maps to the architecture diagram
| Layer | Where it lives |
|---|---|
| Presentation (pages, templates, auth screens, admin panel) | `templates/`, `static/css/style.css`, `static/js/os.js` |
| Application: Booking, User, Movie & Show, Report services, API routes | `app.py` (sections are labelled) |
| Database (Users, Movies, Theatres, Shows, Seats, Bookings, Payments + Notifications) | `database/schema.sql`, MySQL |
| OS Simulator: Process Manager, Scheduler, Synchronization (+ deadlock) | `os_module/scheduling.py`, `sync.py`, `deadlock.py`, page `/os` |
| External services: payment gateway (simulated), e-mail notifications | `simulate_gateway()` and `notify()` in `app.py`, `notifications` table |

## How the pieces integrate
```
Browser --HTTP--> Flask routes (app.py) --SQL (pooled connections)--> MySQL
                       |
                       +--> os_module (pure Python, no DB) <--- /api/* JSON <--- os.js in the browser
```
* **Booking** (`/book/<show_id>`) is one MySQL transaction: lock the chosen seat rows (`SELECT ... FOR UPDATE`, always in ascending seat_id order), check nobody confirmed them, take payment, insert `bookings` + `payments`, write a notification, commit. Any failure rolls everything back.
* **Safety net:** `bookings.active_key` plus `UNIQUE(show_id, seat_id, active_key)` makes a double booking impossible even if the application logic were bypassed.
* **OS lab** links to the real system in two ways: the *Seat locking* tab simulates the same critical section the booking transaction uses, and the *Resource monitor* reads live seat allocation from MySQL through `/api/resources`.
* **CSRF protection** is on every POST. Forms include `csrf_token`, and `os.js` sends it in the `X-CSRF-Token` header.

## Features
Customer: register, log in, profile and password change, search and filter movies, showtimes with live availability, seat map with regular and premium seats, multi-seat booking (up to 6), simulated payment (UPI, card, net banking, demo), printable ticket, my bookings, cancellation with refund-pending state, notification inbox.
Admin: revenue, occupancy and cancellation reports; add or delete movies; add theatres (seats auto-generated); schedule or delete shows; view and cancel any booking.
OS lab: FCFS, SJF, Priority and Round Robin with Gantt chart, waiting, turnaround and response times and process state log, plus a four-way comparison; seat-lock simulation with and without mutual exclusion; wait-for-graph deadlock detection with victim selection, recovery steps and a drawn graph; live resource monitor.

## Mentor demo script (about 6 minutes)
1. Log in as the user, open a movie, pick a show, choose 2 seats (one premium) and pay. Show the ticket, then My bookings and Profile (notification).
2. Open a second browser window as another user and try to book the same seat: it is rejected. Explain `FOR UPDATE` and the UNIQUE key.
3. Cancel a booking: status becomes Cancelled, payment becomes Refund pending, the seat is free again.
4. Log in as admin: reports, add a movie, a theatre and a show.
5. OS lab: compare all four schedulers; run seat locking **with** and **without** the lock (race condition, double booking); load the deadlock preset, detect it, read the recovery; open the resource monitor.
Key sentence: *the DBMS performs the real booking transaction; the OS module is an educational simulation of the concurrency and resource-management ideas behind it.*

## Project layout
```
app.py  config.py  requirements.txt
database/   schema.sql  setup_db.py
os_module/  scheduling.py  sync.py  deadlock.py
templates/  (14 pages)   static/css/style.css   static/js/os.js
```

## Troubleshooting
* *"The database is not reachable"*: MySQL service not running, or wrong password in `config.py`.
* *Access denied for user 'root'*: password mismatch; you can also set the `DB_PASSWORD` environment variable.
* *Port 5000 busy*: change `app.run(debug=True, port=5001)` at the bottom of `app.py`.
* Going to production: set a real `SECRET_KEY`, run with `waitress` or `gunicorn`, replace `simulate_gateway()` with a real gateway and `notify()` with SMTP.
