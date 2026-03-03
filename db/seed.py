"""
Seed the database with example data for the PoC.
Run directly: python -m db.seed
"""

import uuid
from db.schema import get_connection, init_schema


EXAMPLE_PROFILE = {
    "name": "Tommy Liu",
    "home_gym": "Mosaic Boulders",
    "years_climbing": "2",
    "peak_boulder_grade": "V8",
    "peak_sport_grade": "",
    "preferred_style": "boulder",
    "training_focus": "power endurance, mobility, flexibility",
    "notes": "",
}

EXAMPLE_LOGS = [
    # Recent bouldering sessions
    {
        "id": str(uuid.uuid4()),
        "logged_at": "2026-02-28 18:30:00",
        "location": "Mosaic Boulders",
        "route_name": None,
        "grade": "V6",
        "style": "boulder",
        "outcome": "send",
        "attempts": 2,
        "notes": "Felt solid on the compression move. Got it second go.",
        "tags": '["compression", "slab"]',
    },
    {
        "id": str(uuid.uuid4()),
        "logged_at": "2026-02-28 19:00:00",
        "location": "Mosaic Boulders",
        "route_name": None,
        "grade": "V7",
        "style": "boulder",
        "outcome": "attempt",
        "attempts": 8,
        "notes": "Overhang with a nasty heel-toe crux at the top. Getting closer but the heel keeps blowing.",
        "tags": '["overhang", "heel hook", "project"]',
    },
    {
        "id": str(uuid.uuid4()),
        "logged_at": "2026-02-26 17:45:00",
        "location": "Mosaic Boulders",
        "route_name": None,
        "grade": "V6",
        "style": "boulder",
        "outcome": "flash",
        "attempts": 1,
        "notes": "Crimpy face, read the beta on the way up. Felt easy.",
        "tags": '["crimp", "face"]',
    },
    {
        "id": str(uuid.uuid4()),
        "logged_at": "2026-02-26 18:15:00",
        "location": "Mosaic Boulders",
        "route_name": None,
        "grade": "V8",
        "style": "boulder",
        "outcome": "attempt",
        "attempts": 12,
        "notes": "Campus-style dyno. Can match the hold but can't control the swing. Pure power issue.",
        "tags": '["dyno", "campus", "project"]',
    },
    {
        "id": str(uuid.uuid4()),
        "logged_at": "2026-02-24 18:00:00",
        "location": "Yosemite Valley",
        "route_name": "After Six",
        "grade": "5.7",
        "style": "trad",
        "outcome": "onsight",
        "attempts": 1,
        "notes": "Easy trad warm up. Beautiful splitter crack.",
        "tags": '["crack", "trad", "outdoors"]',
    },
    {
        "id": str(uuid.uuid4()),
        "logged_at": "2026-02-22 19:00:00",
        "location": "Mosaic Boulders",
        "route_name": None,
        "grade": "V5",
        "style": "boulder",
        "outcome": "send",
        "attempts": 1,
        "tags": '["sloper", "compression"]',
        "notes": "Warm up, no issues.",
    },
    {
        "id": str(uuid.uuid4()),
        "logged_at": "2026-02-22 19:30:00",
        "location": "Mosaic Boulders",
        "route_name": None,
        "grade": "V6",
        "style": "boulder",
        "outcome": "send",
        "attempts": 3,
        "notes": "Pinch-heavy, forearms were pumped by the end.",
        "tags": '["pinch", "overhang"]',
    },
    {
        "id": str(uuid.uuid4()),
        "logged_at": "2026-02-20 18:00:00",
        "location": "Mosaic Boulders",
        "route_name": None,
        "grade": "V7",
        "style": "boulder",
        "outcome": "send",
        "attempts": 5,
        "notes": "Finally got it. The heel-toe at the start was the key — once I figured that out the rest flowed.",
        "tags": '["heel hook", "overhang", "send"]',
    },
    {
        "id": str(uuid.uuid4()),
        "logged_at": "2026-02-18 17:30:00",
        "location": "Berkeley Ironworks",
        "route_name": None,
        "grade": "V6",
        "style": "boulder",
        "outcome": "send",
        "attempts": 2,
        "notes": "Visited Berkeley Ironworks for a change. Routesetting felt different, more volume-heavy.",
        "tags": '["volume", "compression"]',
    },
    {
        "id": str(uuid.uuid4()),
        "logged_at": "2026-02-15 10:00:00",
        "location": "Mosaic Boulders",
        "route_name": None,
        "grade": "V8",
        "style": "boulder",
        "outcome": "attempt",
        "attempts": 6,
        "notes": "Morning session. Felt weak, probably underrecovered from the campus board session yesterday.",
        "tags": '["crimp", "project"]',
    },
]


def seed(db_path: str, force: bool = False) -> None:
    init_schema(db_path)
    conn = get_connection(db_path)

    existing = conn.execute("SELECT COUNT(*) FROM climb_logs").fetchone()[0]
    if existing > 0 and not force:
        print(
            f"[seed] DB already has {existing} climb logs, skipping. Use force=True to reseed."
        )
        conn.close()
        return

    if force:
        conn.execute("DELETE FROM climb_logs")
        conn.execute("DELETE FROM user_profile")
        conn.execute("DELETE FROM chat_messages")

    for key, value in EXAMPLE_PROFILE.items():
        conn.execute(
            "INSERT OR REPLACE INTO user_profile (key, value) VALUES (?, ?)",
            (key, value),
        )

    for log in EXAMPLE_LOGS:
        conn.execute(
            """
            INSERT OR REPLACE INTO climb_logs
            (id, logged_at, location, route_name, grade, style, outcome, attempts, notes, tags)
            VALUES (:id, :logged_at, :location, :route_name, :grade, :style,
                    :outcome, :attempts, :notes, :tags)
        """,
            log,
        )

    conn.commit()
    conn.close()
    print(
        f"[seed] Seeded {len(EXAMPLE_LOGS)} climb logs and {len(EXAMPLE_PROFILE)} profile fields."
    )


if __name__ == "__main__":
    import sys
    from agent.config import load_config

    cfg = load_config()
    force = "--force" in sys.argv
    seed(cfg["db"]["path"], force=force)
