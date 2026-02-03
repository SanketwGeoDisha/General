"""
Full Agent Integration Test
Test that the NIRF collector properly integrates with the main CollegeKPIAuditor
"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from server import CollegeKPIAuditor


async def test_agent_nirf_integration():
    """Test that the agent can use NIRF collector to gather data"""
    
    print("="*80)
    print("FULL AGENT INTEGRATION TEST - NIRF Data Collection")
    print("="*80)
    
    # Check if NIRF collector is available
    try:
        from nirf_collector import NIRFCollector, collect_nirf_for_college
        print("\n✓ NIRF Collector module imported successfully")
    except ImportError as e:
        print(f"\n❌ Failed to import NIRF Collector: {e}")
        return False
    
    # Initialize auditor
    try:
        auditor = CollegeKPIAuditor()
        print("✓ CollegeKPIAuditor initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize auditor: {e}")
        return False
    
    # Test college
    college_name = "NIT Surathkal"
    print(f"\n{'='*80}")
    print(f"Testing data collection for: {college_name}")
    print(f"{'='*80}\n")
    
    # Progress callback
    async def progress_callback(message, progress):
        print(f"  [{progress}%] {message}")
    
    try:
        # Gather official data (this should trigger NIRF collector)
        print("[PHASE 1] Gathering official data (includes NIRF discovery)...")
        all_data = await auditor.gather_official_data(college_name, progress_callback)
        
        # Check NIRF data
        print(f"\n[PHASE 2] Analyzing collected NIRF data...")
        nirf_data = all_data.get("nirf", [])
        
        if nirf_data:
            print(f"✓ Found {len(nirf_data)} NIRF data sources")
            
            # Count by year
            years = {}
            content_count = 0
            for item in nirf_data:
                year = item.get('year', 'unknown')
                years[year] = years.get(year, 0) + 1
                if item.get('content'):
                    content_count += 1
            
            print(f"\nNIRF Data by Year:")
            for year in sorted(years.keys(), reverse=True):
                print(f"  - {year}: {years[year]} documents")
            
            print(f"\n✓ {content_count} documents have extracted content")
            
            # Show sample of extracted content
            print(f"\n[PHASE 3] Sample of extracted NIRF content:")
            print("-" * 80)
            for i, item in enumerate(nirf_data[:3], 1):
                year = item.get('year', 'N/A')
                title = item.get('title', 'Unknown')
                url = item.get('url', 'N/A')
                content = item.get('content', '')
                
                print(f"\n{i}. [{year}] {title}")
                print(f"   URL: {url}")
                if content:
                    print(f"   Content Length: {len(content)} characters")
                    print(f"   Preview: {content[:200]}...")
                else:
                    print(f"   Content: Not extracted (snippet only)")
            
            # Check combined text
            combined_text = all_data.get("combined_text", "")
            nirf_in_combined = combined_text.count("[NIRF")
            print(f"\n✓ NIRF data appears {nirf_in_combined} times in combined_text")
            
            # Success criteria
            print(f"\n{'='*80}")
            print("INTEGRATION TEST RESULTS")
            print(f"{'='*80}")
            
            success = True
            if len(nirf_data) > 0:
                print("✓ NIRF collector discovered documents")
            else:
                print("❌ No NIRF documents discovered")
                success = False
            
            if content_count > 0:
                print("✓ Content extracted from NIRF documents")
            else:
                print("⚠ No content extracted (check PDF/HTML fetching)")
            
            if nirf_in_combined > 0:
                print("✓ NIRF data included in combined_text for LLM")
            else:
                print("❌ NIRF data not added to combined_text")
                success = False
            
            if any(item.get('year') == 2025 for item in nirf_data):
                print("✓ NIRF 2025 data available")
            elif any(item.get('year') == 2024 for item in nirf_data):
                print("✓ NIRF 2024 data available (2025 may not be published)")
            else:
                print("⚠ No recent NIRF data (2024/2025)")
            
            if success:
                print(f"\n✅ FULL INTEGRATION TEST PASSED")
                print(f"   Agent can successfully collect and process NIRF data")
                return True
            else:
                print(f"\n⚠ PARTIAL SUCCESS - Some features need attention")
                return False
                
        else:
            print("❌ No NIRF data collected")
            print("   This could indicate:")
            print("   - NIRF collector not being called")
            print("   - Integration issue between collector and agent")
            return False
            
    except Exception as e:
        print(f"\n❌ Integration test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n🔍 Testing Full Agent Integration with NIRF Collector\n")
    
    # Check environment
    if not os.environ.get("SERPER_API_KEY"):
        print("⚠ Warning: SERPER_API_KEY not set. Some features may not work.")
    
    if not os.environ.get("GEMINI_API_KEY"):
        print("⚠ Warning: GEMINI_API_KEY not set. LLM processing will fail.")
    
    # Run test
    result = asyncio.run(test_agent_nirf_integration())
    
    sys.exit(0 if result else 1)
