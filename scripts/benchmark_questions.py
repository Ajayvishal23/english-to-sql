"""Benchmark questions: plain English + the SQL a human would write.

Scoring compares the *result rows* of the model's query with the reference
query, so any correct formulation counts — not just an exact text match.
"""

from __future__ import annotations

QUESTIONS: dict[str, list[tuple[str, str]]] = {
    # ---------------------------------------------------------------- retail
    "retail": [
        ("Show all customers from Germany.",
         "SELECT customer_id, first_name, last_name, city, country "
         "FROM customers WHERE country = 'Germany'"),
        ("How many orders are there in total?",
         "SELECT COUNT(*) FROM orders"),
        ("List the 5 most expensive products with their price.",
         "SELECT name, unit_price FROM products ORDER BY unit_price DESC LIMIT 5"),
        ("Which products have fewer than 20 units in stock?",
         "SELECT name FROM products WHERE units_in_stock < 20"),
        ("How many customers are there in each country?",
         "SELECT country, COUNT(*) AS n FROM customers GROUP BY country"),
        ("What is the total quantity sold for each product?",
         "SELECT p.name, SUM(i.quantity) AS total FROM products p "
         "JOIN order_items i ON i.product_id = p.product_id GROUP BY p.name"),
        ("List customers who have never placed an order.",
         "SELECT c.customer_id, c.first_name, c.last_name FROM customers c "
         "LEFT JOIN orders o ON o.customer_id = c.customer_id "
         "WHERE o.order_id IS NULL"),
        ("Which employee handled the most orders?",
         "SELECT e.first_name, e.last_name, COUNT(*) AS n FROM employees e "
         "JOIN orders o ON o.employee_id = e.employee_id "
         "GROUP BY e.employee_id ORDER BY n DESC LIMIT 1"),
    ],
    # ----------------------------------------------------------- music store
    "music_store": [
        ("List all artists from the UK.",
         "SELECT name FROM artists WHERE country = 'UK'"),
        ("How many tracks are there?",
         "SELECT COUNT(*) FROM tracks"),
        ("Show the albums released after 2010 with their release year.",
         "SELECT title, release_year FROM albums WHERE release_year > 2010"),
        ("What is the average track price?",
         "SELECT AVG(unit_price) FROM tracks"),
        ("How many albums does each artist have?",
         "SELECT a.name, COUNT(al.album_id) AS n FROM artists a "
         "JOIN albums al ON al.artist_id = a.artist_id GROUP BY a.name"),
        ("Which 5 customers spent the most in total?",
         "SELECT c.customer_id, c.first_name, c.last_name, "
         "ROUND(SUM(i.total), 2) AS spent FROM customers c "
         "JOIN invoices i ON i.customer_id = c.customer_id "
         "GROUP BY c.customer_id ORDER BY spent DESC LIMIT 5"),
        ("How many tracks are in each genre?",
         "SELECT g.name, COUNT(t.track_id) AS n FROM genres g "
         "JOIN tracks t ON t.genre_id = g.genre_id GROUP BY g.name"),
    ],
    # -------------------------------------------------------------------- hr
    "hr": [
        ("List the employees who work in the Engineering department.",
         "SELECT e.emp_id, e.first_name, e.last_name FROM employees e "
         "JOIN departments d ON d.dept_id = e.dept_id "
         "WHERE d.dept_name = 'Engineering'"),
        ("What is the average salary per department?",
         "SELECT d.dept_name, AVG(e.salary) AS avg_salary FROM departments d "
         "JOIN employees e ON e.dept_id = d.dept_id GROUP BY d.dept_name"),
        ("How many employees are no longer active?",
         "SELECT COUNT(*) FROM employees WHERE is_active = 0"),
        ("Show the 10 highest paid employees with their salary.",
         "SELECT first_name, last_name, salary FROM employees "
         "ORDER BY salary DESC LIMIT 10"),
        ("Which projects have not finished yet?",
         "SELECT name FROM projects WHERE end_date IS NULL"),
        ("How many hours were logged on each project?",
         "SELECT p.project_id, p.name, ROUND(SUM(a.hours), 2) AS hours "
         "FROM projects p JOIN assignments a ON a.project_id = p.project_id "
         "GROUP BY p.project_id"),
        ("Who was hired in 2024?",
         "SELECT emp_id, first_name, last_name FROM employees "
         "WHERE hire_date >= '2024-01-01' AND hire_date < '2025-01-01'"),
    ],
    # --------------------------------------------------------------- library
    "library": [
        ("How many books are in the library?",
         "SELECT COUNT(*) FROM books"),
        ("List the books in the Mystery genre.",
         "SELECT title FROM books WHERE genre = 'Mystery'"),
        ("Which loans have not been returned yet?",
         "SELECT loan_id FROM loans WHERE return_date IS NULL"),
        ("How many books did each author write?",
         "SELECT a.name, COUNT(b.book_id) AS n FROM authors a "
         "JOIN books b ON b.author_id = a.author_id GROUP BY a.name"),
        ("What is the total amount of unpaid fines?",
         "SELECT SUM(amount) FROM fines WHERE paid = 0"),
        ("Show the members from Chennai.",
         "SELECT member_id, full_name FROM members WHERE city = 'Chennai'"),
        ("Which 5 books were borrowed most often?",
         "SELECT b.title, COUNT(l.loan_id) AS n FROM books b "
         "JOIN loans l ON l.book_id = b.book_id GROUP BY b.title "
         "ORDER BY n DESC LIMIT 5"),
    ],
    # ---------------------------------------------------------------- clinic
    "clinic": [
        ("How many patients are registered?",
         "SELECT COUNT(*) FROM patients"),
        ("List the doctors in Cardiology.",
         "SELECT name FROM doctors WHERE speciality = 'Cardiology'"),
        ("How many appointments were cancelled?",
         "SELECT COUNT(*) FROM appointments WHERE status = 'cancelled'"),
        ("How many appointments does each doctor have?",
         "SELECT d.name, COUNT(a.appointment_id) AS n FROM doctors d "
         "JOIN appointments a ON a.doctor_id = d.doctor_id GROUP BY d.name"),
        ("What is the total fee collected from completed appointments?",
         "SELECT SUM(fee_paid) FROM appointments WHERE status = 'completed'"),
        ("Which medicines are out of stock?",
         "SELECT name FROM medicines WHERE in_stock = 0"),
        ("Show the patients from Madurai.",
         "SELECT name FROM patients WHERE city = 'Madurai'"),
    ],
}


def total_questions() -> int:
    return sum(len(v) for v in QUESTIONS.values())
