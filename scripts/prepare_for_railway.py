#!/usr/bin/env python3
"""
Script to prepare the NYAI Backend for Railway deployment by optimizing knowledge base files.
This script should be run before pushing to GitHub for deployment.
"""

import os
import shutil
import pandas as pd
from pathlib import Path

def main():
    """Prepare knowledge base files for Railway deployment."""
    print("Preparing NYAI Backend for Railway deployment...")
    
    # Get the project root directory
    project_root = Path(__file__).parent.parent.absolute()
    knowledge_base_dir = project_root / "knowledge_base"
    
    # Create backup directory
    backup_dir = project_root / "knowledge_base_backup"
    backup_dir.mkdir(exist_ok=True)
    
    # Check if knowledge base directory exists
    if not knowledge_base_dir.exists():
        print(f"Error: Knowledge base directory not found at {knowledge_base_dir}")
        return
    
    # Check for CSV files
    csv_files = list(knowledge_base_dir.glob("*.csv"))
    if not csv_files:
        print(f"Error: No CSV files found in knowledge base directory: {knowledge_base_dir}")
        return
    
    print(f"Found {len(csv_files)} CSV files in knowledge base")
    
    # Process each CSV file
    for file_path in csv_files:
        print(f"Processing {file_path.name}...")
        
        # Create backup
        backup_path = backup_dir / file_path.name
        shutil.copy2(file_path, backup_path)
        print(f"  - Created backup at {backup_path}")
        
        # Load and optimize CSV
        try:
            df = pd.read_csv(file_path)
            original_size = file_path.stat().st_size
            
            # Basic optimizations
            # 1. Remove duplicate rows
            df = df.drop_duplicates()
            
            # 2. Convert string columns to lowercase for consistency
            for col in df.columns:
                if df[col].dtype == 'object':  # String columns
                    df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
            
            # 3. Remove rows with empty content
            content_cols = ['content', 'text', 'description', 'body']
            content_cols = [col for col in content_cols if col in df.columns]
            
            if content_cols:
                # Check if any content column is empty
                for col in content_cols:
                    df = df[df[col].notna() & (df[col] != '')]
            
            # Save optimized file
            df.to_csv(file_path, index=False)
            new_size = file_path.stat().st_size
            
            # Report optimization results
            size_reduction = original_size - new_size
            percent_reduction = (size_reduction / original_size) * 100 if original_size > 0 else 0
            
            print(f"  - Optimized file size: {new_size / 1024:.2f} KB")
            print(f"  - Size reduction: {size_reduction / 1024:.2f} KB ({percent_reduction:.2f}%)")
            print(f"  - Rows after optimization: {len(df)}")
        
        except Exception as e:
            print(f"  - Error processing {file_path.name}: {e}")
            # Restore from backup if processing failed
            shutil.copy2(backup_path, file_path)
            print(f"  - Restored original file from backup")
    
    print("\nKnowledge base preparation complete!")
    print("You can now deploy to Railway following the instructions in RAILWAY_DEPLOYMENT.md")
    
if __name__ == "__main__":
    main() 