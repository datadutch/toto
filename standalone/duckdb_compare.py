#!/usr/bin/env python3
"""
DuckDB Performance Comparison: MotherDuck vs Local
Runs benchmarks against both databases and compares results.
"""

import os
import time
import random
import string
import duckdb
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import List, Dict
import statistics

load_dotenv()

@dataclass
class BenchmarkResult:
    query_name: str
    executions: List[float]
    db_type: str
    
    @property
    def avg_ms(self) -> float:
        return statistics.mean(self.executions) * 1000
    
    def ratio_vs(self, other: 'BenchmarkResult') -> float:
        """Return ratio of self avg time to other avg time."""
        return self.avg_ms / other.avg_ms if other.avg_ms > 0 else 0


class DuckDBAnalyzer:
    def __init__(self, conn, iterations: int = 5):
        self.conn = conn
        self.iterations = iterations
        self.results: List[BenchmarkResult] = []
        
    def _generate_string(self, length: int = 10) -> str:
        return ''.join(random.choices(string.ascii_letters, k=length))
    
    def setup_test_data(self, scale: int = 10000) -> None:
        """Create test tables with scalable data."""
        # Users table
        self.conn.execute("""
            CREATE OR REPLACE TABLE bench_users (
                user_id INTEGER PRIMARY KEY,
                name VARCHAR,
                email VARCHAR,
                signup_date DATE
            )
        """)
        
        # Products table
        self.conn.execute("""
            CREATE OR REPLACE TABLE bench_products (
                product_id INTEGER PRIMARY KEY,
                name VARCHAR,
                category VARCHAR,
                price DECIMAL(10,2)
            )
        """)
        
        # Orders table (fact table)
        self.conn.execute("""
            CREATE OR REPLACE TABLE bench_orders (
                order_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                product_id INTEGER,
                quantity INTEGER,
                order_date TIMESTAMP
            )
        """)
        
        # Insert test data
        num_users = max(100, scale // 100)
        num_products = max(100, scale // 100)
        num_orders = scale
        
        for i in range(num_users):
            self.conn.execute(
                "INSERT INTO bench_users VALUES (?, ?, ?, ?)",
                [i, self._generate_string(20), f"user{i}@test.com", f"2020-01-{i%28+1:02d}"]
            )
        
        categories = ["Electronics", "Clothing", "Books", "Sports", "Food"]
        for i in range(num_products):
            self.conn.execute(
                "INSERT INTO bench_products VALUES (?, ?, ?, ?)",
                [i, self._generate_string(30), random.choice(categories), round(random.uniform(1, 500), 2)]
            )
        
        for i in range(num_orders):
            self.conn.execute(
                "INSERT INTO bench_orders VALUES (?, ?, ?, ?, ?)",
                [i, random.randint(0, num_users-1), random.randint(0, num_products-1), 
                 random.randint(1, 10), f"2024-01-{random.randint(1,28):02d} {random.randint(0,23):02d}:00:00"]
            )
    
    def run_benchmark(self, query: str, name: str) -> BenchmarkResult:
        """Execute a query multiple times and measure performance."""
        # Warmup
        self.conn.execute(query).fetchall()
        
        # Measured runs
        times: List[float] = []
        for _ in range(self.iterations):
            start = time.perf_counter()
            self.conn.execute(query).fetchall()
            end = time.perf_counter()
            times.append(end - start)
        
        return BenchmarkResult(query_name=name, executions=times, db_type=self.conn.debug_name if hasattr(self.conn, 'debug_name') else 'unknown')
    
    def benchmark_queries(self, scale: int = 10000) -> None:
        """Run standard benchmark suite."""
        self.setup_test_data(scale)
        
        self.results = [
            self.run_benchmark("SELECT COUNT(*) FROM bench_users", "Count users"),
            self.run_benchmark("SELECT COUNT(*) FROM bench_orders", "Count orders"),
            self.run_benchmark("SELECT * FROM bench_orders WHERE user_id = 50", "Filter by user_id"),
            self.run_benchmark("SELECT category, AVG(price) FROM bench_products GROUP BY category", "Avg price by category"),
            self.run_benchmark("""
                SELECT u.name, COUNT(o.order_id) as order_count
                FROM bench_users u
                JOIN bench_orders o ON o.user_id = u.user_id
                GROUP BY u.name
                ORDER BY order_count DESC
                LIMIT 10
            """, "User order counts (join)"),
            self.run_benchmark("""
                SELECT CAST(order_date AS DATE) as date, COUNT(*) as orders
                FROM bench_orders
                GROUP BY date
                ORDER BY date
            """, "Daily order aggregation"),
            self.run_benchmark("""
                SELECT u.name, p.category, SUM(o.quantity * p.price) as total_spent
                FROM bench_users u
                JOIN bench_orders o ON o.user_id = u.user_id
                JOIN bench_products p ON o.product_id = p.product_id
                GROUP BY u.name, p.category
                ORDER BY total_spent DESC
                LIMIT 20
            """, "User spending by category"),
        ]


def run_benchmarks(db_path: str, db_name: str, scale: int = 5000, iterations: int = 3):
    """Run benchmarks against a specific database."""
    print(f"\n{'='*60}")
    print(f"Benchmarking: {db_name}")
    print(f"Scale: {scale:,} rows, Iterations: {iterations}")
    print(f"{'='*60}")
    
    try:
        conn = duckdb.connect(db_path)
        analyzer = DuckDBAnalyzer(conn, iterations=iterations)
        analyzer.benchmark_queries(scale)
        
        results = analyzer.results
        for r in results:
            print(f"  {r.query_name:<40} {r.avg_ms:>8.2f} ms")
        
        conn.close()
        return results
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def compare_results(md_results: List[BenchmarkResult], local_results: List[BenchmarkResult]) -> None:
    """Compare MotherDuck vs Local results."""
    print(f"\n{'='*80}")
    print("COMPARISON: MotherDuck vs Local DuckDB".center(80))
    print(f"{'='*80}")
    print(f"{'Query':<40} {'MotherDuck (ms)':<15} {'Local (ms)':<15} {'MD/Local':<12}")
    print("-"*80)
    
    for md, local in zip(md_results, local_results):
        ratio = md.avg_ms / local.avg_ms if local.avg_ms > 0 else 0
        ratio_str = f"{ratio:.2f}x"
        if ratio > 1:
            ratio_str = f"{ratio:.2f}x (slower)"
        else:
            ratio_str = f"{ratio:.2f}x (faster)"
        
        print(f"{md.query_name:<40} {md.avg_ms:<15.2f} {local.avg_ms:<15.2f} {ratio_str:<15}")
    
    print("="*80)


def main():
    load_dotenv()
    
    # MotherDuck connection
    token = os.getenv("MOTHERDUCK_TOKEN")
    md_path = f"md:toto?motherduck_token={token}" if token else None
    
    # Local connection - use in-memory for fair comparison
    local_path = ":memory:"
    
    scale = 500
    iterations = 2
    
    md_results = None
    local_results = None
    
    # Run MotherDuck benchmarks
    if md_path:
        md_results = run_benchmarks(md_path, "MotherDuck", scale, iterations)
    else:
        print("No MOTHERDUCK_TOKEN found, skipping MotherDuck benchmarks")
    
    # Run Local benchmarks
    local_results = run_benchmarks(local_path, "Local DuckDB (in-memory)", scale, iterations)
    
    # Compare
    if md_results and local_results:
        compare_results(md_results, local_results)


if __name__ == "__main__":
    main()
