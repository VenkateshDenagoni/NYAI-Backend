#!/usr/bin/env python3
"""
Script to check NYAI Backend deployment on Railway.
This script can be run to verify the deployment status and system health.
"""

import os
import sys
import json
import time
import argparse
import requests
from rich.console import Console
from rich.table import Table
from rich import print as rprint

# Initialize rich console
console = Console()

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Check NYAI Backend deployment status on Railway")
    parser.add_argument("--url", required=True, help="Base URL of the deployed application (e.g., https://nyai-backend-production.up.railway.app)")
    parser.add_argument("--api-key", help="API key for authenticated endpoints")
    parser.add_argument("--check-interval", type=int, default=60, help="Interval in seconds between checks")
    parser.add_argument("--max-checks", type=int, default=10, help="Maximum number of checks")
    return parser.parse_args()

def check_health(base_url):
    """Check the health endpoint."""
    try:
        response = requests.get(f"{base_url}/health", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"status": "error", "error": str(e)}

def check_rag_status(base_url):
    """Check the RAG status endpoint."""
    try:
        response = requests.get(f"{base_url}/api/rag/status", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"status": "error", "error": str(e)}

def test_query(base_url, api_key=None):
    """Test a simple RAG query."""
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    
    payload = {
        "query": "What is Article 21 of the Indian Constitution?",
        "search_method": "hybrid"
    }
    
    try:
        response = requests.post(
            f"{base_url}/api/rag/query", 
            json=payload,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        
        # Process the streaming response
        lines = response.text.strip().split('\n')
        responses = [json.loads(line) for line in lines if line.strip()]
        
        # Check if we got an init message and at least some content
        has_init = any(r.get("type") == "init" for r in responses)
        content_parts = [r.get("data", {}).get("content", "") for r in responses if r.get("type") == "content"]
        content = "".join(content_parts)
        
        return {
            "status": "success" if has_init and content else "partial",
            "response_length": len(content),
            "has_init": has_init,
            "has_content": bool(content),
            "response_sample": content[:100] + "..." if len(content) > 100 else content
        }
    except requests.exceptions.RequestException as e:
        return {"status": "error", "error": str(e)}

def display_results(health_data, rag_status, query_results):
    """Display the results in a nicely formatted table."""
    # Health status table
    health_table = Table(title="System Health Status")
    health_table.add_column("Component", style="cyan")
    health_table.add_column("Status", style="green")
    
    health_table.add_row("Overall Status", health_data.get("status", "unknown"))
    
    # Add dependency status if available
    deps = health_data.get("dependencies", {})
    for dep_name, dep_status in deps.items():
        health_table.add_row(f"  {dep_name}", dep_status)
    
    # RAG status table
    rag_table = Table(title="RAG System Status")
    rag_table.add_column("Component", style="cyan")
    rag_table.add_column("Value", style="green")
    
    rag_table.add_row("Status", rag_status.get("status", "unknown"))
    
    # Add component status if available
    for comp_name, comp_status in rag_status.get("components", {}).items():
        rag_table.add_row(f"  {comp_name}", comp_status)
    
    rag_table.add_row("Document Count", str(rag_status.get("documents", {}).get("count", 0)))
    rag_table.add_row("Active Sessions", str(rag_status.get("sessions", {}).get("active_count", 0)))
    rag_table.add_row("Version", rag_status.get("version", "unknown"))
    
    # Query test table
    query_table = Table(title="Query Test Results")
    query_table.add_column("Metric", style="cyan")
    query_table.add_column("Value", style="green")
    
    query_table.add_row("Status", query_results.get("status", "unknown"))
    
    if "error" in query_results:
        query_table.add_row("Error", query_results["error"])
    else:
        query_table.add_row("Response Length", str(query_results.get("response_length", 0)))
        query_table.add_row("Has Init Message", "✅" if query_results.get("has_init") else "❌")
        query_table.add_row("Has Content", "✅" if query_results.get("has_content") else "❌")
        if query_results.get("response_sample"):
            query_table.add_row("Sample Response", query_results.get("response_sample", ""))
    
    # Print all tables
    console.print(health_table)
    console.print(rag_table)
    console.print(query_table)

def main():
    """Run the deployment check."""
    args = parse_args()
    
    console.print(f"[bold cyan]Checking NYAI Backend deployment at {args.url}[/bold cyan]")
    
    for check_num in range(1, args.max_checks + 1):
        console.print(f"\n[bold]Check {check_num}/{args.max_checks}[/bold] - {time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Perform checks
        health_data = check_health(args.url)
        rag_status = check_rag_status(args.url)
        
        # Only test query if health check passed
        if health_data.get("status") == "healthy":
            query_results = test_query(args.url, args.api_key)
        else:
            query_results = {"status": "skipped", "error": "Health check failed"}
        
        # Display results
        display_results(health_data, rag_status, query_results)
        
        # Check if all systems are fully operational
        all_systems_go = (
            health_data.get("status") == "healthy" and
            rag_status.get("status") == "healthy" and
            query_results.get("status") == "success"
        )
        
        if all_systems_go:
            console.print("\n[bold green]✅ All systems operational![/bold green]")
            break
        elif check_num < args.max_checks:
            console.print(f"\n[yellow]Some components not fully operational yet. Waiting {args.check_interval} seconds before next check...[/yellow]")
            time.sleep(args.check_interval)
        else:
            console.print("\n[bold red]❌ Not all systems are operational after maximum checks.[/bold red]")
            console.print("[yellow]Check the Railway logs for more information.[/yellow]")
    
    if "error" in health_data:
        console.print("\n[bold red]Health check failed:[/bold red]")
        console.print(f"[red]{health_data['error']}[/red]")
        console.print("\n[yellow]Possible causes:[/yellow]")
        console.print("1. Deployment is still in progress")
        console.print("2. Application crashed during startup")
        console.print("3. URL is incorrect")
        console.print("4. Railway service is down")
        
        console.print("\n[yellow]Troubleshooting steps:[/yellow]")
        console.print("1. Check Railway logs")
        console.print("2. Verify environment variables are set correctly")
        console.print("3. Check if knowledge base files are available")
        console.print("4. Try redeploying the application")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Check cancelled by user[/yellow]")
        sys.exit(0) 