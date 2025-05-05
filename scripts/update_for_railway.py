#!/usr/bin/env python3
"""
Script to update environment files and prepare deployment to Railway.
This script ensures all required configuration is in place before deploying.
"""

import os
import shutil
import sys
import subprocess
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

console = Console()

def check_requirements():
    """Check if all requirements for deployment are met."""
    requirements = [
        ("Dockerfile", os.path.exists("Dockerfile")),
        ("railway.toml", os.path.exists("railway.toml")),
        (".dockerignore", os.path.exists(".dockerignore")),
        ("prepare_for_railway.py", os.path.exists("scripts/prepare_for_railway.py")),
        ("check_deployment.py", os.path.exists("scripts/check_deployment.py")),
        ("RAILWAY_DEPLOYMENT.md", os.path.exists("RAILWAY_DEPLOYMENT.md")),
    ]
    
    missing = [req[0] for req in requirements if not req[1]]
    
    if missing:
        console.print("[bold red]❌ Missing required files for Railway deployment:[/bold red]")
        for file in missing:
            console.print(f"  - {file}")
        return False
    
    return True

def update_env_file():
    """Update .env.production file with Railway compatible settings."""
    env_example = Path(".env.example")
    env_production = Path(".env.production")
    
    # Create .env.production if it doesn't exist
    if not env_production.exists():
        if env_example.exists():
            shutil.copy(env_example, env_production)
            console.print("[green]Created .env.production from .env.example[/green]")
        else:
            console.print("[bold red]❌ .env.example not found[/bold red]")
            return False
    
    # Read the current .env.production
    with open(env_production, 'r') as f:
        lines = f.readlines()
    
    # Update with Railway-specific settings
    railway_settings = {
        "HOST": "0.0.0.0",
        "PORT": "${PORT}",  # Railway provides PORT automatically
        "FLASK_ENV": "production",
        "DEBUG": "false",
        "LOG_LEVEL": "INFO",
        "KNOWLEDGE_BASE_DIR": "/app/knowledge_base",
        "VECTOR_DB_PATH": "/data/vector_db",
        "SESSION_DB_PATH": "/data/sessions",
        "ENABLE_AUTH": "true",
        "API_KEY": "${API_KEY}",  # Will be set in Railway environment variables
        "CORS_ORIGINS": "*"  # Adjust as needed for production
    }
    
    new_lines = []
    updated_keys = set()
    
    # Update existing keys
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            new_lines.append(line)
            continue
            
        if '=' in line:
            key = line.split('=')[0].strip()
            if key in railway_settings:
                new_lines.append(f"{key}={railway_settings[key]}")
                updated_keys.add(key)
            else:
                new_lines.append(line)
    
    # Add any missing Railway settings
    for key, value in railway_settings.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")
    
    # Write the updated .env.production
    with open(env_production, 'w') as f:
        f.write('\n'.join(new_lines) + '\n')
    
    console.print("[green]✅ Updated .env.production with Railway settings[/green]")
    return True

def check_knowledge_base():
    """Check if knowledge base files are ready for deployment."""
    kb_dir = Path("knowledge_base")
    
    if not kb_dir.exists() or not list(kb_dir.glob("*.csv")):
        console.print("[bold yellow]⚠️  No knowledge base files found[/bold yellow]")
        if Confirm.ask("Would you like to run the prepare_for_railway.py script to set up knowledge base files?"):
            try:
                subprocess.run([sys.executable, "scripts/prepare_for_railway.py"], check=True)
                console.print("[green]✅ Knowledge base preparation complete[/green]")
            except subprocess.CalledProcessError:
                console.print("[bold red]❌ Knowledge base preparation failed[/bold red]")
                return False
        else:
            console.print("[yellow]Skipping knowledge base preparation[/yellow]")
    else:
        console.print("[green]✅ Knowledge base files found[/green]")
    
    return True

def stage_for_commit():
    """Stage deployment files for commit."""
    try:
        # Check if in a git repository
        subprocess.run(["git", "status"], check=True, stdout=subprocess.DEVNULL)
        
        # Stage deployment files
        files_to_stage = [
            "Dockerfile",
            "railway.toml",
            ".dockerignore",
            ".env.production",
            "RAILWAY_DEPLOYMENT.md"
        ]
        
        for file in files_to_stage:
            if os.path.exists(file):
                subprocess.run(["git", "add", file], check=True)
        
        console.print("[green]✅ Staged deployment files for commit[/green]")
        
        # Prepare commit message
        commit_msg = "Prepare for Railway deployment"
        if Confirm.ask("Would you like to commit the changes now?"):
            # Get custom commit message if desired
            custom_msg = Prompt.ask("Enter a commit message", default=commit_msg)
            subprocess.run(["git", "commit", "-m", custom_msg], check=True)
            console.print("[green]✅ Changes committed[/green]")
            
            # Ask about pushing to GitHub
            if Confirm.ask("Would you like to push to GitHub now?"):
                branch = subprocess.check_output(["git", "branch", "--show-current"]).decode().strip()
                subprocess.run(["git", "push", "origin", branch], check=True)
                console.print(f"[green]✅ Changes pushed to {branch}[/green]")
    
    except subprocess.CalledProcessError:
        console.print("[yellow]⚠️  Not in a git repository or git command failed[/yellow]")
    except Exception as e:
        console.print(f"[bold red]❌ Error: {str(e)}[/bold red]")

def main():
    """Run the Railway preparation script."""
    console.print(Panel.fit(
        "[bold]NYAI Backend Railway Deployment Preparation[/bold]",
        border_style="cyan"
    ))
    
    # Check requirements
    if not check_requirements():
        console.print("[bold red]❌ Please create the missing files before proceeding[/bold red]")
        return
    
    # Update environment file
    if not update_env_file():
        console.print("[bold red]❌ Failed to update environment file[/bold red]")
        return
    
    # Check knowledge base
    if not check_knowledge_base():
        console.print("[bold yellow]⚠️ Knowledge base preparation skipped or failed[/bold yellow]")
    
    # Stage files for commit
    stage_for_commit()
    
    # Final instructions
    console.print(Panel.fit(
        "[bold green]✅ Railway deployment preparation complete![/bold green]\n\n"
        "Next steps:\n"
        "1. Connect your GitHub repository to Railway\n"
        "2. Create a new service in Railway from your repository\n"
        "3. Set required environment variables including API_KEY\n"
        "4. Add a persistent volume for the /data directory\n"
        "5. Deploy your application\n"
        "6. Use scripts/check_deployment.py to verify your deployment",
        title="Success",
        border_style="green"
    ))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Preparation cancelled by user[/yellow]")
        sys.exit(0) 