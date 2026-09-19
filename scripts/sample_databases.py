"""Extra sample databases used to measure accuracy across domains.

The schemas follow widely used public examples (a Chinook-style music store,
a Northwind-style retail shop, an HR database, a library and a clinic) so the
benchmark covers different naming styles, join depths and data types. Every
database is generated locally with a fixed seed — nothing is downloaded.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

__all__ = ["BUILDERS", "build_all"]


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _rand_date(rng: random.Random, start: date, end: date) -> str:
    return (start + timedelta(days=rng.randint(0, (end - start).days))).isoformat()


# --------------------------------------------------------------------------- #
# 1. Music store (Chinook-style): artists -> albums -> tracks -> invoice lines
# --------------------------------------------------------------------------- #
def build_music(path: Path, seed: int = 7) -> Path:
    rng = random.Random(seed)
    con = _connect(path)
    con.executescript("""
    CREATE TABLE artists (artist_id INTEGER PRIMARY KEY, name TEXT NOT NULL,
        country TEXT);
    CREATE TABLE albums (album_id INTEGER PRIMARY KEY, title TEXT NOT NULL,
        artist_id INTEGER NOT NULL REFERENCES artists(artist_id),
        release_year INTEGER);
    CREATE TABLE genres (genre_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
    CREATE TABLE tracks (track_id INTEGER PRIMARY KEY, name TEXT NOT NULL,
        album_id INTEGER REFERENCES albums(album_id),
        genre_id INTEGER REFERENCES genres(genre_id),
        milliseconds INTEGER, unit_price REAL NOT NULL);
    CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name TEXT,
        last_name TEXT, email TEXT, country TEXT, city TEXT);
    CREATE TABLE invoices (invoice_id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
        invoice_date DATE, billing_country TEXT, total REAL);
    CREATE TABLE invoice_lines (invoice_line_id INTEGER PRIMARY KEY,
        invoice_id INTEGER NOT NULL REFERENCES invoices(invoice_id),
        track_id INTEGER NOT NULL REFERENCES tracks(track_id),
        unit_price REAL, quantity INTEGER);
    """)
    artists = ["Radiohead", "Miles Davis", "Adele", "Daft Punk", "Nina Simone",
               "Arctic Monkeys", "A R Rahman", "Bjork", "Kendrick Lamar",
               "Fleetwood Mac"]
    countries = ["UK", "USA", "France", "India", "Iceland", "Germany", "Brazil"]
    con.executemany("INSERT INTO artists VALUES (?,?,?)",
                    [(i, name, rng.choice(countries))
                     for i, name in enumerate(artists, 1)])
    genres = ["Rock", "Jazz", "Pop", "Electronic", "Hip Hop", "Soul"]
    con.executemany("INSERT INTO genres VALUES (?,?)",
                    list(enumerate(genres, 1)))
    albums, tracks, album_id, track_id = [], [], 1, 1
    for artist_id in range(1, len(artists) + 1):
        for n in range(rng.randint(1, 3)):
            albums.append((album_id, f"{artists[artist_id-1]} Vol {n+1}",
                           artist_id, rng.randint(1985, 2024)))
            for _ in range(rng.randint(4, 9)):
                tracks.append((track_id, f"Track {track_id}", album_id,
                               rng.randint(1, len(genres)),
                               rng.randint(120, 420) * 1000,
                               round(rng.choice([0.99, 1.29, 1.99]), 2)))
                track_id += 1
            album_id += 1
    con.executemany("INSERT INTO albums VALUES (?,?,?,?)", albums)
    con.executemany("INSERT INTO tracks VALUES (?,?,?,?,?,?)", tracks)
    firsts = ["Leo", "Mia", "Omar", "Sara", "Tom", "Ana", "Raj", "Emma"]
    lasts = ["Silva", "Khan", "Meyer", "Dubois", "Rossi", "Patel", "Novak"]
    customers = []
    for cid in range(1, 61):
        f, l = rng.choice(firsts), rng.choice(lasts)
        country = rng.choice(countries)
        customers.append((cid, f, l, f"{f}.{l}{cid}@example.com".lower(),
                          country, f"{country} City"))
    con.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)
    invoices, lines, inv_id, line_id = [], [], 1, 1
    for _ in range(200):
        cust = rng.choice(customers)
        chosen = rng.sample(tracks, rng.randint(1, 5))
        total = 0.0
        for track in chosen:
            qty = rng.randint(1, 3)
            total += track[5] * qty
            lines.append((line_id, inv_id, track[0], track[5], qty))
            line_id += 1
        invoices.append((inv_id, cust[0],
                         _rand_date(rng, date(2022, 1, 1), date(2025, 6, 30)),
                         cust[4], round(total, 2)))
        inv_id += 1
    con.executemany("INSERT INTO invoices VALUES (?,?,?,?,?)", invoices)
    con.executemany("INSERT INTO invoice_lines VALUES (?,?,?,?,?)", lines)
    con.commit()
    con.close()
    return path


# --------------------------------------------------------------------------- #
# 2. HR database: departments -> employees -> salaries, with a manager link
# --------------------------------------------------------------------------- #
def build_hr(path: Path, seed: int = 11) -> Path:
    rng = random.Random(seed)
    con = _connect(path)
    con.executescript("""
    CREATE TABLE departments (dept_id INTEGER PRIMARY KEY, dept_name TEXT NOT NULL,
        location TEXT, budget REAL);
    CREATE TABLE job_titles (job_id INTEGER PRIMARY KEY, title TEXT NOT NULL,
        min_salary REAL, max_salary REAL);
    CREATE TABLE employees (emp_id INTEGER PRIMARY KEY, first_name TEXT,
        last_name TEXT, email TEXT, hire_date DATE,
        dept_id INTEGER REFERENCES departments(dept_id),
        job_id INTEGER REFERENCES job_titles(job_id),
        manager_id INTEGER REFERENCES employees(emp_id), salary REAL,
        is_active INTEGER DEFAULT 1);
    CREATE TABLE projects (project_id INTEGER PRIMARY KEY, name TEXT,
        dept_id INTEGER REFERENCES departments(dept_id), start_date DATE,
        end_date DATE);
    CREATE TABLE assignments (assignment_id INTEGER PRIMARY KEY,
        emp_id INTEGER REFERENCES employees(emp_id),
        project_id INTEGER REFERENCES projects(project_id), hours REAL);
    """)
    depts = [("Engineering", "Bengaluru", 1200000), ("Sales", "Chennai", 800000),
             ("Marketing", "Mumbai", 450000), ("Finance", "Delhi", 600000),
             ("Support", "Pune", 350000)]
    con.executemany("INSERT INTO departments VALUES (?,?,?,?)",
                    [(i, *d) for i, d in enumerate(depts, 1)])
    jobs = [("Software Engineer", 600000, 2500000), ("Sales Executive", 400000, 1500000),
            ("Analyst", 500000, 1800000), ("Manager", 1200000, 4000000),
            ("Support Agent", 300000, 900000)]
    con.executemany("INSERT INTO job_titles VALUES (?,?,?,?)",
                    [(i, *j) for i, j in enumerate(jobs, 1)])
    firsts = ["Ajay", "Divya", "Karthik", "Sneha", "Vikram", "Priya", "Arun",
              "Meera", "Rahul", "Anita"]
    lasts = ["Iyer", "Sharma", "Reddy", "Nair", "Gupta", "Menon", "Rao"]
    employees = []
    for eid in range(1, 81):
        f, l = rng.choice(firsts), rng.choice(lasts)
        job = rng.randint(1, len(jobs))
        salary = round(rng.uniform(jobs[job - 1][1], jobs[job - 1][2]), -3)
        employees.append((eid, f, l, f"{f}.{l}{eid}@corp.example".lower(),
                          _rand_date(rng, date(2015, 1, 1), date(2025, 1, 1)),
                          rng.randint(1, len(depts)), job,
                          None if eid <= 5 else rng.randint(1, 5), salary,
                          int(rng.random() > 0.12)))
    con.executemany("INSERT INTO employees VALUES (?,?,?,?,?,?,?,?,?,?)", employees)
    projects = []
    for pid in range(1, 16):
        start = _rand_date(rng, date(2023, 1, 1), date(2025, 1, 1))
        projects.append((pid, f"Project {chr(64 + pid)}",
                         rng.randint(1, len(depts)), start,
                         rng.choice([None, _rand_date(rng, date(2025, 2, 1),
                                                      date(2026, 1, 1))])))
    con.executemany("INSERT INTO projects VALUES (?,?,?,?,?)", projects)
    con.executemany("INSERT INTO assignments VALUES (?,?,?,?)",
                    [(i, rng.randint(1, 80), rng.randint(1, 15),
                      round(rng.uniform(5, 180), 1)) for i in range(1, 121)])
    con.commit()
    con.close()
    return path


# --------------------------------------------------------------------------- #
# 3. Library: books, members, loans (dates and NULLs matter here)
# --------------------------------------------------------------------------- #
def build_library(path: Path, seed: int = 13) -> Path:
    rng = random.Random(seed)
    con = _connect(path)
    con.executescript("""
    CREATE TABLE authors (author_id INTEGER PRIMARY KEY, name TEXT NOT NULL,
        birth_year INTEGER);
    CREATE TABLE books (book_id INTEGER PRIMARY KEY, title TEXT NOT NULL,
        author_id INTEGER REFERENCES authors(author_id), genre TEXT,
        published_year INTEGER, copies INTEGER DEFAULT 1);
    CREATE TABLE members (member_id INTEGER PRIMARY KEY, full_name TEXT,
        join_date DATE, city TEXT, membership TEXT);
    CREATE TABLE loans (loan_id INTEGER PRIMARY KEY,
        book_id INTEGER REFERENCES books(book_id),
        member_id INTEGER REFERENCES members(member_id),
        loan_date DATE, due_date DATE, return_date DATE);
    CREATE TABLE fines (fine_id INTEGER PRIMARY KEY,
        loan_id INTEGER REFERENCES loans(loan_id), amount REAL, paid INTEGER);
    """)
    authors = ["Ursula Le Guin", "Chinua Achebe", "Jane Austen", "R K Narayan",
               "Haruki Murakami", "Toni Morrison", "Italo Calvino"]
    con.executemany("INSERT INTO authors VALUES (?,?,?)",
                    [(i, a, rng.randint(1775, 1960))
                     for i, a in enumerate(authors, 1)])
    genres = ["Fiction", "Science Fiction", "History", "Poetry", "Mystery"]
    books = [(b, f"Book {b}", rng.randint(1, len(authors)), rng.choice(genres),
              rng.randint(1950, 2024), rng.randint(1, 6)) for b in range(1, 41)]
    con.executemany("INSERT INTO books VALUES (?,?,?,?,?,?)", books)
    cities = ["Chennai", "Kochi", "Hyderabad", "Kolkata", "Jaipur"]
    members = [(m, f"Member {m}", _rand_date(rng, date(2020, 1, 1), date(2025, 6, 1)),
                rng.choice(cities), rng.choice(["standard", "student", "premium"]))
               for m in range(1, 51)]
    con.executemany("INSERT INTO members VALUES (?,?,?,?,?)", members)
    loans, fines, fine_id = [], [], 1
    for loan_id in range(1, 201):
        loan_date = _rand_date(rng, date(2024, 1, 1), date(2025, 8, 1))
        due = (date.fromisoformat(loan_date) + timedelta(days=21)).isoformat()
        returned = None if rng.random() < 0.25 else (
            date.fromisoformat(loan_date)
            + timedelta(days=rng.randint(3, 40))).isoformat()
        loans.append((loan_id, rng.randint(1, 40), rng.randint(1, 50),
                      loan_date, due, returned))
        if returned and returned > due:
            fines.append((fine_id, loan_id, round(rng.uniform(10, 200), 2),
                          int(rng.random() > 0.4)))
            fine_id += 1
    con.executemany("INSERT INTO loans VALUES (?,?,?,?,?,?)", loans)
    con.executemany("INSERT INTO fines VALUES (?,?,?,?)", fines)
    con.commit()
    con.close()
    return path


# --------------------------------------------------------------------------- #
# 4. Clinic: patients, doctors, appointments, prescriptions
# --------------------------------------------------------------------------- #
def build_clinic(path: Path, seed: int = 17) -> Path:
    rng = random.Random(seed)
    con = _connect(path)
    con.executescript("""
    CREATE TABLE doctors (doctor_id INTEGER PRIMARY KEY, name TEXT,
        speciality TEXT, consultation_fee REAL);
    CREATE TABLE patients (patient_id INTEGER PRIMARY KEY, name TEXT,
        gender TEXT, birth_date DATE, city TEXT, registered_on DATE);
    CREATE TABLE appointments (appointment_id INTEGER PRIMARY KEY,
        patient_id INTEGER REFERENCES patients(patient_id),
        doctor_id INTEGER REFERENCES doctors(doctor_id),
        appointment_date DATE, status TEXT, fee_paid REAL);
    CREATE TABLE medicines (medicine_id INTEGER PRIMARY KEY, name TEXT,
        price REAL, in_stock INTEGER);
    CREATE TABLE prescriptions (prescription_id INTEGER PRIMARY KEY,
        appointment_id INTEGER REFERENCES appointments(appointment_id),
        medicine_id INTEGER REFERENCES medicines(medicine_id), dosage TEXT,
        days INTEGER);
    """)
    specialities = ["Cardiology", "Dermatology", "General Medicine",
                    "Orthopaedics", "Paediatrics"]
    con.executemany("INSERT INTO doctors VALUES (?,?,?,?)",
                    [(i, f"Dr. {chr(64+i)}", rng.choice(specialities),
                      round(rng.uniform(300, 1500), -1)) for i in range(1, 13)])
    cities = ["Chennai", "Madurai", "Coimbatore", "Salem", "Trichy"]
    con.executemany("INSERT INTO patients VALUES (?,?,?,?,?,?)",
                    [(i, f"Patient {i}", rng.choice(["F", "M"]),
                      _rand_date(rng, date(1950, 1, 1), date(2018, 1, 1)),
                      rng.choice(cities),
                      _rand_date(rng, date(2021, 1, 1), date(2025, 6, 1)))
                     for i in range(1, 121)])
    statuses = ["completed"] * 6 + ["cancelled", "no-show", "scheduled"]
    appointments = []
    for aid in range(1, 301):
        status = rng.choice(statuses)
        appointments.append((aid, rng.randint(1, 120), rng.randint(1, 12),
                             _rand_date(rng, date(2024, 1, 1), date(2025, 9, 1)),
                             status,
                             round(rng.uniform(300, 1500), -1)
                             if status == "completed" else 0.0))
    con.executemany("INSERT INTO appointments VALUES (?,?,?,?,?,?)", appointments)
    meds = ["Paracetamol", "Amoxicillin", "Ibuprofen", "Cetirizine", "Metformin",
            "Omeprazole", "Atorvastatin"]
    con.executemany(
        "INSERT INTO medicines VALUES (?,?,?,?)",
        [(i, m, round(rng.uniform(15, 350), 2),
          0 if i % 4 == 0 else rng.randint(5, 400))   # a few are out of stock
         for i, m in enumerate(meds, 1)])
    con.executemany("INSERT INTO prescriptions VALUES (?,?,?,?,?)",
                    [(i, rng.randint(1, 300), rng.randint(1, len(meds)),
                      rng.choice(["1-0-1", "0-0-1", "1-1-1"]), rng.randint(3, 30))
                     for i in range(1, 201)])
    con.commit()
    con.close()
    return path


BUILDERS = {
    "music_store": build_music,
    "hr": build_hr,
    "library": build_library,
    "clinic": build_clinic,
}


def build_all(folder: Path) -> dict[str, Path]:
    """Create every benchmark database inside ``folder``."""
    made = {}
    for name, builder in BUILDERS.items():
        made[name] = builder(folder / f"{name}.db")
    return made


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent / "data" / "benchmark"
    for name, built in build_all(root).items():
        print(f"{name}: {built}")
