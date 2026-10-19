-- CineSync : Smart Movie Ticket Booking & Resource Allocation System
-- Run completely in MySQL Workbench, or let `python database/setup_db.py` run it for you.

CREATE DATABASE IF NOT EXISTS smart_movie CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE smart_movie;

CREATE TABLE IF NOT EXISTS users (
    user_id        INT AUTO_INCREMENT PRIMARY KEY,
    name           VARCHAR(100) NOT NULL,
    email          VARCHAR(120) NOT NULL UNIQUE,
    password_hash  VARCHAR(255) NOT NULL,
    phone          VARCHAR(20),
    role           ENUM('USER','ADMIN') NOT NULL DEFAULT 'USER',
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS movies (
    movie_id       INT AUTO_INCREMENT PRIMARY KEY,
    title          VARCHAR(150) NOT NULL,
    genre          VARCHAR(60),
    language       VARCHAR(40) NOT NULL DEFAULT 'English',
    duration_min   INT NOT NULL,
    rating         DECIMAL(3,1) NOT NULL DEFAULT 0,
    description    TEXT,
    CONSTRAINT chk_movie_duration CHECK (duration_min > 0),
    CONSTRAINT chk_movie_rating   CHECK (rating BETWEEN 0 AND 10)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS theatres (
    theatre_id     INT AUTO_INCREMENT PRIMARY KEY,
    name           VARCHAR(100) NOT NULL,
    location       VARCHAR(150) NOT NULL,
    UNIQUE KEY uq_theatre (name, location)
) ENGINE=InnoDB;

-- A seat is a physical resource that belongs to a theatre (hall).
CREATE TABLE IF NOT EXISTS seats (
    seat_id        INT AUTO_INCREMENT PRIMARY KEY,
    theatre_id     INT NOT NULL,
    row_label      CHAR(2) NOT NULL,
    col_no         INT NOT NULL,
    seat_number    VARCHAR(6) NOT NULL,
    seat_type      ENUM('REGULAR','PREMIUM') NOT NULL DEFAULT 'REGULAR',
    UNIQUE KEY uq_seat (theatre_id, seat_number),
    CONSTRAINT fk_seat_theatre FOREIGN KEY (theatre_id) REFERENCES theatres(theatre_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS shows (
    show_id        INT AUTO_INCREMENT PRIMARY KEY,
    movie_id       INT NOT NULL,
    theatre_id     INT NOT NULL,
    show_date      DATE NOT NULL,
    start_time     TIME NOT NULL,
    ticket_price   DECIMAL(8,2) NOT NULL,
    UNIQUE KEY uq_show_slot (theatre_id, show_date, start_time),
    CONSTRAINT chk_price CHECK (ticket_price > 0),
    CONSTRAINT fk_show_movie   FOREIGN KEY (movie_id)   REFERENCES movies(movie_id),
    CONSTRAINT fk_show_theatre FOREIGN KEY (theatre_id) REFERENCES theatres(theatre_id)
) ENGINE=InnoDB;

-- active_key is 1 only while a booking is CONFIRMED (NULL otherwise).
-- UNIQUE(show_id, seat_id, active_key) therefore makes double booking IMPOSSIBLE at the
-- database level, even if application-level locking were bypassed. Cancelled rows (NULL) never clash.
CREATE TABLE IF NOT EXISTS bookings (
    booking_id     INT AUTO_INCREMENT PRIMARY KEY,
    user_id        INT NOT NULL,
    show_id        INT NOT NULL,
    seat_id        INT NOT NULL,
    booking_time   DATETIME NOT NULL,
    status         ENUM('CONFIRMED','CANCELLED') NOT NULL DEFAULT 'CONFIRMED',
    amount         DECIMAL(8,2) NOT NULL,
    active_key     TINYINT GENERATED ALWAYS AS (IF(status = 'CONFIRMED', 1, NULL)) STORED,
    UNIQUE KEY uq_active_seat (show_id, seat_id, active_key),
    INDEX idx_booking_user (user_id),
    CONSTRAINT fk_book_user  FOREIGN KEY (user_id) REFERENCES users(user_id),
    CONSTRAINT fk_book_show  FOREIGN KEY (show_id) REFERENCES shows(show_id),
    CONSTRAINT fk_book_seat  FOREIGN KEY (seat_id) REFERENCES seats(seat_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payments (
    payment_id      INT AUTO_INCREMENT PRIMARY KEY,
    booking_id      INT NOT NULL UNIQUE,
    amount          DECIMAL(8,2) NOT NULL,
    payment_mode    ENUM('DEMO','UPI','CARD','NETBANKING') NOT NULL DEFAULT 'DEMO',
    payment_status  ENUM('SUCCESS','FAILED','REFUND_PENDING','REFUNDED') NOT NULL,
    transaction_id  VARCHAR(40) NOT NULL UNIQUE,
    paid_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_pay_booking FOREIGN KEY (booking_id) REFERENCES bookings(booking_id)
) ENGINE=InnoDB;

-- Simulated e-mail / notification outbox (External Services layer).
CREATE TABLE IF NOT EXISTS notifications (
    notification_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    subject         VARCHAR(150) NOT NULL,
    message         TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_notif_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB;
