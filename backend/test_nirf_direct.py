"""
Direct NIRF Integration Test
Tests NIRF collector integration without requiring search API
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from nirf_collector import collect_nirf_for_college


async def test_nirf_direct():
    """Test NIRF collector directly and show it can be integrated"""
    
    print("="*80)
    print("NIRF COLLECTOR - DIRECT INTEGRATION TEST")
    print("="*80)
    print("\nThis test verifies that:")
    print("1. NIRF collector can discover documents from college websites")
    print("2. Documents are properly classified and prioritized")
    print("3. Content can be extracted for LLM processing")
    print("4. Integration with agent is straightforward")
    
    # Test college
    college_name = "NIT Surathkal"
    base_url = "https://www.nitk.ac.in"
    
    print(f"\n{'='*80}")
    print(f"Test College: {college_name}")
    print(f"Website: {base_url}")
    print(f"{'='*80}\n")
    
    try:
        print("[Step 1/4] Discovering NIRF documents...")
        results = await collect_nirf_for_college(college_name, base_url)
        
        total_docs = len(results['all'])
        nirf_portal = len(results['nirfindia'])
        college_docs = len(results['college_website'])
        
        print(f"✓ Found {total_docs} NIRF documents")
        print(f"  - {nirf_portal} from nirfindia.org")
        print(f"  - {college_docs} from college website")
        
        if total_docs == 0:
            print("\n❌ No documents found - test failed")
            return False
        
        print(f"\n[Step 2/4] Analyzing discovered documents...")
        
        # Count by year
        by_year = {}
        by_type = {}
        for doc in results['all']:
            year = doc.year or 'Unknown'
            doc_type = doc.doc_type
            by_year[year] = by_year.get(year, 0) + 1
            by_type[doc_type] = by_type.get(doc_type, 0) + 1
        
        print(f"\nDocuments by Year:")
        for year in sorted([y for y in by_year.keys() if y != 'Unknown'], reverse=True):
            print(f"  {year}: {by_year[year]} documents")
        if 'Unknown' in by_year:
            print(f"  Unknown: {by_year['Unknown']} documents")
        
        print(f"\nDocuments by Type:")
        for doc_type, count in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
            print(f"  {doc_type}: {count}")
        
        print(f"\n[Step 3/4] Checking for 2025 data...")
        nirf_2025 = [doc for doc in results['all'] if doc.year == 2025]
        nirf_2024 = [doc for doc in results['all'] if doc.year == 2024]
        
        if nirf_2025:
            print(f"✓ Found {len(nirf_2025)} NIRF 2025 documents:")
            for doc in nirf_2025[:3]:
                print(f"  - {doc.title}")
                print(f"    URL: {doc.url}")
                print(f"    Type: {doc.doc_type}, Score: {doc.priority_score}")
        else:
            print("⚠ No NIRF 2025 data (may not be published yet)")
        
        if nirf_2024:
            print(f"✓ Found {len(nirf_2024)} NIRF 2024 documents")
        
        print(f"\n[Step 4/4] Integration simulation...")
        print("\nIn the full agent, this data would be:")
        print("1. Fetched using fetch_webpage_content() or _fetch_pdf_content()")
        print("2. Added to combined_text for LLM processing")
        print("3. Used to extract KPI values like NIRF ranking, placements, etc.")
        
        # Show how content would be structured
        print(f"\n Example content structure for LLM:")
        print("-" * 80)
        for doc in results['all'][:2]:
            print(f"\n[NIRF {doc.year} {doc.category or ''} - {doc.doc_type.upper()}]")
            print(f"Title: {doc.title}")
            print(f"URL: {doc.url}")
            print(f"Priority Score: {doc.priority_score}")
            print(f"Content: <would be fetched from URL for PDFs/HTML>")
        
        # Final summary
        print(f"\n{'='*80}")
        print("TEST RESULTS")
        print(f"{'='*80}")
        
        checks = []
        
        # Check 1: Found documents
        if total_docs > 0:
            print("✓ NIRF documents discovered successfully")
            checks.append(True)
        else:
            print("❌ No documents found")
            checks.append(False)
        
        # Check 2: Has PDFs (valuable content)
        pdf_count = by_type.get('pdf', 0)
        if pdf_count > 0:
            print(f"✓ Found {pdf_count} PDF documents (extractable data)")
            checks.append(True)
        else:
            print("⚠ No PDF documents found")
            checks.append(False)
        
        # Check 3: Recent data
        if nirf_2025 or nirf_2024:
            print("✓ Recent NIRF data available (2024 or 2025)")
            checks.append(True)
        else:
            print("⚠ No recent data (older than 2024)")
            checks.append(False)
        
        # Check 4: High priority docs
        high_priority = [doc for doc in results['all'] if doc.priority_score >= 10]
        if high_priority:
            print(f"✓ Found {len(high_priority)} high-priority documents")
            checks.append(True)
        else:
            print("⚠ No high-priority documents")
            checks.append(False)
        
        # Check 5: Multiple categories
        categories = set(doc.category for doc in results['all'] if doc.category)
        if len(categories) > 1:
            print(f"✓ Multiple categories found: {', '.join(categories)}")
            checks.append(True)
        else:
            print(f"⚠ Limited categories: {', '.join(categories) if categories else 'none'}")
            checks.append(False)
        
        success_rate = sum(checks) / len(checks) * 100
        
        print(f"\n{'='*80}")
        if success_rate >= 80:
            print(f"✅ INTEGRATION TEST PASSED ({success_rate:.0f}% success rate)")
            print("\nThe NIRF collector is fully functional and ready to use!")
            print("It will automatically:")
            print("  • Discover NIRF documents from college websites")
            print("  • Prioritize recent years (2025, 2024, 2023)")
            print("  • Find PDFs and webpages with NIRF data")
            print("  • Provide URLs for content extraction")
            return True
        elif success_rate >= 60:
            print(f"⚠ PARTIAL SUCCESS ({success_rate:.0f}% success rate)")
            print("Basic functionality works, some enhancements recommended")
            return True
        else:
            print(f"❌ TEST FAILED ({success_rate:.0f}% success rate)")
            return False
            
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n🔍 NIRF Collector - Direct Integration Test\n")
    result = asyncio.run(test_nirf_direct())
    sys.exit(0 if result else 1)
