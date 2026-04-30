#!/usr/bin/env python3
"""
DuckDB Performance Analyzer
 benchmarks query execution, analyzes performance characteristics.
Usage: python duckdb_performance_analyzer.py [--iterations N] [--scale N]
"""

import duckdb
import time
import random
import string
import argparse
from dataclasses import dataclass
from typing import List, Dict, Optional
import statistics


@dataclass
class BenchmarkResult:
    query_name: str
    executions: List[float]
    
    @property
    def avg_ms(self) -> float:
        return statistics.mean(self.executions) * 1000
    
    @property
    def min_ms(self) -> float:
        return min(self.executions) * 1000
    
    @property
    def max_ms(self) -> float:
        return max(self.executions) * 1000
    
    @property
    def std_ms(self) -> float:
        return statistics.stdev(self.executions) * 1000 if len(self.executions) > 1 else 0


class DuckDBAnalyzer:
    def __init__(self, scale: int = 10000, iterations: int = 5):
        self.scale = scale
        self.iterations = iterations
        self.conn = duckdb.connect(":memory:")
        self.results: List[BenchmarkResult] = []
        
    def _generate_string(self, length: int = 10) -> str:
        return ''.join(random.choices(string.ascii_letters, k=length))
    
    def setup_test_data(self) -> None:
        """Create test tables with scalable data."""
        print(f"Setting up test data with scale factor: {self.scale:,}")
        
        # Users table
        self.conn.execute("""
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                name VARCHAR,
                email VARCHAR,
                signup_date DATE
            )
        """)
        
        # Products table
        self.conn.execute("""
            CREATE TABLE products (
                product_id INTEGER PRIMARY KEY,
                name VARCHAR,
                category VARCHAR,
                price DECIMAL(10,2)
            )
        """)
        
        # Orders table (fact table)
        self.conn.execute("""
            CREATE TABLE orders (
                order_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                product_id INTEGER,
                quantity INTEGER,
                order_date TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            )
        """)
        
        # Insert test data
        num_users = max(100, self.scale // 100)
        num_products = max(100, self.scale // 100)
        num_orders = self.scale
        
        print(f"  Inserting {num_users} users...")
        self.conn.execute("BEGIN")
        for i in range(num_users):
            self.conn.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?)",
                [i, self._generate_string(20), f"user{i}@test.com", f"2020-01-{i%28+1:02d}"]
            )
        
        print(f"  Inserting {num_products} products...")
        categories = ["Electronics", "Clothing", "Books", "Sports", "Food"]
        for i in range(num_products):
            self.conn.execute(
                "INSERT INTO products VALUES (?, ?, ?, ?)",
                [i, self._generate_string(30), random.choice(categories), round(random.uniform(1, 500), 2)]
            )
        
        print(f"  Inserting {num_orders} orders...")
        for i in range(num_orders):
            self.conn.execute(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?)",
                [i, random.randint(0, num_users-1), random.randint(0, num_products-1), 
                 random.randint(1, 10), f"2024-01-{random.randint(1,28):02d} {random.randint(0,23):02d}:00:00"]
            )
        self.conn.execute("COMMIT")
        print("  Data insert complete!")
    
    def run_benchmark(self, query: str, name: str, warmup: int = 1) -> BenchmarkResult:
        """Execute a query multiple times and measure performance."""
        # Warmup runs (not measured)
        for _ in range(warmup):
            self.conn.execute(query).fetchall()
        
        # Measured runs
        times: List[float] = []
        for _ in range(self.iterations):
            start = time.perf_counter()
            result = self.conn.execute(query).fetchall()
            end = time.perf_counter()
            times.append(end - start)
        
        result = BenchmarkResult(query_name=name, executions=times)
        self.results.append(result)
        return result
    
    def benchmark_simple_queries(self) -> None:
        """Benchmark common query patterns."""
        print("\n=== Running Simple Query Benchmarks ===\n")
        
        # Count queries
        self.run_benchmark("SELECT COUNT(*) FROM users", "Count users")
        self.run_benchmark("SELECT COUNT(*) FROM orders", "Count orders")
        
        # Filter queries
        self.run_benchmark(
            "SELECT * FROM orders WHERE user_id = 50", 
            "Filter by user_id"
        )
        
        # Aggregation
        self.run_benchmark(
            "SELECT category, AVG(price) FROM products GROUP BY category",
            "Average price by category"
        )
        
        # Join
        self.run_benchmark("""
            SELECT u.name, COUNT(o.order_id) as order_count
            FROM users u
            JOIN orders o ON o.user_id = u.user_id
            GROUP BY u.name
            ORDER BY order_count DESC
            LIMIT 10
        """, "User order counts (with join)")
        
    def benchmark_analytical_queries(self) -> None:
        """Benchmark analytical query patterns."""
        print("\n=== Running Analytical Query Benchmarks ===\n")
        
        # Time-series aggregation
        self.run_benchmark("""
            SELECT 
                CAST(order_date AS DATE) as date,
                COUNT(*) as orders,
                SUM(quantity) as total_items
            FROM orders
            GROUP BY date
            ORDER BY date
        """, "Daily order aggregation")
        
        # Multi-table join
        self.run_benchmark("""
            SELECT 
                u.name as user_name,
                p.category,
                SUM(o.quantity * p.price) as total_spent
            FROM users u
            JOIN orders o ON o.user_id = u.user_id
            JOIN products p ON o.product_id = p.product_id
            GROUP BY u.name, p.category
            ORDER BY total_spent DESC
            LIMIT 20
        """, "User spending by category")
        
        # Window functions
        self.run_benchmark("""
            SELECT 
                user_id,
                COUNT(*) as order_count,
                RANK() OVER (ORDER BY COUNT(*) DESC) as rank
            FROM orders
            GROUP BY user_id
            ORDER BY rank
        """, "User order ranking")
    
    def benchmark_write_operations(self) -> None:
        """Benchmark write operations."""
        print("\n=== Running Write Operation Benchmarks ===\n")
        
        # Create temp table for write tests
        self.conn.execute("CREATE TABLE bench_insert AS SELECT * FROM orders LIMIT 0")
        
        # Single insert
        self.run_benchmark(
            "INSERT INTO bench_insert SELECT * FROM orders LIMIT 100",
            "Insert 100 rows"
        )
        
        # Bulk insert
        self.run_benchmark(
            "INSERT INTO bench_insert SELECT * FROM orders LIMIT 10000",
            "Insert 10000 rows"
        )
        
        # Delete
        self.run_benchmark("DELETE FROM bench_insert WHERE order_id < 1000", "Delete 1000 rows")
    
    def print_results(self) -> None:
        """Print benchmark results in a formatted table."""
        print("\n" + "="*80)
        print("PERFORMANCE RESULTS".center(80))
        print("="*80)
        print(f"{'Query':<40} {'Avg(ms)':<12} {'Min(ms)':<10} {'Max(ms)':<10} {'Std(ms)':<10}")
        print("-"*80)
        
        for r in self.results:
            print(f"{r.query_name:<40} {r.avg_ms:<12.3f} {r.min_ms:<10.3f} {r.max_ms:<10.3f} {r.std_ms:<10.3f}")
        
        print("="*80)
    
    def get_connection_info(self) -> Dict:
        """Get DuckDB connection information."""
        return {
            "version": duckdb.__version__,
            "memory_usage": self._get_memory_usage()
        }
    
    def _get_memory_usage(self) -> str:
        """Get current memory usage from DuckDB."""
        # Sum all memory usage from duckdb_memory()
        result = self.conn.execute("""
            SELECT SUM(memory_usage_bytes) / (1024.0 * 1024.0) as memory_mb 
            FROM duckdb_memory()
        """).fetchone()
        if result and result[0] is not None:
            return f"{float(result[0]):.2f} MB"
        
        # Fallback: try different query
        try:
            result = self.conn.execute("PRAGMA memory_usage").fetchone()
            if result:
                return f"{result[0]}"
        except:
            pass
        return "N/A"
    
    def close(self) -> None:
        """Close the DuckDB connection."""
        self.conn.close()


def main():
    parser = argparse.ArgumentParser(description="DuckDB Performance Analyzer")
    parser.add_argument("--scale", type=int, default=10000, 
                       help="Number of rows to generate (default: 10000)")
    parser.add_argument("--iterations", type=int, default=5,
                       help="Number of iterations per benchmark (default: 5)")
    args = parser.parse_args()
    
    print(f"DuckDB Performance Analyzer")
    print(f"DuckDB Version: {duckdb.__version__}")
    print(f"Scale: {args.scale:,} rows")
    print(f"Iterations: {args.iterations}")
    
    analyzer = DuckDBAnalyzer(scale=args.scale, iterations=args.iterations)
    analyzer.setup_test_data()
    analyzer.benchmark_simple_queries()
    analyzer.benchmark_analytical_queries()
    analyzer.benchmark_write_operations()
    analyzer.print_results()
    
    info = analyzer.get_connection_info()
    print(f"\nMemory Usage: {info['memory_usage']}")
    
    analyzer.close()
    print("\nBenchmark complete!")


if __name__ == "__main__":
    main()
