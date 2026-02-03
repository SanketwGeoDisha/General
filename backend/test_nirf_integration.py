"""
Test NIRF Integration
Verify that the NIRF collector can discover and extract data from NIRF documents
"""

import asyncio
import sys
from nirf_collector import NIRFCollector, collect_nirf_for_college


async def test_nirf_collector():
    """Test NIRF collector with a known college"""
    
    # Test with NITK (known to have accessible NIRF data)
    college_name = "NIT Surathkal"
    base_url = "https://www.nitk.ac.in"
    
    print("="*80)
    print(f"Testing NIRF Collector for: {college_name}")
    print(f"Website: {base_url}")
    print("="*80)
    
    try:
        # Initialize collector
        collector = NIRFCollector(max_depth=3, max_urls=500, timeout=30)
        print("\n[1/5] Initializing NIRF Collector... ✓")
        
        # Collect NIRF data
        print(f"[2/5] Starting comprehensive NIRF discovery...")
        results = await collector.collect_nirf_data(college_name, base_url)
        print(f"[2/5] Discovery complete ✓")
        
        # Display results
        print(f"\n[3/5] Processing Results:")
        print(f"  - Found {len(results['nirfindia'])} documents from nirfindia.org")
        print(f"  - Found {len(results['college_website'])} documents from college website")
        print(f"  - Total: {len(results['all'])} NIRF documents")
        
        # Show top priority documents
        print(f"\n[4/5] Top Priority NIRF Documents (by year and score):")
        print("-" * 80)
        
        for i, doc in enumerate(results['all'][:10], 1):
            year_str = f"[{doc.year}]" if doc.year else "[N/A]"
            category_str = f"({doc.category})" if doc.category else ""
            print(f"\n  {i}. {year_str} {doc.title} {category_str}")
            print(f"     Type: {doc.doc_type} | Score: {doc.priority_score:.1f}")
            print(f"     URL: {doc.url}")
        
        # Verify 2025 data if available
        print(f"\n[5/5] Checking for NIRF 2025 data:")
        nirf_2025_docs = [doc for doc in results['all'] if doc.year == 2025]
        nirf_2024_docs = [doc for doc in results['all'] if doc.year == 2024]
        nirf_2023_docs = [doc for doc in results['all'] if doc.year == 2023]
        
        if nirf_2025_docs:
            print(f"  ✓ Found {len(nirf_2025_docs)} NIRF 2025 documents")
            for doc in nirf_2025_docs[:3]:
                print(f"    - {doc.title}")
        else:
            print(f"  ⚠ No NIRF 2025 documents found (may not be available yet)")
        
        if nirf_2024_docs:
            print(f"  ✓ Found {len(nirf_2024_docs)} NIRF 2024 documents")
        
        if nirf_2023_docs:
            print(f"  ✓ Found {len(nirf_2023_docs)} NIRF 2023 documents")
        
        # Summary
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        
        if len(results['all']) > 0:
            print("✓ NIRF Collector is working correctly")
            print(f"✓ Successfully discovered {len(results['all'])} NIRF documents")
            
            # Check if we have recent data
            recent_years = [2025, 2024, 2023]
            has_recent = any(doc.year in recent_years for doc in results['all'])
            if has_recent:
                print("✓ Recent NIRF data (2023-2025) is available")
            else:
                print("⚠ No recent NIRF data found (check if college has submitted)")
            
            # Check nirfindia.org
            if results['nirfindia']:
                print(f"✓ Found data from nirfindia.org (official portal)")
            else:
                print("⚠ No data from nirfindia.org (may need to check college name spelling)")
            
            print("\n✅ Integration test PASSED")
            return True
        else:
            print("❌ No NIRF documents found")
            print("⚠ This could mean:")
            print("  - College website doesn't have NIRF pages")
            print("  - NIRF pages are behind login/authentication")
            print("  - College name needs exact match")
            return False
            
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_with_custom_college():
    """Test with user-provided college"""
    if len(sys.argv) > 1:
        college_name = sys.argv[1]
        base_url = sys.argv[2] if len(sys.argv) > 2 else None
        
        if not base_url:
            print(f"Testing with: {college_name}")
            print("Note: No URL provided, using search only")
            return
        
        print(f"\nTesting custom college: {college_name}")
        print(f"Website: {base_url}\n")
        
        results = await collect_nirf_for_college(college_name, base_url)
        
        print(f"Results for {college_name}:")
        print(f"  - Total documents: {len(results['all'])}")
        print(f"  - From nirfindia.org: {len(results['nirfindia'])}")
        print(f"  - From college website: {len(results['college_website'])}")
        
        if results['all']:
            print("\nTop 5 documents:")
            for doc in results['all'][:5]:
                print(f"  - [{doc.year}] {doc.title}")
                print(f"    {doc.url}")


if __name__ == "__main__":
    print("\n🔍 NIRF Collector Integration Test\n")
    
    # Run main test
    result = asyncio.run(test_nirf_collector())
    
    # Test with custom college if provided
    if len(sys.argv) > 1:
        print("\n" + "="*80)
        asyncio.run(test_with_custom_college())
    
    sys.exit(0 if result else 1)
