import sqlite3
from datetime import date, datetime
from typing import Optional, List, Dict, Any
import os

DB_PATH = os.getenv("DB_PATH", "flamebot.db")

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        cursor = self.conn.cursor()

        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                registered_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS friendships (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id_1   INTEGER NOT NULL,
                user_id_2   INTEGER NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                -- status: pending | accepted | declined
                created_at  TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id_1) REFERENCES users(user_id),
                FOREIGN KEY (user_id_2) REFERENCES users(user_id),
                UNIQUE(user_id_1, user_id_2)
            );

            CREATE TABLE IF NOT EXISTS flames (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id_1    INTEGER NOT NULL,
                user_id_2    INTEGER NOT NULL,
                streak       INTEGER DEFAULT 0,
                best_streak  INTEGER DEFAULT 0,
                last_updated TEXT,
                FOREIGN KEY (user_id_1) REFERENCES users(user_id),
                FOREIGN KEY (user_id_2) REFERENCES users(user_id),
                UNIQUE(user_id_1, user_id_2)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id   INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                sent_date   TEXT NOT NULL,
                sent_at     TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (sender_id) REFERENCES users(user_id),
                FOREIGN KEY (receiver_id) REFERENCES users(user_id)
            );
        """)
        self.conn.commit()

    # ─── User management ─────────────────────────────────────────────────────

    def register_user(self, user_id: int, username: str, first_name: str):
        self.conn.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
        """, (user_id, username, first_name))
        self.conn.commit()

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)
        ).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_users(self) -> List[Dict]:
        rows = self.conn.execute("SELECT * FROM users").fetchall()
        return [dict(r) for r in rows]

    def get_user_stats(self, user_id: int) -> Dict:
        total = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE sender_id = ?", (user_id,)
        ).fetchone()['cnt']
        user = self.get_user_by_id(user_id)
        return {
            'total_messages': total,
            'registered_at': user['registered_at'] if user else ''
        }

    # ─── Friend management ────────────────────────────────────────────────────

    def send_friend_request(self, from_id: int, to_id: int) -> str:
        # Check if already friends
        existing = self.conn.execute("""
            SELECT status FROM friendships
            WHERE (user_id_1=? AND user_id_2=?) OR (user_id_1=? AND user_id_2=?)
        """, (from_id, to_id, to_id, from_id)).fetchone()

        if existing:
            status = existing['status']
            if status == 'accepted':
                return "already_friends"
            elif status == 'pending':
                # Check direction
                direction = self.conn.execute("""
                    SELECT user_id_1 FROM friendships
                    WHERE user_id_1=? AND user_id_2=? AND status='pending'
                """, (from_id, to_id)).fetchone()
                if direction:
                    return "request_exists"
                else:
                    return "incoming_exists"

        self.conn.execute("""
            INSERT OR IGNORE INTO friendships (user_id_1, user_id_2, status)
            VALUES (?, ?, 'pending')
        """, (from_id, to_id))
        self.conn.commit()

        # Create flame record
        self._ensure_flame(from_id, to_id)
        return "success"

    def accept_friend_request(self, from_id: int, to_id: int):
        self.conn.execute("""
            UPDATE friendships SET status='accepted'
            WHERE user_id_1=? AND user_id_2=?
        """, (from_id, to_id))
        self.conn.commit()
        self._ensure_flame(from_id, to_id)

    def decline_friend_request(self, from_id: int, to_id: int):
        self.conn.execute("""
            UPDATE friendships SET status='declined'
            WHERE user_id_1=? AND user_id_2=?
        """, (from_id, to_id))
        self.conn.commit()

    def are_friends(self, user_id_1: int, user_id_2: int) -> bool:
        row = self.conn.execute("""
            SELECT 1 FROM friendships
            WHERE ((user_id_1=? AND user_id_2=?) OR (user_id_1=? AND user_id_2=?))
            AND status='accepted'
        """, (user_id_1, user_id_2, user_id_2, user_id_1)).fetchone()
        return row is not None

    def get_friends(self, user_id: int) -> List[Dict]:
        rows = self.conn.execute("""
            SELECT u.* FROM users u
            JOIN friendships f ON (
                (f.user_id_1=? AND f.user_id_2=u.user_id) OR
                (f.user_id_2=? AND f.user_id_1=u.user_id)
            )
            WHERE f.status='accepted' AND u.user_id != ?
        """, (user_id, user_id, user_id)).fetchall()
        return [dict(r) for r in rows]

    def get_pending_requests(self, user_id: int) -> List[Dict]:
        """Get friend requests sent TO this user (incoming)"""
        rows = self.conn.execute("""
            SELECT u.* FROM users u
            JOIN friendships f ON f.user_id_1=u.user_id
            WHERE f.user_id_2=? AND f.status='pending'
        """, (user_id,)).fetchall()
        return [dict(r) for r in rows]

    # ─── Flame management ─────────────────────────────────────────────────────

    def _ensure_flame(self, user_id_1: int, user_id_2: int):
        """Ensure normalized flame record exists (smaller id first)"""
        a, b = min(user_id_1, user_id_2), max(user_id_1, user_id_2)
        self.conn.execute("""
            INSERT OR IGNORE INTO flames (user_id_1, user_id_2, streak, best_streak)
            VALUES (?, ?, 0, 0)
        """, (a, b))
        self.conn.commit()

    def get_flame(self, user_id_1: int, user_id_2: int) -> Optional[Dict]:
        a, b = min(user_id_1, user_id_2), max(user_id_1, user_id_2)
        row = self.conn.execute(
            "SELECT * FROM flames WHERE user_id_1=? AND user_id_2=?", (a, b)
        ).fetchone()
        return dict(row) if row else None

    def get_best_flame(self, user_id: int) -> Optional[Dict]:
        """Get the pair with highest streak for this user, with friend's username"""
        row = self.conn.execute("""
            SELECT f.*, u.username FROM flames f
            JOIN users u ON (
                CASE WHEN f.user_id_1=? THEN f.user_id_2 ELSE f.user_id_1 END = u.user_id
            )
            WHERE f.user_id_1=? OR f.user_id_2=?
            ORDER BY f.streak DESC LIMIT 1
        """, (user_id, user_id, user_id)).fetchone()
        return dict(row) if row else None

    def update_flame(self, sender_id: int, receiver_id: int) -> str:
        """Update streak after both parties have sent a message today"""
        a, b = min(sender_id, receiver_id), max(sender_id, receiver_id)
        today = str(date.today())

        both_sent = self._both_sent_today(sender_id, receiver_id)
        if not both_sent:
            return "waiting"

        flame = self.get_flame(a, b)
        if not flame:
            return "no_flame"

        if flame['last_updated'] == today:
            return "already_updated"

        # Determine if streak continues or resets
        yesterday = str(date.today() - __import__('datetime').timedelta(days=1))
        if flame['last_updated'] == yesterday or flame['streak'] == 0:
            new_streak = flame['streak'] + 1
        else:
            new_streak = 1  # Reset — they missed a day

        new_best = max(new_streak, flame['best_streak'])

        self.conn.execute("""
            UPDATE flames SET streak=?, best_streak=?, last_updated=?
            WHERE user_id_1=? AND user_id_2=?
        """, (new_streak, new_best, today, a, b))
        self.conn.commit()
        return "updated"

    def _both_sent_today(self, user_id_1: int, user_id_2: int) -> bool:
        today = str(date.today())
        sent_1 = self.conn.execute("""
            SELECT 1 FROM messages
            WHERE sender_id=? AND receiver_id=? AND sent_date=?
        """, (user_id_1, user_id_2, today)).fetchone()
        sent_2 = self.conn.execute("""
            SELECT 1 FROM messages
            WHERE sender_id=? AND receiver_id=? AND sent_date=?
        """, (user_id_2, user_id_1, today)).fetchone()
        return sent_1 is not None and sent_2 is not None

    # ─── Messages ─────────────────────────────────────────────────────────────

    def record_message(self, sender_id: int, receiver_id: int):
        today = str(date.today())
        self.conn.execute("""
            INSERT INTO messages (sender_id, receiver_id, sent_date)
            VALUES (?, ?, ?)
        """, (sender_id, receiver_id, today))
        self.conn.commit()

    def checked_in_today(self, sender_id: int, receiver_id: int) -> bool:
        today = str(date.today())
        row = self.conn.execute("""
            SELECT 1 FROM messages
            WHERE sender_id=? AND receiver_id=? AND sent_date=?
        """, (sender_id, receiver_id, today)).fetchone()
        return row is not None
