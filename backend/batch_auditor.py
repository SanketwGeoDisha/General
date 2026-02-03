"""
SCALE Automated Batch College KPI Auditor
==========================================
Systematically processes multiple colleges with automatic API rotation,
Consolidated exports, Adaptive error handling, Logging, and Enhanced reporting.

Author: AskDiya v1
Version: 1.0
Date: February 2, 2026
"""

import os
import sys
import json
import csv
import asyncio
import logging
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
import traceback
from dotenv import load_dotenv
import requests
from collections import OrderedDict

# Import the main auditor class
try:
    from server import CollegeKPIAuditor, SourcePriorityClassifier, APIKeyExhaustedException
except ImportError:
    print("Error: Cannot import from server.py. Ensure this script is in the backend directory.")
    sys.exit(1)

# ============================================================================
# SCALE COMPONENTS
# ============================================================================

# S - Systematic Configuration
@dataclass
class AutomationConfig:
    """Systematic configuration for batch processing"""
    serper_api_keys: List[str]
    gemini_api_key: str
    output_dir: Path
    colleges_list: List[str]
    max_concurrent_audits: int = 3
    retry_on_failure: bool = True
    max_retries: int = 2
    delay_between_audits: float = 2.0
    export_formats: List[str] = None
    
    def __post_init__(self):
        if self.export_formats is None:
            self.export_formats = ["csv", "json"]
        self.output_dir.mkdir(parents=True, exist_ok=True)

# C - Consolidated Logging System
class AuditLogger:
    """Consolidated logging with multiple output streams"""
    
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Main log file
        self.main_log = log_dir / f"batch_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        # Error log file
        self.error_log = log_dir / f"errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        # Configure logging
        self.logger = logging.getLogger("BatchAuditor")
        self.logger.setLevel(logging.INFO)
        
        # File handler for main log
        fh_main = logging.FileHandler(self.main_log, encoding='utf-8')
        fh_main.setLevel(logging.INFO)
        
        # File handler for errors
        fh_error = logging.FileHandler(self.error_log, encoding='utf-8')
        fh_error.setLevel(logging.ERROR)
        
        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        
        # Formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh_main.setFormatter(formatter)
        fh_error.setFormatter(formatter)
        ch.setFormatter(formatter)
        
        self.logger.addHandler(fh_main)
        self.logger.addHandler(fh_error)
        self.logger.addHandler(ch)
    
    def info(self, message: str):
        self.logger.info(message)
    
    def error(self, message: str, exc_info: bool = False):
        self.logger.error(message, exc_info=exc_info)
    
    def warning(self, message: str):
        self.logger.warning(message)

# A - Adaptive API Key Manager
class APIKeyManager:
    """Adaptive rotation of Serper API keys with usage tracking"""
    
    def __init__(self, api_keys: List[str], logger: AuditLogger):
        self.api_keys = api_keys
        self.logger = logger
        self.current_index = 0
        self.usage_count = {key: 0 for key in api_keys}
        self.failed_keys = set()
        self.last_rotation_time = time.time()
    
    def get_current_key(self) -> Optional[str]:
        """Get current active API key"""
        if len(self.failed_keys) >= len(self.api_keys):
            self.logger.error("All API keys exhausted!")
            return None
        
        # Skip failed keys
        while self.api_keys[self.current_index] in self.failed_keys:
            self.current_index = (self.current_index + 1) % len(self.api_keys)
        
        return self.api_keys[self.current_index]
    
    def rotate_key(self, reason: str = "exhausted"):
        """Rotate to next available API key"""
        current_key = self.api_keys[self.current_index]
        
        if reason == "exhausted":
            self.failed_keys.add(current_key)
            self.logger.warning(f"API key {self.current_index + 1} exhausted, rotating...")
        
        self.current_index = (self.current_index + 1) % len(self.api_keys)
        
        # Skip failed keys
        attempts = 0
        while self.api_keys[self.current_index] in self.failed_keys and attempts < len(self.api_keys):
            self.current_index = (self.current_index + 1) % len(self.api_keys)
            attempts += 1
        
        new_key = self.get_current_key()
        if new_key:
            self.logger.info(f"Rotated to API key {self.current_index + 1}")
            self.last_rotation_time = time.time()
        else:
            self.logger.error("No more API keys available!")
    
    def mark_success(self):
        """Mark current key usage as successful"""
        current_key = self.get_current_key()
        if current_key:
            self.usage_count[current_key] += 1
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics"""
        return {
            "total_keys": len(self.api_keys),
            "active_keys": len(self.api_keys) - len(self.failed_keys),
            "failed_keys": len(self.failed_keys),
            "usage_per_key": self.usage_count
        }

# L - Layered Export System
class ExportManager:
    """Layered export system for CSV and JSON formats"""
    
    def __init__(self, output_dir: Path, logger: AuditLogger):
        self.output_dir = output_dir
        self.logger = logger
        self.csv_dir = output_dir / "csv_exports"
        self.json_dir = output_dir / "json_exports"
        self.csv_dir.mkdir(parents=True, exist_ok=True)
        self.json_dir.mkdir(parents=True, exist_ok=True)
    
    def export_csv(self, college_name: str, results: List[Dict], summary: Dict) -> bool:
        """Export audit results to CSV format"""
        try:
            safe_name = self._sanitize_filename(college_name)
            csv_path = self.csv_dir / f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                # Write college name header
                f.write(f'College Name,"{college_name}"\n')
                f.write('\n')
                
                # Write audit overview
                f.write('=== AUDIT OVERVIEW ===\n')
                f.write(f'Audit Date,"{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}"\n')
                f.write(f'Total KPIs,{summary.get("total_kpis", 0)}\n')
                f.write(f'Data Found,{summary.get("data_found", 0)}\n')
                f.write(f'Data Not Found,{summary.get("data_not_found", 0)}\n')
                f.write(f'High Confidence,{summary.get("high_confidence", 0)}\n')
                f.write(f'Coverage Percentage,{summary.get("coverage_percentage", 0)}%\n')
                f.write('\n')
                
                # Write category breakdown
                f.write('=== CATEGORY BREAKDOWN ===\n')
                f.write('Category,Found,Total,Percentage\n')
                for category, stats in summary.get("categories", {}).items():
                    total = stats.get('total', 0)
                    found = stats.get('found', 0)
                    percentage = round((found / total) * 100) if total > 0 else 0
                    f.write(f'"{category}",{found},{total},{percentage}%\n')
                f.write('\n')
                
                # Write KPI details
                f.write('=== KPI DETAILS ===\n')
                writer = csv.writer(f)
                writer.writerow([
                    'KPI Name', 'Category', 'Value', 'Evidence', 'Source URL',
                    'System Confidence', 'LLM Confidence', 'Source Priority', 'Data Year', 'Recency'
                ])
                
                for result in results:
                    writer.writerow([
                        result.get('kpi_name', ''),
                        result.get('category', ''),
                        result.get('value', ''),
                        result.get('evidence_quote', ''),
                        result.get('source_url', ''),
                        result.get('system_confidence', result.get('confidence', 'low')),
                        result.get('llm_confidence', 'low'),
                        result.get('source_priority', 'unknown'),
                        result.get('data_year', ''),
                        result.get('recency', 'unknown')
                    ])
            
            self.logger.info(f"CSV exported: {csv_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"CSV export failed for {college_name}: {e}", exc_info=True)
            return False
    
    def export_json(self, college_name: str, results: List[Dict], summary: Dict) -> bool:
        """Export audit results to JSON format"""
        try:
            safe_name = self._sanitize_filename(college_name)
            json_path = self.json_dir / f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            export_data = {
                "college_name": college_name,
                "audit_date": datetime.now().isoformat(),
                "summary": summary,
                "results": results
            }
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"JSON exported: {json_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"JSON export failed for {college_name}: {e}", exc_info=True)
            return False
    
    def export_consolidated_summary(self, all_results: List[Dict]) -> bool:
        """Export consolidated summary of all audits"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Consolidated CSV
            summary_csv = self.output_dir / f"consolidated_summary_{timestamp}.csv"
            with open(summary_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'College Name', 'Status', 'Total KPIs', 'Data Found', 'Coverage %',
                    'High Confidence Count', 'Duration (seconds)', 'Error Message'
                ])
                
                for result in all_results:
                    writer.writerow([
                        result.get('college_name', ''),
                        result.get('status', ''),
                        result.get('summary', {}).get('total_kpis', 0),
                        result.get('summary', {}).get('data_found', 0),
                        result.get('summary', {}).get('coverage_percentage', 0),
                        result.get('summary', {}).get('high_confidence', 0),
                        result.get('duration_seconds', 0),
                        result.get('error', '')
                    ])
            
            # Consolidated JSON
            summary_json = self.output_dir / f"consolidated_summary_{timestamp}.json"
            with open(summary_json, 'w', encoding='utf-8') as f:
                json.dump({
                    "batch_audit_date": datetime.now().isoformat(),
                    "total_colleges": len(all_results),
                    "successful": sum(1 for r in all_results if r.get('status') == 'completed'),
                    "failed": sum(1 for r in all_results if r.get('status') == 'failed'),
                    "colleges": all_results
                }, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"Consolidated summaries exported")
            return True
            
        except Exception as e:
            self.logger.error(f"Consolidated export failed: {e}", exc_info=True)
            return False
    
    def _sanitize_filename(self, name: str) -> str:
        """Sanitize college name for filename"""
        # Remove or replace invalid filename characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        return name[:100]  # Limit length

# E - Enhanced Batch Processor
class BatchAuditProcessor:
    """Enhanced batch processing with error handling and progress tracking"""
    
    def __init__(self, config: AutomationConfig):
        self.config = config
        self.logger = AuditLogger(config.output_dir / "logs")
        self.api_manager = APIKeyManager(config.serper_api_keys, self.logger)
        self.export_manager = ExportManager(config.output_dir, self.logger)
        self.results: List[Dict] = []
        self.start_time = None
        self.end_time = None
    
    async def process_single_college(self, college_name: str, index: int, total: int) -> Dict[str, Any]:
        """Process a single college audit"""
        self.logger.info(f"\n{'='*80}")
        self.logger.info(f"Processing [{index}/{total}]: {college_name}")
        self.logger.info(f"{'='*80}")
        
        start_time = time.time()
        result = {
            "college_name": college_name,
            "index": index,
            "status": "pending",
            "results": [],
            "summary": {},
            "duration_seconds": 0,
            "error": None
        }
        
        retry_count = 0
        max_retries = self.config.max_retries if self.config.retry_on_failure else 0
        
        while retry_count <= max_retries:
            try:
                # Get current API key
                current_api_key = self.api_manager.get_current_key()
                if not current_api_key:
                    raise Exception("No available API keys")
                
                # Update environment variable for the auditor
                os.environ['SERPER_API_KEY'] = current_api_key
                
                # Create auditor instance with current API key
                auditor = CollegeKPIAuditor()
                
                # Run audit
                self.logger.info(f"Starting audit for {college_name} (API Key #{self.api_manager.current_index + 1})")
                
                async def progress_callback(message: str, progress: int):
                    self.logger.info(f"[{college_name}] {progress}% - {message}")
                
                results = await auditor.run_audit(college_name, progress_callback)
                
                # Mark API key usage as successful
                self.api_manager.mark_success()
                
                # Generate summary
                summary = self._generate_summary(results)
                
                result.update({
                    "status": "completed",
                    "results": results,
                    "summary": summary,
                    "duration_seconds": round(time.time() - start_time, 2)
                })
                
                # Export results
                if "csv" in self.config.export_formats:
                    self.export_manager.export_csv(college_name, results, summary)
                
                if "json" in self.config.export_formats:
                    self.export_manager.export_json(college_name, results, summary)
                
                self.logger.info(f"✓ Completed {college_name} in {result['duration_seconds']}s")
                break  # Success, exit retry loop
                
            except APIKeyExhaustedException as e:
                # Specific handling for 400 Bad Request errors
                error_msg = str(e)
                self.logger.warning(f"400 Bad Request detected for {college_name}: {error_msg}")
                self.logger.warning(f"Rotating API key and retrying...")
                self.api_manager.rotate_key(reason="exhausted")
                retry_count += 1
                if retry_count <= max_retries:
                    self.logger.info(f"Retrying {college_name} with new API key (attempt {retry_count + 1}/{max_retries + 1})")
                    await asyncio.sleep(2)  # Wait before retry
                    continue
                else:
                    result.update({
                        "status": "failed",
                        "error": f"All API keys exhausted: {error_msg}",
                        "duration_seconds": round(time.time() - start_time, 2)
                    })
                    break
                
            except Exception as e:
                error_msg = str(e)
                self.logger.error(f"✗ Error processing {college_name}: {error_msg}", exc_info=True)
                
                # Check if it's a 400 Bad Request error (API key issue)
                if "400" in error_msg and "Bad Request" in error_msg:
                    self.logger.warning(f"400 Bad Request detected for {college_name}, rotating API key...")
                    self.api_manager.rotate_key(reason="exhausted")
                    retry_count += 1
                    if retry_count <= max_retries:
                        self.logger.info(f"Retrying {college_name} with new API key (attempt {retry_count + 1}/{max_retries + 1})")
                        await asyncio.sleep(2)  # Wait before retry
                        continue
                # Check if it's an API quota error
                elif "quota" in error_msg.lower() or "limit" in error_msg.lower() or "429" in error_msg:
                    self.logger.warning("API quota exhausted, rotating key...")
                    self.api_manager.rotate_key(reason="exhausted")
                    retry_count += 1
                    if retry_count <= max_retries:
                        self.logger.info(f"Retrying {college_name} (attempt {retry_count + 1}/{max_retries + 1})")
                        await asyncio.sleep(5)  # Wait before retry
                        continue
                
                # For other errors, retry if configured
                if retry_count < max_retries:
                    retry_count += 1
                    self.logger.info(f"Retrying {college_name} (attempt {retry_count + 1}/{max_retries + 1})")
                    await asyncio.sleep(3)
                else:
                    result.update({
                        "status": "failed",
                        "error": error_msg,
                        "duration_seconds": round(time.time() - start_time, 2)
                    })
                    break
        
        return result
    
    async def process_batch(self):
        """Process entire batch of colleges"""
        self.start_time = time.time()
        self.logger.info(f"\n{'#'*80}")
        self.logger.info(f"BATCH AUDIT STARTED")
        self.logger.info(f"Total Colleges: {len(self.config.colleges_list)}")
        self.logger.info(f"Available API Keys: {len(self.config.serper_api_keys)}")
        self.logger.info(f"Max Concurrent Audits: {self.config.max_concurrent_audits}")
        self.logger.info(f"{'#'*80}\n")
        
        total_colleges = len(self.config.colleges_list)
        
        # Process colleges with controlled concurrency
        for i in range(0, total_colleges, self.config.max_concurrent_audits):
            batch = self.config.colleges_list[i:i + self.config.max_concurrent_audits]
            tasks = []
            
            for idx, college in enumerate(batch, start=i + 1):
                tasks.append(self.process_single_college(college, idx, total_colleges))
            
            # Wait for batch to complete
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in batch_results:
                if isinstance(result, Exception):
                    self.logger.error(f"Batch processing exception: {result}")
                else:
                    self.results.append(result)
            
            # Delay between batches
            if i + self.config.max_concurrent_audits < total_colleges:
                self.logger.info(f"\nWaiting {self.config.delay_between_audits}s before next batch...\n")
                await asyncio.sleep(self.config.delay_between_audits)
        
        self.end_time = time.time()
        
        # Generate consolidated summary
        self._print_final_summary()
        self.export_manager.export_consolidated_summary(self.results)
    
    def _generate_summary(self, results: List[Dict]) -> Dict[str, Any]:
        """Generate summary statistics for audit results"""
        total = len(results)
        found = sum(1 for r in results if str(r.get('value', '')).lower() not in 
                   ['data not found', 'error', 'processing error', 'not available', ''])
        high_conf = sum(1 for r in results if r.get('system_confidence') == 'high' or r.get('confidence') == 'high')
        medium_conf = sum(1 for r in results if r.get('system_confidence') == 'medium' or r.get('confidence') == 'medium')
        
        # Source priority breakdown
        source_priority_breakdown = {'high': 0, 'medium': 0, 'low': 0}
        for r in results:
            priority = r.get('source_priority', 'unknown')
            if priority in source_priority_breakdown:
                source_priority_breakdown[priority] += 1
        
        # Group by category
        categories = {}
        for r in results:
            cat = r.get('category', 'Other')
            if cat not in categories:
                categories[cat] = {'total': 0, 'found': 0}
            categories[cat]['total'] += 1
            if str(r.get('value', '')).lower() not in ['data not found', 'error', 'processing error', '']:
                categories[cat]['found'] += 1
        
        return {
            "total_kpis": total,
            "data_found": found,
            "data_not_found": total - found,
            "high_confidence": high_conf,
            "medium_confidence": medium_conf,
            "coverage_percentage": round((found / total) * 100, 1) if total > 0 else 0,
            "source_priority_breakdown": source_priority_breakdown,
            "categories": categories
        }
    
    def _print_final_summary(self):
        """Print final batch processing summary"""
        duration = self.end_time - self.start_time
        successful = sum(1 for r in self.results if r.get('status') == 'completed')
        failed = sum(1 for r in self.results if r.get('status') == 'failed')
        
        self.logger.info(f"\n{'#'*80}")
        self.logger.info(f"BATCH AUDIT COMPLETED")
        self.logger.info(f"{'#'*80}")
        self.logger.info(f"Total Colleges Processed: {len(self.results)}")
        self.logger.info(f"Successful: {successful}")
        self.logger.info(f"Failed: {failed}")
        self.logger.info(f"Total Duration: {duration:.2f} seconds ({duration/60:.2f} minutes)")
        self.logger.info(f"Average Time per College: {duration/len(self.results):.2f} seconds")
        
        # API usage stats
        api_stats = self.api_manager.get_usage_stats()
        self.logger.info(f"\nAPI Key Usage:")
        self.logger.info(f"  Total Keys: {api_stats['total_keys']}")
        self.logger.info(f"  Active Keys: {api_stats['active_keys']}")
        self.logger.info(f"  Exhausted Keys: {api_stats['failed_keys']}")
        
        self.logger.info(f"\nExport Locations:")
        self.logger.info(f"  CSV: {self.export_manager.csv_dir}")
        self.logger.info(f"  JSON: {self.export_manager.json_dir}")
        self.logger.info(f"  Logs: {self.logger.log_dir}")
        self.logger.info(f"{'#'*80}\n")

# ============================================================================
# MAIN EXECUTION
# ============================================================================

async def main():
    """Main execution function"""
    
    # Load environment variables
    load_dotenv()
    
    # ============================================================================
    # CONFIGURATION - UPDATE THESE VALUES
    # ============================================================================
    
    # Multiple Serper API keys (add as many as you have)
    SERPER_API_KEYS = [
        os.environ.get("SERPER_API_KEY"),
        os.environ.get("SERPER_API_KEY_2"),
        os.environ.get("SERPER_API_KEY_3"),
        os.environ.get("SERPER_API_KEY_4"),
        os.environ.get("SERPER_API_KEY_5"),
        # Add more keys as needed
    ]
    
    # Filter out None values
    SERPER_API_KEYS = [key for key in SERPER_API_KEYS if key]
    
    if not SERPER_API_KEYS:
        print("Error: No Serper API keys found in environment variables!")
        print("Please add SERPER_API_KEY, SERPER_API_KEY_2, etc. to your .env file")
        return
    
    # Gemini API key
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY not found in environment variables!")
        return
    
    # List of colleges to audit
    COLLEGES_LIST = [
        "IIT Bombay",
        "IIT Delhi",
        "IIT Madras",
        "IIT Kanpur",
        "IIT Kharagpur",
        "IIT Roorkee",
        "IIT Guwahati",
        "IIT Hyderabad",
        "NIT Trichy",
        "NIT Warangal",
        "NIT Surathkal",
        "NIT Rourkela",
        "BITS Pilani",
        "VIT Vellore",
        "Manipal Institute of Technology",
        "SRM Institute of Science and Technology",
        "Amity University Noida",
        "Delhi Technological University",
        "Anna University",
        "Jadavpur University",
    ]
    
    # Alternatively, load colleges from a text file (one college per line)
    colleges_file = Path(__file__).parent / "colleges_list.txt"
    if colleges_file.exists():
        with open(colleges_file, 'r', encoding='utf-8') as f:
            file_colleges = [line.strip() for line in f if line.strip()]
        if file_colleges:
            COLLEGES_LIST = file_colleges
            print(f"✓ Loaded {len(COLLEGES_LIST)} colleges from {colleges_file}")
    
    # Output directory
    OUTPUT_DIR = Path(__file__).parent / "batch_audit_outputs"
    
    # Configuration
    config = AutomationConfig(
        serper_api_keys=SERPER_API_KEYS,
        gemini_api_key=GEMINI_API_KEY,
        output_dir=OUTPUT_DIR,
        colleges_list=COLLEGES_LIST,
        max_concurrent_audits=2,  # Process 2 colleges at a time
        retry_on_failure=True,
        max_retries=2,
        delay_between_audits=3.0,  # 3 seconds between batches
        export_formats=["csv", "json"]
    )
    
    # ============================================================================
    # START BATCH PROCESSING
    # ============================================================================
    
    print(f"\n{'='*80}")
    print(f"SCALE Automated Batch College KPI Auditor")
    print(f"{'='*80}")
    print(f"Configuration:")
    print(f"  - Total Colleges: {len(config.colleges_list)}")
    print(f"  - API Keys Available: {len(config.serper_api_keys)}")
    print(f"  - Max Concurrent: {config.max_concurrent_audits}")
    print(f"  - Output Directory: {config.output_dir}")
    print(f"  - Export Formats: {', '.join(config.export_formats)}")
    print(f"{'='*80}\n")
    
    processor = BatchAuditProcessor(config)
    await processor.process_batch()
    
    print(f"\n{'='*80}")
    print(f"✓ Batch processing completed successfully!")
    print(f"✓ Check {OUTPUT_DIR} for all exports and logs")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())
