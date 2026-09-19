# Accuracy benchmark

Model: `Qwen/Qwen2.5-Coder-0.5B-Instruct (re-scored)`

**26/36 correct = 72%**

| Database | Correct | Questions | Accuracy | Avg time |
|---|---|---|---|---|
| clinic | 7 | 7 | 100% | 27s |
| hr | 4 | 7 | 57% | 57s |
| library | 4 | 7 | 57% | 50s |
| music_store | 5 | 7 | 71% | 88s |
| retail | 6 | 8 | 75% | 76s |

## Questions that failed

- **retail** — How many orders are there in total?  
  `SELECT SUM(T1.quantity) AS total_orders
FROM order_items AS T1
JOIN orders AS T2 ON T1.order_id = T2.order_id;`  
  different values
- **retail** — List the 5 most expensive products with their price.  
  `SELECT p.name, p.unit_price
FROM products p
JOIN order_items oi ON p.product_id = oi.product_id
WHERE oi.quantity > 0
ORDER BY p.unit_price DESC
LIMIT 5;`  
  different values
- **music_store** — Show the albums released after 2010 with their release year.  
  `SELECT a.title, a.release_year
FROM albums a
JOIN invoices i ON a.album_id = i.album_id
WHERE i.invoice_date > '2010-01-01'
ORDER BY a.release_year DESC;`  
  failed to run: no such column: i.album_id
- **music_store** — How many albums does each artist have?  
  `SELECT a.artist_id, a.name, COUNT(a.album_id) AS album_count
FROM albums a
JOIN artists a ON a.artist_id = a.artist_id
GROUP BY a.artist_id
ORDER BY album_count DESC;`  
  failed to run: ambiguous column name: a.artist_id
- **hr** — Show the 10 highest paid employees with their salary.  
  `SELECT e.first_name, e.last_name, e.salary
FROM employees e
JOIN orders o ON e.emp_id = o.employee_id
WHERE o.hire_date >= '2024-01-01'
GROUP BY e.emp_id
ORDER BY SUM(o.salary) DESC
LIMIT 10;`  
  failed to run: no such table: orders
- **hr** — Which projects have not finished yet?  
  `SELECT DISTINCT p.name
FROM projects p
WHERE p.end_date < CURDATE();`  
  failed to run: no such function: CURDATE
- **hr** — Who was hired in 2024?  
  `SELECT e.first_name, e.last_name, e.hire_date
FROM employees e
WHERE e.hire_date = '2024-01-01';`  
  0 rows instead of 5
- **library** — List the books in the Mystery genre.  
  `SELECT b.title
FROM books b
JOIN genres g ON b.genre_id = g.genre_id
WHERE g.genre = 'Mystery';`  
  failed to run: no such table: genres
- **library** — What is the total amount of unpaid fines?  
  `SELECT SUM(f.amount) AS total_unpaid_fines
FROM fines f
JOIN loans l ON f.loan_id = l.loan_id
WHERE l.return_date IS NULL;`  
  different values
- **library** — Show the members from Chennai.  
  `SELECT m.full_name FROM members m
JOIN loans l ON m.member_id = l.member_id
WHERE m.city = 'Chennai';`  
  40 rows instead of 10
