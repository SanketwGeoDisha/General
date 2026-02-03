"""
NIRF Data Collector Module - Enhanced Multi-Level Discovery
============================================================
Comprehensive NIRF document discovery using multi-phase approach:
Phase 1: Sitemap + Multi-level crawl
Phase 2: Intelligent filtering (keyword matching)
Phase 3: Document discovery in priority pages
Phase 4: Direct NIRF portal search

Author: AskDiya v1
Date: February 3, 2026
"""

import asyncio
import aiohttp
import re
from urllib.parse import urlparse, urljoin
from xml.etree import ElementTree as ET
from typing import Set, List, Dict, Optional, Tuple
from dataclasses import dataclass
from collections import deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class NIRFDocument:
    """NIRF document with metadata"""
    url: str
    title: str
    doc_type: str  # 'pdf', 'excel', 'html', 'webpage'
    year: Optional[int] = None
    category: Optional[str] = None  # 'overall', 'engineering', 'management', etc.
    priority_score: float = 0.0
    source: str = "crawl"  # 'crawl', 'sitemap', 'nirfindia.org'


class NIRFCollector:
    """
    Enhanced NIRF data collection with multi-level discovery.
    
    Strategy:
    1. Search nirfindia.org for official NIRF data pages
    2. Search college website sitemap for NIRF pages
    3. Multi-level BFS crawl to find NIRF pages (especially campus-specific pages)
    4. Extract NIRF PDFs/documents from discovered pages
    5. Classify and prioritize by year and relevance
    """
    
    # Common NIRF-related URL patterns (HIGH PRIORITY)
    NIRF_URL_PATTERNS = [
        r'nirf',
        r'ranking',
        r'rankings',
        r'national.*rank',
        r'india.*rank',
        r'rank.*india',
        r'data.*template',  # NIRF data template submissions
        r'metrics.*report',
        r'institutional.*ranking',
        r'mhrd.*rank',
    ]
    
    # NIRF keywords for deep crawling - Focus on 2025
    NIRF_KEYWORDS = [
        'nirf 2025', 'nirf-2025', 'nirf2025',
        'nirf', 'ranking', 'rankings', 'national ranking', 'india rankings',
        'nirf data', 'nirf submission', 'nirf report', 'nirf metrics', 'nirf score',
        'overall ranking', 'engineering ranking', 'management ranking',
        'nirf rank', 'ranked', 'rank india', 'india rank',
        'nirf india', 'mhrd ranking', 'ministry ranking',
        'national institutional ranking', 'institutional ranking framework'
    ]
    
    # NIRF document years to prioritize (most recent first)
    PRIORITY_YEARS = [2025, 2024, 2023, 2022, 2021]
    
    # File extensions for NIRF documents
    NIRF_DOC_EXTENSIONS = ['.pdf', '.xlsx', '.xls', '.doc', '.docx']
    
    # Ignored patterns to skip
    IGNORED_PATTERNS = [
        'login', 'signup', 'register', 'cart', 'checkout',
        'gallery', 'photo', 'video', 'event', 'notice',
        'admission', 'application', 'brochure', 'prospectus',
        'news', 'blog', 'article', 'announcement'
    ]
    
    def __init__(self, timeout: int = 30, max_depth: int = 4, max_urls: int = 1000):
        """
        Initialize NIRF collector.
        
        Args:
            timeout: Request timeout in seconds
            max_depth: Maximum crawl depth (4 is good for finding campus-specific NIRF pages)
            max_urls: Maximum URLs to discover
        """
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.max_depth = max_depth
        self.max_urls = max_urls
    
    async def collect_nirf_data(self, college_name: str, base_url: str) -> Dict[str, List[NIRFDocument]]:
        """
        Main entry point: Collect all NIRF-related data for a college.
        
        Args:
            college_name: Name of the college
            base_url: College website URL
            
        Returns:
            Dict with keys:
                - 'nirfindia': NIRF official portal documents
                - 'college_website': Documents from college website
                - 'all': All discovered NIRF documents sorted by priority
        """
        all_nirf_urls: Set[str] = set()
        nirf_documents: List[NIRFDocument] = []
        
        logger.info(f"[NIRF COLLECTOR] Starting comprehensive NIRF data collection for {college_name}")
        
        # ============ PHASE 1: Official NIRF Portal ============
        logger.info(f"  [Phase 1] Searching nirfindia.org...")
        nirfindia_docs = await self.search_nirfindia_org(college_name)
        nirf_documents.extend(nirfindia_docs)
        logger.info(f"  [Phase 1] Found {len(nirfindia_docs)} documents from nirfindia.org")
        
        # ============ PHASE 2: College Website Sitemap ============
        logger.info(f"  [Phase 2] Checking college website sitemap...")
        sitemap_urls = await self.fetch_sitemap_urls(base_url)
        nirf_sitemap_urls = self._filter_nirf_urls(sitemap_urls)
        all_nirf_urls.update(nirf_sitemap_urls)
        logger.info(f"  [Phase 2] Found {len(nirf_sitemap_urls)} NIRF-related URLs from sitemap")
        
        # ============ PHASE 3: Multi-Level Crawl for NIRF Pages ============
        logger.info(f"  [Phase 3] Multi-level crawl for NIRF pages (depth={self.max_depth})...")
        crawled_urls = await self.multi_level_nirf_crawl(base_url)
        all_nirf_urls.update(crawled_urls)
        logger.info(f"  [Phase 3] Found {len(crawled_urls)} additional NIRF URLs from crawling")
        
        # ============ PHASE 4: Document Discovery in NIRF Pages ============
        logger.info(f"  [Phase 4] Extracting NIRF documents from discovered pages...")
        
        # Classify preliminary URLs
        preliminary_docs = self._classify_urls(list(all_nirf_urls), base_url)
        
        # Find HTML pages with high NIRF scores
        nirf_html_pages = [
            doc for doc in preliminary_docs 
            if doc.doc_type in ('html', 'webpage') and doc.priority_score >= 5
        ]
        
        # Initialize page context for year inference
        page_context = {}
        
        # Extract documents from these pages
        if nirf_html_pages:
            doc_urls_with_context = await self.discover_nirf_documents_in_pages(nirf_html_pages[:25], base_url)
            all_nirf_urls.update([url for url, _ in doc_urls_with_context])
            logger.info(f"  [Phase 4] Found {len(doc_urls_with_context)} NIRF documents inside pages")
            
            # Store context for year inference
            page_context = {url: year for url, year in doc_urls_with_context}
        
        # ============ PHASE 5: Classification & Prioritization ============
        logger.info(f"  [Phase 5] Classifying and prioritizing documents...")
        nirf_documents.extend(self._classify_urls(list(all_nirf_urls), base_url))
        
        # Infer year from parent pages for documents without year
        for doc in nirf_documents:
            if doc.year is None and doc.url in page_context:
                doc.year = page_context[doc.url]
                doc.priority_score += 10.0 if doc.year == 2025 else 0  # Boost 2025 docs
        
        # Remove duplicates
        unique_docs = {}
        for doc in nirf_documents:
            if doc.url not in unique_docs:
                unique_docs[doc.url] = doc
            elif doc.priority_score > unique_docs[doc.url].priority_score:
                # Keep higher priority version
                unique_docs[doc.url] = doc
        
        nirf_documents = list(unique_docs.values())
        
        # Sort by priority (year + score)
        nirf_documents.sort(key=lambda x: (x.year or 0, x.priority_score), reverse=True)
        
        # FILTER: Prioritize NIRF 2025 documents only
        nirf_2025 = [doc for doc in nirf_documents if doc.year == 2025]
        
        if nirf_2025:
            logger.info(f"[NIRF COLLECTOR] Found {len(nirf_2025)} NIRF 2025 documents - using only 2025 data")
            nirf_documents = nirf_2025  # Use only 2025 documents
        else:
            # Fallback: Use latest year available if 2025 not found
            latest_year = max([doc.year for doc in nirf_documents if doc.year], default=None)
            if latest_year:
                nirf_documents = [doc for doc in nirf_documents if doc.year == latest_year]
                logger.warning(f"[NIRF COLLECTOR] No 2025 data found, using latest year: {latest_year} ({len(nirf_documents)} docs)")
            else:
                logger.warning(f"[NIRF COLLECTOR] No year-specific NIRF data found")
        
        # Separate by source
        nirfindia_docs = [doc for doc in nirf_documents if doc.source == 'nirfindia.org']
        college_docs = [doc for doc in nirf_documents if doc.source != 'nirfindia.org']
        
        logger.info(f"[NIRF COLLECTOR] Complete: {len(nirfindia_docs)} from nirfindia.org, "
                   f"{len(college_docs)} from college website, {len(nirf_documents)} total (filtered for latest year)")
        
        return {
            'nirfindia': nirfindia_docs,
            'college_website': college_docs,
            'all': nirf_documents
        }
    
    async def search_nirfindia_org(self, college_name: str) -> List[NIRFDocument]:
        """
        Search nirfindia.org for official NIRF data about the college.
        """
        documents = []
        
        # Build search URLs for nirfindia.org - NIRF 2025 ONLY
        # Note: nirfindia.org has specific URL patterns for college data
        search_patterns = [
            f"https://www.nirfindia.org/2025/EngineeringRanking.html",
            f"https://www.nirfindia.org/2025/OverallRanking.html",
            f"https://www.nirfindia.org/2025/ManagementRanking.html",
            f"https://www.nirfindia.org/2025/PharmacyRanking.html",
        ]
        
        async with aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session:
            for url in search_patterns:
                try:
                    async with session.get(url, ssl=False) as response:
                        if response.status == 200:
                            html = await response.text()
                            
                            # Look for college name in the HTML
                            if college_name.lower() in html.lower():
                                # Extract year from URL
                                year_match = re.search(r'/(\d{4})/', url)
                                year = int(year_match.group(1)) if year_match else None
                                
                                # Determine category
                                category = 'overall'
                                if 'Engineering' in url:
                                    category = 'engineering'
                                elif 'Management' in url:
                                    category = 'management'
                                
                                doc = NIRFDocument(
                                    url=url,
                                    title=f"NIRF {year} {category.title()} Rankings",
                                    doc_type='html',
                                    year=year,
                                    category=category,
                                    priority_score=10.0,  # Highest priority
                                    source='nirfindia.org'
                                )
                                documents.append(doc)
                                logger.info(f"  Found NIRF {year} {category} ranking page for {college_name}")
                
                except Exception as e:
                    logger.debug(f"  Could not fetch {url}: {e}")
                    continue
                
                await asyncio.sleep(0.1)  # Be polite
        
        return documents
    
    async def multi_level_nirf_crawl(self, base_url: str) -> Set[str]:
        """
        BFS crawl specifically looking for NIRF-related pages.
        Goes deeper than regular crawl because NIRF pages can be nested
        (e.g., homepage -> campus page -> NIRF page -> NIRF PDFs).
        """
        discovered_urls: Set[str] = set()
        visited: Set[str] = set()
        
        # BFS queue: (url, depth)
        queue = deque([(base_url, 0)])
        
        # Parse base domain
        parsed_base = urlparse(base_url)
        base_domain = parsed_base.netloc.replace('www.', '')
        
        async with aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session:
            while queue and len(discovered_urls) < self.max_urls:
                url, depth = queue.popleft()
                
                if url in visited:
                    continue
                visited.add(url)
                
                if depth > self.max_depth:
                    continue
                
                try:
                    async with session.get(url, ssl=False, allow_redirects=True) as response:
                        if response.status != 200:
                            continue
                        
                        content_type = response.headers.get('content-type', '')
                        
                        # If it's a document, just add it
                        if 'text/html' not in content_type:
                            if self._is_nirf_related(url):
                                discovered_urls.add(url)
                            continue
                        
                        html = await response.text()
                        
                        # Extract all links
                        page_urls = self._extract_urls_from_html(html, url, base_domain)
                        
                        # Filter for NIRF-related URLs
                        for page_url in page_urls:
                            if self._is_nirf_related(page_url):
                                discovered_urls.add(page_url)
                                
                                # Add to crawl queue if it's an HTML page
                                url_lower = page_url.lower()
                                is_doc = any(url_lower.endswith(ext) for ext in self.NIRF_DOC_EXTENSIONS)
                                
                                if page_url not in visited and not is_doc:
                                    # Priority crawling for NIRF pages
                                    if depth < self.max_depth:
                                        queue.append((page_url, depth + 1))
                
                except Exception as e:
                    logger.debug(f"  Crawl error for {url}: {e}")
                    continue
                
                await asyncio.sleep(0.08)  # Small delay
        
        return discovered_urls
    
    async def discover_nirf_documents_in_pages(self, nirf_pages: List[NIRFDocument], 
                                                 base_url: str) -> List[tuple]:
        """
        Fetch NIRF-related pages and extract document links from them.
        Critical for finding NIRF PDFs that aren't in sitemaps.
        
        Returns:
            List of tuples (url, inferred_year) where inferred_year comes from parent page
        """
        doc_urls_with_year: List[tuple] = []
        seen_urls: Set[str] = set()
        
        parsed_base = urlparse(base_url)
        base_domain = parsed_base.netloc.replace('www.', '')
        
        logger.info(f"  Extracting documents from {len(nirf_pages)} NIRF pages...")
        
        async with aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session:
            for page in nirf_pages:
                logger.info(f"  Fetching page: {page.url}")
                try:
                    async with session.get(page.url, ssl=False, allow_redirects=True) as response:
                        if response.status != 200:
                            continue
                        
                        html = await response.text()
                        
                        # Find all NIRF document links with comprehensive patterns
                        doc_patterns = [
                            # PDFs with various naming patterns
                            r'href=["\']([^"\']*/[^"\']*\.pdf)["\']',  # Any PDF
                            r'href=["\']([^"\']*/attachments/[^"\']*\.pdf)["\']',  # Attachment PDFs
                            r'href=["\']([^"\']*/document/[^"\']*\.pdf)["\']',  # Document PDFs
                            r'href=["\']([^"\']*/uploads/[^"\']*\.pdf)["\']',  # Upload PDFs
                            r'href=["\']([^"\']*/wp-content/[^"\']*\.pdf)["\']',  # WordPress PDFs
                            # Excel files
                            r'href=["\']([^"\']*\.xlsx?)["\']',
                            # Direct NIRF references
                            r'href=["\']([^"\']*/nirf[^"\']*\.pdf)["\']',
                            r'href=["\']([^"\']*/NIRF[^"\']*\.pdf)["\']',
                        ]
                        
                        for pattern in doc_patterns:
                            for match in re.findall(pattern, html, re.IGNORECASE):
                                try:
                                    abs_url = urljoin(page.url, match)
                                    parsed = urlparse(abs_url)
                                    url_domain = parsed.netloc.replace('www.', '')
                                    
                                    if url_domain == base_domain and abs_url not in seen_urls:
                                        # Check if it looks like a NIRF document
                                        url_lower = abs_url.lower()
                                        if any(kw in url_lower for kw in ['nirf', 'ranking', 'data', 'engineering', 'overall', 'management', 'pharmacy', 'attachments/8', 'attachments/7', 'attachments/6']):
                                            seen_urls.add(abs_url)
                                            doc_urls_with_year.append((abs_url, page.year))
                                            logger.info(f"  Found document: {abs_url} (year from parent: {page.year})")
                                except:
                                    continue
                
                except Exception as e:
                    logger.debug(f"  Could not fetch page {page.url}: {e}")
                    continue
                
                await asyncio.sleep(0.05)
        
        return doc_urls_with_year
    
    async def fetch_sitemap_urls(self, base_url: str) -> Set[str]:
        """Fetch URLs from sitemap.xml"""
        urls: Set[str] = set()
        parsed = urlparse(base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        
        sitemap_paths = [
            "/sitemap.xml",
            "/sitemap_index.xml",
            "/sitemap/sitemap.xml",
            "/wp-sitemap.xml",
        ]
        
        async with aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session:
            for sitemap_path in sitemap_paths:
                sitemap_url = base + sitemap_path
                try:
                    async with session.get(sitemap_url, ssl=False) as response:
                        if response.status == 200:
                            content = await response.text()
                            parsed_urls = self._parse_sitemap_xml(content)
                            urls.update(parsed_urls)
                            if urls:
                                break
                except:
                    continue
        
        return urls
    
    def _parse_sitemap_xml(self, xml_content: str) -> Set[str]:
        """Parse sitemap XML"""
        urls: Set[str] = set()
        
        try:
            xml_content = re.sub(r'\sxmlns="[^"]+"', '', xml_content)
            root = ET.fromstring(xml_content)
            
            for url_tag in root.findall('.//url'):
                loc = url_tag.find('loc')
                if loc is not None and loc.text:
                    urls.add(loc.text.strip())
            
            for loc in root.findall('.//loc'):
                if loc.text:
                    urls.add(loc.text.strip())
        except:
            # Regex fallback
            url_pattern = re.compile(r'<loc>\s*(https?://[^<]+)\s*</loc>')
            for match in url_pattern.finditer(xml_content):
                urls.add(match.group(1).strip())
        
        return urls
    
    def _extract_urls_from_html(self, html: str, current_url: str, base_domain: str) -> Set[str]:
        """Extract URLs from HTML"""
        urls = set()
        
        href_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
        src_pattern = re.compile(r'src=["\']([^"\']+)["\']', re.IGNORECASE)
        
        for pattern in [href_pattern, src_pattern]:
            for match in pattern.findall(html):
                try:
                    if match.startswith(('#', 'javascript:', 'mailto:', 'tel:', 'data:')):
                        continue
                    
                    abs_url = urljoin(current_url, match)
                    parsed = urlparse(abs_url)
                    url_domain = parsed.netloc.replace('www.', '')
                    
                    if url_domain == base_domain:
                        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                        if parsed.query:
                            clean_url += f"?{parsed.query}"
                        urls.add(clean_url)
                except:
                    continue
        
        return urls
    
    def _is_nirf_related(self, url: str) -> bool:
        """Check if URL is NIRF-related"""
        url_lower = url.lower()
        url_normalized = url_lower.replace('%20', ' ').replace('-', ' ').replace('_', ' ')
        
        # Skip ignored patterns
        if any(pattern in url_lower for pattern in self.IGNORED_PATTERNS):
            return False
        
        # Direct NIRF indicators (high confidence)
        direct_indicators = [
            'nirf', 'ranking', 'national rank', 'india rank',
            'engineering.pdf', 'overall.pdf', 'management.pdf',
            'pharmacy.pdf', 'innovation.pdf'
        ]
        
        for indicator in direct_indicators:
            if indicator in url_lower:
                return True
        
        # Check if it's a document in a NIRF-related path
        if url_lower.endswith('.pdf') or url_lower.endswith(('.xlsx', '.xls')):
            # Check for attachment IDs (common in CMS systems for recent documents)
            # e.g., /attachments/8177/ likely contains recent 2025 data
            if '/attachments/' in url_lower or '/document/' in url_lower:
                # Accept documents with high attachment IDs (likely recent)
                attachment_match = re.search(r'/attachments/(\d+)/', url_lower)
                if attachment_match:
                    attachment_id = int(attachment_match.group(1))
                    if attachment_id > 6000:  # Recent documents typically have higher IDs
                        return True
        
        # Check NIRF patterns
        for pattern in self.NIRF_URL_PATTERNS:
            if re.search(pattern, url_normalized):
                return True
        
        # Check NIRF keywords
        for keyword in self.NIRF_KEYWORDS:
            if keyword.lower() in url_normalized:
                return True
        
        return False
    
    def _filter_nirf_urls(self, urls: Set[str]) -> Set[str]:
        """Filter URLs for NIRF-related content"""
        return {url for url in urls if self._is_nirf_related(url)}
    
    def _classify_urls(self, urls: List[str], base_url: str) -> List[NIRFDocument]:
        """Classify URLs into NIRFDocument objects"""
        documents = []
        
        for url in urls:
            url_lower = url.lower()
            
            # Skip ignored patterns
            if any(pattern in url_lower for pattern in self.IGNORED_PATTERNS):
                continue
            
            # Determine document type
            doc_type = self._get_doc_type(url)
            
            # Extract year
            year = self._extract_year(url)
            
            # Determine category
            category = self._determine_category(url)
            
            # Calculate priority score
            score = self._calculate_priority_score(url, year, category)
            
            # Generate title
            title = self._generate_title(url, year, category)
            
            doc = NIRFDocument(
                url=url,
                title=title,
                doc_type=doc_type,
                year=year,
                category=category,
                priority_score=score,
                source='crawl' if base_url in url else 'external'
            )
            
            documents.append(doc)
        
        return documents
    
    def _get_doc_type(self, url: str) -> str:
        """Determine document type"""
        url_lower = url.lower()
        if url_lower.endswith('.pdf'):
            return 'pdf'
        elif url_lower.endswith(('.xls', '.xlsx')):
            return 'excel'
        elif url_lower.endswith(('.doc', '.docx')):
            return 'word'
        elif url_lower.endswith(('.html', '.htm', '.php', '.aspx')):
            return 'html'
        return 'webpage'
    
    def _extract_year(self, url: str) -> Optional[int]:
        """Extract year from URL"""
        # Look for 4-digit year (2020-2027)
        year_match = re.search(r'(202[0-7])', url)
        if year_match:
            return int(year_match.group(1))
        return None
    
    def _determine_category(self, url: str) -> Optional[str]:
        """Determine NIRF category"""
        url_lower = url.lower()
        
        if 'engineering' in url_lower:
            return 'engineering'
        elif 'management' in url_lower:
            return 'management'
        elif 'pharmacy' in url_lower:
            return 'pharmacy'
        elif 'overall' in url_lower:
            return 'overall'
        
        return None
    
    def _calculate_priority_score(self, url: str, year: Optional[int], 
                                   category: Optional[str]) -> float:
        """Calculate priority score for document"""
        score = 5.0  # Base score
        
        # Year bonus (2025 gets massive priority)
        if year:
            if year == 2025:
                score += 10.0  # MAXIMUM priority for 2025
            elif year == 2024:
                score += 2.0   # Much lower priority for older years
            elif year == 2023:
                score += 1.0
            else:
                score += 0.5   # Minimal priority for 2022 and older
        
        # Category bonus
        if category in ['overall', 'engineering']:
            score += 2.0
        
        # Document type bonus
        url_lower = url.lower()
        if url_lower.endswith('.pdf'):
            score += 3.0  # PDFs are valuable
        elif url_lower.endswith(('.xls', '.xlsx')):
            score += 4.0  # Excel files often have raw data
        
        # Keyword bonuses
        if 'data' in url_lower and 'template' in url_lower:
            score += 3.0  # NIRF data template submissions
        
        if 'metrics' in url_lower or 'report' in url_lower:
            score += 2.0
        
        return score
    
    def _generate_title(self, url: str, year: Optional[int], category: Optional[str]) -> str:
        """Generate human-readable title"""
        parts = []
        
        if year:
            parts.append(f"NIRF {year}")
        else:
            parts.append("NIRF")
        
        if category:
            parts.append(category.title())
        
        # Add doc type hint
        url_lower = url.lower()
        if 'data' in url_lower and 'template' in url_lower:
            parts.append("Data Template")
        elif 'metrics' in url_lower:
            parts.append("Metrics Report")
        elif url_lower.endswith('.pdf'):
            parts.append("PDF")
        elif url_lower.endswith(('.xls', '.xlsx')):
            parts.append("Data Sheet")
        
        return " ".join(parts)


# Convenience function
async def collect_nirf_for_college(college_name: str, base_url: str) -> Dict[str, List[NIRFDocument]]:
    """Collect all NIRF data for a college."""
    collector = NIRFCollector(max_depth=4, max_urls=1000)
    return await collector.collect_nirf_data(college_name, base_url)


# Test function
if __name__ == "__main__":
    import sys
    
    async def test():
        college_name = sys.argv[1] if len(sys.argv) > 1 else "RV College of Engineering"
        base_url = sys.argv[2] if len(sys.argv) > 2 else "https://rvce.edu.in/"
        
        print(f"Testing NIRF collection for: {college_name}")
        print(f"Website: {base_url}\n")
        
        collector = NIRFCollector()
        results = await collector.collect_nirf_data(college_name, base_url)
        
        print(f"\n=== NIRF Portal Documents ({len(results['nirfindia'])}) ===")
        for doc in results['nirfindia'][:10]:
            print(f"  [{doc.year}] {doc.title}")
            print(f"      {doc.url}")
            print(f"      Score: {doc.priority_score}\n")
        
        print(f"\n=== College Website NIRF Documents ({len(results['college_website'])}) ===")
        for doc in results['college_website'][:15]:
            print(f"  [{doc.year}] {doc.title}")
            print(f"      {doc.url}")
            print(f"      Score: {doc.priority_score}\n")
        
        print(f"\n=== Total NIRF Documents: {len(results['all'])} ===")
    
    asyncio.run(test())
