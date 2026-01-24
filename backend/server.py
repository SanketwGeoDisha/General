from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
import json
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone
import asyncio
import requests
import google.generativeai as genai
import re
from urllib.parse import urlparse, quote
from bs4 import BeautifulSoup
import time

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# In-memory storage for audits
audits_store: Dict[str, Dict[str, Any]] = {}

# ============ KPI Schema with Search Keywords ============

KPI_SCHEMA = {
    "college_kpis": [
        {
            "field_name": "ict_enabled_learning_infrastructure",
            "display_name": "ICT-Enabled Learning Infrastructure",
            "category": "Academic Infrastructure",
            "data_type": "boolean",
            "unit": "yes/no",
            "validation_rules": "true or false only",
            "extraction_instruction": "Set true if ICT infrastructure (smart classrooms, learning management systems, digital labs) is explicitly mentioned/implemented, false if explicitly stated as not available, null if unclear.",
            "example_value": True,
            "remarks_required": True,
            "search_keywords": ["smart classroom", "ICT infrastructure", "LMS learning management", "digital classroom", "e-learning platform", "virtual lab", "online learning"]
        },
        {
            "field_name": "digital_library_access",
            "display_name": "Digital Library Access",
            "category": "Academic Infrastructure",
            "data_type": "boolean",
            "unit": "yes/no",
            "validation_rules": "true or false only",
            "extraction_instruction": "Set true if digital/e-library access is available to students, false if not available, null if unclear.",
            "example_value": True,
            "remarks_required": True,
            "search_keywords": ["digital library", "e-library", "online library", "e-resources", "e-journals", "DELNET", "NDL", "online database"]
        },
        {
            "field_name": "male_hostels_college_managed",
            "display_name": "Male Hostels Managed by College",
            "category": "Campus Facilities",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer or 0",
            "extraction_instruction": "Count of male hostel facilities directly managed/operated by the college. If unavailable, set 0.",
            "example_value": 5,
            "remarks_required": False,
            "search_keywords": ["boys hostel", "male hostel", "men hostel", "hostel accommodation", "hostel capacity", "number of hostels"]
        },
        {
            "field_name": "female_hostels_college_managed",
            "display_name": "Female Hostels Managed by College",
            "category": "Campus Facilities",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer or 0",
            "extraction_instruction": "Count of female hostel facilities directly managed/operated by the college. If unavailable, set 0.",
            "example_value": 4,
            "remarks_required": False,
            "search_keywords": ["girls hostel", "female hostel", "women hostel", "ladies hostel", "hostel for girls", "women accommodation"]
        },
        {
            "field_name": "smart_campus_erp_implementation",
            "display_name": "Smart Campus / ERP Implementation",
            "category": "Technology Infrastructure",
            "data_type": "boolean",
            "unit": "yes/no",
            "validation_rules": "true or false only",
            "extraction_instruction": "Set true if smart campus initiatives or ERP systems are implemented, false if not, null if unclear.",
            "example_value": True,
            "remarks_required": True,
            "search_keywords": ["ERP system", "smart campus", "campus management system", "student portal", "digital campus", "automation"]
        },
        {
            "field_name": "courses_list",
            "display_name": "List of Courses",
            "category": "Academic Programs",
            "data_type": "array",
            "unit": "names",
            "validation_rules": "array of strings",
            "extraction_instruction": "Array containing names of all courses/programs offered. Extract full program names.",
            "example_value": ["Computer Science Engineering", "Mechanical Engineering", "MBA"],
            "remarks_required": False,
            "search_keywords": ["courses offered", "programs offered", "academic programs", "B.Tech", "M.Tech", "MBA", "departments", "branches"]
        },
        {
            "field_name": "course_fees",
            "display_name": "Fees for Each Course",
            "category": "Academic Programs",
            "data_type": "object",
            "unit": "INR",
            "validation_rules": "key-value pairs: course_name -> annual_fee",
            "extraction_instruction": "Object mapping course names to annual tuition fees in INR. Include only tuition fees.",
            "example_value": {"Computer Science Engineering": 200000, "Mechanical Engineering": 180000},
            "remarks_required": False,
            "search_keywords": ["fee structure", "tuition fee", "course fees", "annual fee", "semester fee", "fee details", "fee per year"]
        },
        {
            "field_name": "total_graduate_students_2025",
            "display_name": "Total Graduate Students (2025)",
            "category": "Student Demographics",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer",
            "extraction_instruction": "Total number of graduating students across all programs for academic year 2024-25.",
            "example_value": 1200,
            "remarks_required": False,
            "search_keywords": ["graduating batch 2025", "final year students", "outgoing batch", "students graduated", "batch size 2025"]
        },
        {
            "field_name": "placed_students_count",
            "display_name": "Placed Students Count",
            "category": "Placements",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer <= total_graduate_students",
            "extraction_instruction": "Number of graduating students who received job offers through campus placements.",
            "example_value": 950,
            "remarks_required": False,
            "search_keywords": ["students placed", "placement statistics", "placement record", "campus placement", "students recruited", "placement percentage"]
        },
        {
            "field_name": "max_compensation_last_season",
            "display_name": "Maximum Compensation (Last Placement Season)",
            "category": "Placements",
            "data_type": "float",
            "unit": "INR per annum",
            "validation_rules": "positive number",
            "extraction_instruction": "Highest annual compensation offered to any student in last placement season.",
            "example_value": 4200000.00,
            "remarks_required": False,
            "search_keywords": ["highest package", "maximum salary", "top CTC", "highest CTC", "best package", "maximum compensation", "highest offer"]
        },
        {
            "field_name": "median_compensation_last_batch",
            "display_name": "Median Compensation (Last Batch)",
            "category": "Placements",
            "data_type": "float",
            "unit": "INR per annum",
            "validation_rules": "positive number",
            "extraction_instruction": "Median annual compensation offered to placed students from last graduating batch.",
            "example_value": 850000.00,
            "remarks_required": False,
            "search_keywords": ["median salary", "median package", "median CTC", "average package", "average salary", "mean compensation"]
        },
        {
            "field_name": "students_higher_education",
            "display_name": "Students Pursuing Higher Education",
            "category": "Student Outcomes",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer",
            "extraction_instruction": "Number of graduating students who enrolled in higher education (Masters/PhD) after graduation.",
            "example_value": 150,
            "remarks_required": False,
            "search_keywords": ["higher studies", "pursuing masters", "MS abroad", "PhD admission", "higher education", "postgraduate studies"]
        },
        {
            "field_name": "ip_patents_last_year",
            "display_name": "IP Patents Granted/Licensed (Latest Year)",
            "category": "Research & Innovation",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer or 0",
            "extraction_instruction": "Number of patents granted or licensed to the institution in the latest academic year.",
            "example_value": 12,
            "remarks_required": False,
            "search_keywords": ["patents granted", "patents filed", "intellectual property", "IPR", "patent publications", "innovations patented"]
        },
        {
            "field_name": "entrance_exam_name",
            "display_name": "Entrance Exam Name",
            "category": "Admissions",
            "data_type": "string",
            "unit": "exam name",
            "validation_rules": "string value",
            "extraction_instruction": "Primary entrance examination name for undergraduate admissions.",
            "example_value": "JEE Main",
            "remarks_required": False,
            "search_keywords": ["admission through", "entrance exam", "JEE", "NEET", "admission test", "eligibility criteria", "selection process"]
        },
        {
            "field_name": "entrance_exam_cutoff",
            "display_name": "Entrance Exam Cutoff by Program",
            "category": "Admissions",
            "data_type": "object",
            "unit": "percentile/score",
            "validation_rules": "key-value pairs: course_name -> cutoff_value",
            "extraction_instruction": "Object mapping course names to entrance exam cutoff scores/percentiles for last admission cycle.",
            "example_value": {"Computer Science Engineering": 98.5, "Mechanical Engineering": 92.3},
            "remarks_required": False,
            "search_keywords": ["cutoff marks", "cutoff percentile", "closing rank", "JEE cutoff", "admission cutoff", "minimum marks required"]
        },
        {
            "field_name": "total_students_enrolled",
            "display_name": "Total Students Enrolled",
            "category": "Student Demographics",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer",
            "extraction_instruction": "Total student enrollment across all programs and academic years.",
            "example_value": 5000,
            "remarks_required": False,
            "search_keywords": ["total students", "student strength", "student population", "enrollment", "total intake", "student count"]
        },
        {
            "field_name": "female_students_enrolled",
            "display_name": "Female Students Enrolled",
            "category": "Student Demographics",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer <= total_students_enrolled",
            "extraction_instruction": "Count of female students currently enrolled across all programs.",
            "example_value": 2200,
            "remarks_required": False,
            "search_keywords": ["female students", "girl students", "women students", "gender ratio", "female enrollment", "women in engineering"]
        },
        {
            "field_name": "total_faculty",
            "display_name": "Total Faculty",
            "category": "Faculty",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer",
            "extraction_instruction": "Total number of full-time faculty members.",
            "example_value": 300,
            "remarks_required": False,
            "search_keywords": ["total faculty", "faculty members", "teaching staff", "professors", "faculty strength", "academic staff"]
        },
        {
            "field_name": "phd_faculty",
            "display_name": "PhD Faculty",
            "category": "Faculty",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer <= total_faculty",
            "extraction_instruction": "Number of faculty members with PhD qualifications.",
            "example_value": 250,
            "remarks_required": False,
            "search_keywords": ["PhD faculty", "doctorate faculty", "faculty with PhD", "PhD qualified", "faculty qualifications"]
        },
        {
            "field_name": "avg_teaching_experience",
            "display_name": "Average Teaching Experience of Faculty",
            "category": "Faculty",
            "data_type": "float",
            "unit": "years",
            "validation_rules": "positive number",
            "extraction_instruction": "Average years of teaching experience across all faculty members.",
            "example_value": 12.5,
            "remarks_required": False,
            "search_keywords": ["teaching experience", "faculty experience", "years of experience", "experienced faculty", "faculty profile"]
        },
        {
            "field_name": "sports_infrastructure",
            "display_name": "Sports Infrastructure & Achievements",
            "category": "Campus Facilities",
            "data_type": "object",
            "unit": "description",
            "validation_rules": "object with facilities and achievements",
            "extraction_instruction": "Object containing sports facilities list and notable achievements. Format: {\"facilities\": [], \"achievements\": []}",
            "example_value": {"facilities": ["Cricket Ground", "Swimming Pool"], "achievements": ["University Champions 2024"]},
            "remarks_required": False,
            "search_keywords": ["sports facilities", "playground", "gymnasium", "sports complex", "athletics", "sports achievements", "stadium"]
        },
        {
            "field_name": "active_clubs_list",
            "display_name": "List of Active Clubs",
            "category": "Student Life",
            "data_type": "array",
            "unit": "names",
            "validation_rules": "array of strings",
            "extraction_instruction": "Array of names of currently active student clubs and societies.",
            "example_value": ["Coding Club", "Drama Society", "Music Club"],
            "remarks_required": False,
            "search_keywords": ["student clubs", "clubs and societies", "student activities", "cultural clubs", "technical clubs", "student organizations"]
        },
        {
            "field_name": "nirf_ranking_band",
            "display_name": "NIRF Ranking Band",
            "category": "Accreditations & Rankings",
            "data_type": "string",
            "unit": "rank band",
            "validation_rules": "string from predefined bands",
            "extraction_instruction": "NIRF ranking band (e.g., '1-50', '51-100', '101-150', '151-200', '201+', 'Not Ranked').",
            "example_value": "51-100",
            "remarks_required": False,
            "search_keywords": ["NIRF ranking", "NIRF 2024", "national ranking", "NIRF rank", "engineering ranking", "MHRD ranking"]
        },
        {
            "field_name": "institutional_status",
            "display_name": "Institutional Status",
            "category": "Accreditations & Rankings",
            "data_type": "string",
            "unit": "status type",
            "validation_rules": "one of: 'Autonomous', 'Deemed University', 'Private University', 'Affiliated College'",
            "extraction_instruction": "Institutional affiliation/status as per latest UGC/AICTE recognition.",
            "example_value": "Autonomous",
            "remarks_required": False,
            "search_keywords": ["autonomous status", "deemed university", "affiliated to", "university status", "NAAC accreditation", "UGC recognized"]
        },
        {
            "field_name": "phd_students_enrolled",
            "display_name": "PhD Students Enrolled",
            "category": "Student Demographics",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer or 0",
            "extraction_instruction": "Total number of students currently enrolled in PhD programs.",
            "example_value": 85,
            "remarks_required": False,
            "search_keywords": ["PhD students", "doctoral students", "research scholars", "PhD program", "PhD enrollment", "research students"]
        }
    ],
    "metadata": {
        "version": "2.0",
        "total_kpis": 25,
        "categories": [
            "Academic Infrastructure", "Campus Facilities", "Technology Infrastructure",
            "Academic Programs", "Student Demographics", "Placements", "Student Outcomes",
            "Research & Innovation", "Admissions", "Faculty", "Student Life", "Accreditations & Rankings"
        ]
    }
}

# Create the main app
app = FastAPI(title="College KPI Auditor API")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ Models ============

class AuditRequest(BaseModel):
    college_name: str

class AuditResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    college_name: str
    status: str = "pending"
    progress: int = 0
    progress_message: str = ""
    results: List[Dict[str, Any]] = []
    summary: Dict[str, Any] = {}
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None

# ============ Official Source Validator ============

class OfficialSourceValidator:
    """Validates and filters results to only include official sources"""
    
    # Official source patterns - ONLY these are allowed
    OFFICIAL_PATTERNS = {
        'nirf': ['nirfindia.org', 'nirf.org'],
        'naac': ['naac.gov.in', 'assessmentonline.naac.gov.in'],
        'wikipedia': ['wikipedia.org', 'en.wikipedia.org'],
        'government': ['.gov.in', '.nic.in', '.ac.in', '.edu.in'],
        'aicte': ['aicte-india.org', 'facilities.aicte-india.org'],
        'ugc': ['ugc.ac.in', 'ugc.gov.in'],
    }
    
    # Blocked sources - these should NEVER be used
    BLOCKED_SOURCES = [
        'shiksha.com', 'collegedunia.com', 'collegedekho.com', 'careers360.com',
        'getmyuni.com', 'jagranjosh.com', 'examresults.net', 'indiatoday.in',
        'hindustantimes.com', 'timesofindia.indiatimes.com', 'ndtv.com',
        'news18.com', 'thehindu.com', 'quora.com', 'reddit.com', 'youtube.com',
        'facebook.com', 'instagram.com', 'twitter.com', 'linkedin.com'
    ]
    
    @classmethod
    def is_official_source(cls, url: str, college_domain: str = None) -> bool:
        """Check if URL is from an official/trusted source"""
        if not url or url == "N/A":
            return False
        
        url_lower = url.lower()
        
        # Check if blocked
        for blocked in cls.BLOCKED_SOURCES:
            if blocked in url_lower:
                return False
        
        # Check official patterns
        for source_type, patterns in cls.OFFICIAL_PATTERNS.items():
            for pattern in patterns:
                if pattern in url_lower:
                    return True
        
        # Check if it's the college's official website
        if college_domain and college_domain.lower() in url_lower:
            return True
        
        # Check for common official patterns
        if any(ext in url_lower for ext in ['.ac.in', '.edu.in', '.edu', '.gov']):
            return True
        
        return False
    
    @classmethod
    def get_source_priority(cls, url: str) -> int:
        """Get priority score for source (lower = higher priority)"""
        if not url or url == "N/A":
            return 999
        
        url_lower = url.lower()
        
        # Priority 1: NIRF (most reliable for placements, rankings)
        if 'nirf' in url_lower:
            return 1
        
        # Priority 2: Official college website
        if '.ac.in' in url_lower or '.edu.in' in url_lower:
            return 2
        
        # Priority 3: Wikipedia
        if 'wikipedia' in url_lower:
            return 3
        
        # Priority 4: NAAC
        if 'naac' in url_lower:
            return 4
        
        # Priority 5: Other government
        if '.gov.in' in url_lower or '.nic.in' in url_lower:
            return 5
        
        return 100
    
    @classmethod
    def extract_college_domain(cls, college_name: str) -> str:
        """Extract likely domain pattern from college name"""
        # Common patterns
        name_lower = college_name.lower()
        
        if 'iit' in name_lower:
            # Extract location
            parts = name_lower.split()
            for i, part in enumerate(parts):
                if 'iit' in part and i + 1 < len(parts):
                    return f"iit{parts[i+1]}"
        
        return ""


# ============ KPI Auditor Class ============

class CollegeKPIAuditor:
    def __init__(self):
        self.kpis_data = self._load_kpis_from_schema()
        self.serper_api_key = os.environ.get("SERPER_API_KEY")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY")
        self.validator = OfficialSourceValidator()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })
        
    def _load_kpis_from_schema(self) -> List[Dict]:
        """Load KPIs from KPI_SCHEMA constant"""
        kpis = []
        for kpi_item in KPI_SCHEMA["college_kpis"]:
            kpis.append({
                'name': kpi_item['display_name'],
                'field_name': kpi_item['field_name'],
                'category': kpi_item['category'],
                'data_type': kpi_item['data_type'],
                'unit': kpi_item['unit'],
                'validation_rules': kpi_item['validation_rules'],
                'extraction_instruction': kpi_item['extraction_instruction'],
                'remarks_required': kpi_item.get('remarks_required', False),
                'search_keywords': kpi_item.get('search_keywords', []),
            })
        logger.info(f"Loaded {len(kpis)} KPIs from schema")
        return kpis

    def search_for_kpi(self, college_name: str, kpi: Dict, abbreviation: str = "") -> Dict[str, Any]:
        """Search specifically for a single KPI using its keywords"""
        kpi_data = {
            "kpi_name": kpi['name'],
            "search_results": [],
            "fetched_content": []
        }
        
        keywords = kpi.get('search_keywords', [])
        if not keywords:
            return kpi_data
        
        # Build targeted search queries for this KPI
        queries = []
        
        # Use first 2-3 keywords for variety
        for keyword in keywords[:3]:
            queries.append(f'"{college_name}" {keyword}')
            if abbreviation:
                queries.append(f'"{abbreviation}" {keyword}')
        
        # Add site-specific searches for official sources
        primary_keyword = keywords[0] if keywords else kpi['name']
        queries.extend([
            f'site:.ac.in OR site:.edu.in "{college_name}" {primary_keyword}',
            f'site:nirfindia.org "{college_name}" {primary_keyword}',
        ])
        
        seen_urls = set()
        
        for query in queries[:5]:  # Limit to 5 queries per KPI
            result = self.search_official_sources(query, num_results=5)
            if result.get("official_results"):
                for r in result["official_results"]:
                    url = r.get('url', '')
                    if url not in seen_urls:
                        seen_urls.add(url)
                        kpi_data["search_results"].append(r)
            time.sleep(0.15)  # Rate limiting
        
        # Fetch content from top 2 official URLs
        urls_to_fetch = [r['url'] for r in kpi_data["search_results"][:2] 
                         if not r['url'].lower().endswith('.pdf')]
        
        for url in urls_to_fetch:
            content = self.fetch_webpage_content(url, max_length=8000)
            if content.get('success'):
                kpi_data["fetched_content"].append(content)
        
        return kpi_data

    def fetch_webpage_content(self, url: str, max_length: int = 15000) -> Dict[str, Any]:
        """Fetch and extract text content from a webpage"""
        try:
            # Skip PDFs and non-HTML
            if url.lower().endswith('.pdf'):
                return {"url": url, "content": "", "error": "PDF files not supported", "success": False}
            
            response = self.session.get(url, timeout=15, allow_redirects=True)
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Remove script, style elements
            for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
                script.decompose()
            
            # Get text
            text = soup.get_text(separator=' ', strip=True)
            
            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text)
            
            # Truncate if too long
            if len(text) > max_length:
                text = text[:max_length] + "..."
            
            return {
                "url": url,
                "title": soup.title.string if soup.title else "",
                "content": text,
                "success": True
            }
            
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return {"url": url, "content": "", "error": str(e), "success": False}

    def fetch_wikipedia_content(self, college_name: str) -> Dict[str, Any]:
        """Fetch Wikipedia content using Wikipedia API"""
        try:
            # Clean and encode college name for Wikipedia search
            search_term = college_name.replace(" ", "_")
            
            # First, search for the page
            search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={quote(college_name)}&format=json"
            response = self.session.get(search_url, timeout=10)
            search_results = response.json()
            
            if not search_results.get('query', {}).get('search'):
                return {"url": "", "content": "", "success": False, "error": "No Wikipedia page found"}
            
            # Get the first result's title
            page_title = search_results['query']['search'][0]['title']
            
            # Now get the page content
            content_url = f"https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro=false&explaintext=true&titles={quote(page_title)}&format=json"
            response = self.session.get(content_url, timeout=10)
            content_data = response.json()
            
            pages = content_data.get('query', {}).get('pages', {})
            for page_id, page_data in pages.items():
                if page_id != '-1':
                    content = page_data.get('extract', '')
                    wiki_url = f"https://en.wikipedia.org/wiki/{quote(page_title.replace(' ', '_'))}"
                    return {
                        "url": wiki_url,
                        "title": page_data.get('title', ''),
                        "content": content[:20000] if len(content) > 20000 else content,
                        "success": True
                    }
            
            return {"url": "", "content": "", "success": False, "error": "Page content not found"}
            
        except Exception as e:
            logger.warning(f"Wikipedia fetch failed: {e}")
            return {"url": "", "content": "", "success": False, "error": str(e)}

    def search_official_sources(self, query: str, num_results: int = 10) -> Dict[str, Any]:
        """Perform web search with strict filtering for official sources only"""
        if not self.serper_api_key:
            return {"error": "SERPER_API_KEY not set", "results": []}
        
        url = "https://google.serper.dev/search"
        payload = {
            "q": query,
            "num": num_results,
            "gl": "in",
            "hl": "en"
        }
        headers = {
            'X-API-KEY': self.serper_api_key,
            'Content-Type': 'application/json'
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            results = response.json()
            
            filtered_results = []
            
            # Process organic results - filter for official sources only
            for r in results.get("organic", []):
                link = r.get('link', '')
                
                # Skip non-official sources
                is_blocked = any(blocked in link.lower() for blocked in self.validator.BLOCKED_SOURCES)
                if is_blocked:
                    continue
                
                # Check if official
                is_official = self.validator.is_official_source(link)
                
                if is_official:
                    filtered_results.append({
                        'title': r.get('title', ''),
                        'url': link,
                        'snippet': r.get('snippet', ''),
                        'priority': self.validator.get_source_priority(link),
                        'source_type': self._identify_source_type(link)
                    })
            
            # Sort by priority (lower = better)
            filtered_results.sort(key=lambda x: x['priority'])
            
            # Process Knowledge Graph if available
            knowledge_graph = None
            if "knowledgeGraph" in results:
                kg = results["knowledgeGraph"]
                knowledge_graph = {k: v for k, v in kg.items() if isinstance(v, (str, int, float, list))}
            
            return {
                "query": query,
                "official_results": filtered_results,
                "knowledge_graph": knowledge_graph,
                "total_found": len(filtered_results)
            }
            
        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            return {"error": str(e), "results": []}
    
    def _identify_source_type(self, url: str) -> str:
        """Identify the type of official source"""
        url_lower = url.lower()
        
        if 'nirf' in url_lower:
            return "NIRF"
        elif 'naac' in url_lower:
            return "NAAC"
        elif 'wikipedia' in url_lower:
            return "Wikipedia"
        elif '.ac.in' in url_lower or '.edu.in' in url_lower:
            return "Official College Website"
        elif 'aicte' in url_lower:
            return "AICTE"
        elif 'ugc' in url_lower:
            return "UGC"
        elif '.gov.in' in url_lower:
            return "Government"
        
        return "Other Official"

    async def gather_official_data(self, college_name: str, progress_callback=None) -> Dict[str, Any]:
        """
        Gather data ONLY from official sources with ACTUAL page content:
        1. Wikipedia (full article content)
        2. Official College Website (fetched content)
        3. NIRF Search Results
        4. NAAC Documents
        """
        
        clean_name = college_name.strip()
        all_data = {
            "official_website": [],
            "official_website_content": [],
            "nirf": [],
            "wikipedia": [],
            "wikipedia_content": "",
            "naac": [],
            "combined_text": "",
            "fetched_urls": set()
        }
        
        # Generate college abbreviation for better searches
        abbreviation = self._get_college_abbreviation(clean_name)
        search_names = [clean_name]
        if abbreviation:
            search_names.append(abbreviation)
        
        combined_text_parts = []
        
        # ============ PRIORITY 1: WIKIPEDIA (Full Content) ============
        if progress_callback:
            await progress_callback("Fetching Wikipedia content...", 5)
        
        wiki_data = self.fetch_wikipedia_content(clean_name)
        if wiki_data.get("success"):
            all_data["wikipedia_content"] = wiki_data["content"]
            all_data["wikipedia"].append({
                "title": wiki_data.get("title", clean_name),
                "url": wiki_data.get("url", ""),
                "snippet": wiki_data.get("content", "")[:500],
                "priority": 1,
                "source_type": "Wikipedia"
            })
            combined_text_parts.append(f"[WIKIPEDIA FULL ARTICLE]\nURL: {wiki_data.get('url', '')}\n{wiki_data['content']}\n")
            logger.info(f"Fetched Wikipedia content: {len(wiki_data['content'])} chars")
        elif abbreviation:
            # Try with abbreviation
            wiki_data = self.fetch_wikipedia_content(abbreviation)
            if wiki_data.get("success"):
                all_data["wikipedia_content"] = wiki_data["content"]
                all_data["wikipedia"].append({
                    "title": wiki_data.get("title", abbreviation),
                    "url": wiki_data.get("url", ""),
                    "snippet": wiki_data.get("content", "")[:500],
                    "priority": 1,
                    "source_type": "Wikipedia"
                })
                combined_text_parts.append(f"[WIKIPEDIA FULL ARTICLE]\nURL: {wiki_data.get('url', '')}\n{wiki_data['content']}\n")
        
        # ============ PRIORITY 2: OFFICIAL COLLEGE WEBSITE ============
        if progress_callback:
            await progress_callback("Searching Official College Website...", 15)
        
        # Search for official website pages with specific KPI-related content
        official_queries = [
            f'site:.ac.in OR site:.edu.in "{clean_name}" official',
            f'"{clean_name}" official website placements 2024 2025',
            f'"{clean_name}" official faculty members PhD',
            f'"{clean_name}" official admission fee structure',
            f'"{clean_name}" official infrastructure facilities',
            f'"{clean_name}" official hostel accommodation',
            f'"{clean_name}" official courses programs offered',
        ]
        
        if abbreviation:
            official_queries.extend([
                f'site:.ac.in OR site:.edu.in "{abbreviation}" official',
                f'"{abbreviation}" placements 2024 highest package',
            ])
        
        official_urls_to_fetch = set()
        
        for idx, query in enumerate(official_queries):
            if progress_callback:
                await progress_callback(f"Searching Official Website ({idx+1}/{len(official_queries)})...", 15 + int((idx / len(official_queries)) * 20))
            
            result = self.search_official_sources(query, num_results=5)
            if result.get("official_results"):
                for r in result["official_results"]:
                    if r['source_type'] == "Official College Website":
                        all_data["official_website"].append(r)
                        combined_text_parts.append(f"[OFFICIAL WEBSITE SEARCH]\nTitle: {r['title']}\nURL: {r['url']}\nSnippet: {r['snippet']}\n")
                        # Collect URLs for content fetching
                        if r['url'] and not r['url'].lower().endswith('.pdf'):
                            official_urls_to_fetch.add(r['url'])
            
            await asyncio.sleep(0.2)
        
        # Fetch actual content from top official website pages
        if progress_callback:
            await progress_callback("Fetching official website content...", 40)
        
        urls_to_fetch = list(official_urls_to_fetch)[:5]  # Limit to top 5 URLs
        for idx, url in enumerate(urls_to_fetch):
            if url in all_data["fetched_urls"]:
                continue
            try:
                page_content = self.fetch_webpage_content(url, max_length=12000)
                if page_content.get("success") and page_content.get("content"):
                    all_data["official_website_content"].append(page_content)
                    all_data["fetched_urls"].add(url)
                    combined_text_parts.append(f"[OFFICIAL WEBSITE PAGE CONTENT]\nURL: {url}\nTitle: {page_content.get('title', '')}\nContent: {page_content['content']}\n")
                    logger.info(f"Fetched official page: {url} ({len(page_content['content'])} chars)")
            except Exception as e:
                logger.warning(f"Failed to fetch {url}: {e}")
            await asyncio.sleep(0.3)
        
        # ============ PRIORITY 3: NIRF DATA ============
        if progress_callback:
            await progress_callback("Searching NIRF Documents...", 55)
        
        nirf_queries = [
            f'site:nirfindia.org "{clean_name}"',
            f'"{clean_name}" NIRF 2024 ranking',
            f'"{clean_name}" NIRF placement statistics median salary',
            f'"{clean_name}" NIRF faculty PhD students',
        ]
        
        if abbreviation:
            nirf_queries.extend([
                f'site:nirfindia.org "{abbreviation}"',
                f'"{abbreviation}" NIRF 2024 engineering ranking',
            ])
        
        for idx, query in enumerate(nirf_queries):
            if progress_callback:
                await progress_callback(f"Searching NIRF ({idx+1}/{len(nirf_queries)})...", 55 + int((idx / len(nirf_queries)) * 15))
            
            result = self.search_official_sources(query, num_results=8)
            if result.get("official_results"):
                for r in result["official_results"]:
                    if r['source_type'] == "NIRF" or 'nirf' in r['url'].lower():
                        all_data["nirf"].append(r)
                        combined_text_parts.append(f"[NIRF]\nTitle: {r['title']}\nURL: {r['url']}\nData: {r['snippet']}\n")
            
            await asyncio.sleep(0.2)
        
        # ============ PRIORITY 4: NAAC DOCUMENTS ============
        if progress_callback:
            await progress_callback("Searching NAAC Documents...", 75)
        
        naac_queries = [
            f'site:naac.gov.in "{clean_name}"',
            f'"{clean_name}" NAAC accreditation grade SSR',
        ]
        
        for idx, query in enumerate(naac_queries):
            if progress_callback:
                await progress_callback(f"Searching NAAC ({idx+1}/{len(naac_queries)})...", 75 + int((idx / len(naac_queries)) * 10))
            
            result = self.search_official_sources(query, num_results=5)
            if result.get("official_results"):
                for r in result["official_results"]:
                    if 'naac' in r['url'].lower():
                        all_data["naac"].append(r)
                        combined_text_parts.append(f"[NAAC]\nTitle: {r['title']}\nURL: {r['url']}\nData: {r['snippet']}\n")
            
            await asyncio.sleep(0.2)
        
        # ============ PRIORITY 5: PER-KPI TARGETED SEARCH ============
        if progress_callback:
            await progress_callback("Searching for specific KPI data...", 85)
        
        all_data["kpi_specific_data"] = {}
        
        # Search for each KPI individually with its specific keywords
        for idx, kpi in enumerate(self.kpis_data):
            if progress_callback and idx % 5 == 0:
                progress = 85 + int((idx / len(self.kpis_data)) * 10)
                await progress_callback(f"Searching KPI {idx+1}/{len(self.kpis_data)}: {kpi['name'][:30]}...", min(progress, 95))
            
            kpi_search_data = self.search_for_kpi(clean_name, kpi, abbreviation)
            all_data["kpi_specific_data"][kpi['name']] = kpi_search_data
            
            # Add to combined text
            if kpi_search_data["search_results"]:
                combined_text_parts.append(f"\n[KPI-SPECIFIC: {kpi['name']}]")
                for r in kpi_search_data["search_results"][:3]:
                    combined_text_parts.append(f"  Source: {r['url']}\n  Snippet: {r['snippet']}")
            
            if kpi_search_data["fetched_content"]:
                for content in kpi_search_data["fetched_content"]:
                    combined_text_parts.append(f"  [Fetched Page for {kpi['name']}]\n  URL: {content['url']}\n  Content: {content['content'][:3000]}")
            
            await asyncio.sleep(0.1)
        
        all_data["combined_text"] = "\n\n".join(combined_text_parts)
        
        # Convert set to list for JSON serialization
        all_data["fetched_urls"] = list(all_data["fetched_urls"])
        
        if progress_callback:
            total_sources = len(all_data["official_website"]) + len(all_data["nirf"]) + len(all_data["wikipedia"]) + len(all_data["naac"])
            content_pages = len(all_data["official_website_content"])
            wiki_len = len(all_data.get("wikipedia_content", ""))
            kpi_sources = sum(len(v.get("search_results", [])) for v in all_data.get("kpi_specific_data", {}).values())
            await progress_callback(f"Data collection complete. {total_sources} general sources, {kpi_sources} KPI-specific sources, {content_pages} pages fetched", 98)
        
        return all_data

    def _get_college_abbreviation(self, college_name: str) -> str:
        """Get common abbreviation for college name"""
        name_lower = college_name.lower()
        
        if "indian institute of technology" in name_lower:
            parts = college_name.split()
            for i, part in enumerate(parts):
                if part.lower() == "technology" and i + 1 < len(parts):
                    location = parts[i + 1]
                    return f"IIT {location}"
        elif "national institute of technology" in name_lower:
            parts = college_name.split()
            for i, part in enumerate(parts):
                if part.lower() == "technology" and i + 1 < len(parts):
                    location = parts[i + 1]
                    return f"NIT {location}"
        elif "indian institute of information technology" in name_lower:
            parts = college_name.split()
            for i, part in enumerate(parts):
                if part.lower() == "technology" and i + 1 < len(parts):
                    location = parts[i + 1]
                    return f"IIIT {location}"
        elif "indian institute of management" in name_lower:
            parts = college_name.split()
            for i, part in enumerate(parts):
                if part.lower() == "management" and i + 1 < len(parts):
                    location = parts[i + 1]
                    return f"IIM {location}"
        elif "birla institute of technology" in name_lower:
            if "science" in name_lower:
                return "BITS Pilani"
            else:
                return "BIT Mesra"
        elif "vellore institute of technology" in name_lower or "vit" in name_lower:
            return "VIT"
        elif "manipal institute of technology" in name_lower:
            return "MIT Manipal"
        elif "srm institute" in name_lower or "srm university" in name_lower:
            return "SRM"
        elif "amity university" in name_lower:
            return "Amity"
        elif "lovely professional university" in name_lower:
            return "LPU"
        elif "chandigarh university" in name_lower:
            return "CU Chandigarh"
        elif "delhi technological university" in name_lower:
            return "DTU"
        elif "netaji subhas" in name_lower and "technology" in name_lower:
            return "NSUT"
        elif "pec" in name_lower or "punjab engineering college" in name_lower:
            return "PEC Chandigarh"
        elif "thapar" in name_lower:
            return "Thapar University"
        elif "anna university" in name_lower:
            return "Anna University"
        elif "jadavpur university" in name_lower:
            return "Jadavpur University"
        
        return ""

    async def extract_kpi_with_strict_sources(self, college_name: str, kpis_batch: List[Dict], 
                                               search_data: Dict[str, Any], model) -> List[Dict]:
        """Extract KPI values using Gemini with STRICT official source validation and per-KPI data"""
        
        # Build structured data from official sources - prioritize FULL content
        source_sections = []
        
        # PRIORITY 1: Wikipedia FULL article content (most reliable for general info)
        if search_data.get("wikipedia_content"):
            wiki_url = search_data["wikipedia"][0]["url"] if search_data.get("wikipedia") else "https://en.wikipedia.org"
            source_sections.append("=== WIKIPEDIA FULL ARTICLE (HIGH PRIORITY - VERIFIED CONTENT) ===")
            source_sections.append(f"Source URL: {wiki_url}")
            source_sections.append(f"Content:\n{search_data['wikipedia_content'][:20000]}")
            source_sections.append("")
        
        # PRIORITY 2: Fetched Official Website Content
        if search_data.get("official_website_content"):
            source_sections.append("=== OFFICIAL COLLEGE WEBSITE - FETCHED PAGES (HIGH PRIORITY) ===")
            for item in search_data["official_website_content"][:5]:
                source_sections.append(f"Page URL: {item['url']}")
                source_sections.append(f"Page Title: {item.get('title', '')}")
                source_sections.append(f"Page Content:\n{item['content'][:8000]}")
                source_sections.append("")
        
        # PRIORITY 3: KPI-SPECIFIC SEARCH DATA (NEW - Very Important!)
        kpi_specific_data = search_data.get("kpi_specific_data", {})
        for kpi in kpis_batch:
            kpi_name = kpi['name']
            if kpi_name in kpi_specific_data:
                kpi_data = kpi_specific_data[kpi_name]
                if kpi_data.get("search_results") or kpi_data.get("fetched_content"):
                    source_sections.append(f"=== KPI-SPECIFIC DATA FOR: {kpi_name} ===")
                    
                    # Add fetched content first (higher priority)
                    for content in kpi_data.get("fetched_content", [])[:2]:
                        source_sections.append(f"[Fetched Page] URL: {content['url']}")
                        source_sections.append(f"Content: {content['content'][:5000]}")
                        source_sections.append("")
                    
                    # Add search snippets
                    for result in kpi_data.get("search_results", [])[:4]:
                        source_sections.append(f"[Search Result] URL: {result['url']}")
                        source_sections.append(f"Snippet: {result['snippet']}")
                        source_sections.append("")
        
        # PRIORITY 4: Official Website Search Results
        if search_data.get("official_website"):
            source_sections.append("=== OFFICIAL COLLEGE WEBSITE - SEARCH SNIPPETS ===")
            for item in search_data["official_website"][:10]:
                source_sections.append(f"Title: {item['title']}")
                source_sections.append(f"URL: {item['url']}")
                source_sections.append(f"Snippet: {item['snippet']}")
                source_sections.append("")
        
        # PRIORITY 5: NIRF Data
        if search_data.get("nirf"):
            source_sections.append("=== NIRF DOCUMENTS (OFFICIAL RANKING DATA) ===")
            for item in search_data["nirf"][:8]:
                source_sections.append(f"Title: {item['title']}")
                source_sections.append(f"URL: {item['url']}")
                source_sections.append(f"Data: {item['snippet']}")
                source_sections.append("")
        
        # PRIORITY 6: Wikipedia search snippets (if no full content)
        if search_data.get("wikipedia") and not search_data.get("wikipedia_content"):
            source_sections.append("=== WIKIPEDIA SEARCH RESULTS ===")
            for item in search_data["wikipedia"][:5]:
                source_sections.append(f"Title: {item['title']}")
                source_sections.append(f"URL: {item['url']}")
                source_sections.append(f"Content: {item['snippet']}")
                source_sections.append("")
        
        if search_data.get("naac"):
            source_sections.append("=== NAAC DOCUMENTS (ACCREDITATION DATA) ===")
            for item in search_data["naac"][:5]:
                source_sections.append(f"Title: {item['title']}")
                source_sections.append(f"URL: {item['url']}")
                source_sections.append(f"Content: {item['snippet']}")
                source_sections.append("")
        
        search_content = "\n".join(source_sections)
        
        # Limit content size for API
        if len(search_content) > 100000:
            search_content = search_content[:100000] + "\n[Content truncated for processing]"
        
        # Build KPI extraction instructions with search keywords hint
        kpi_details = []
        for i, kpi in enumerate(kpis_batch, 1):
            detail = f"{i}. KPI: {kpi['name']}"
            detail += f"\n   Category: {kpi['category']}"
            detail += f"\n   Data Type: {kpi['data_type']} ({kpi['unit']})"
            detail += f"\n   Extraction Rule: {kpi['extraction_instruction']}"
            if kpi.get('search_keywords'):
                detail += f"\n   Look for keywords: {', '.join(kpi['search_keywords'][:4])}"
            kpi_details.append(detail)
        
        kpi_list_str = "\n".join(kpi_details)
        
        prompt = f"""You are a data extraction expert specializing in Indian educational institutions. Extract PRECISE data for the following college KPIs.

COLLEGE NAME: "{college_name}"

IMPORTANT: For each KPI, there is dedicated "KPI-SPECIFIC DATA" section in the source data below. Use that section primarily to find the value.

EXTRACTION RULES - FOLLOW STRICTLY:
1. Extract data ONLY from the official sources provided below
2. Use EXACT values as mentioned in the source text - do not approximate or estimate
3. Include the EXACT source URL where you found the data
4. If data is NOT explicitly found in the sources, return "Data Not Found"
5. DO NOT invent, estimate, or hallucinate any values
6. For numbers: extract the exact number mentioned (e.g., "85%" stays as "85%", "₹12 LPA" stays as "12 LPA")
7. For boolean KPIs: only set true if explicitly confirmed, false if explicitly denied, null if not mentioned
8. Confidence levels:
   - "high": Data from Wikipedia full article or official college website fetched content
   - "medium": Data from search snippets of official sources or NIRF
   - "low": Data uncertain or from NAAC/limited sources

=== OFFICIAL SOURCE DATA (READ CAREFULLY) ===
{search_content}
=== END OF SOURCE DATA ===

=== KPIs TO EXTRACT ({len(kpis_batch)} items) ===
{kpi_list_str}
=== END KPIs ===

OUTPUT FORMAT - Return ONLY valid JSON array, no markdown code blocks:
[
  {{
    "kpi_name": "exact KPI name from the list above",
    "category": "category from the list above",
    "value": "extracted value (use exact format from source) OR 'Data Not Found'",
    "evidence_quote": "exact phrase/sentence from source that contains this data OR 'Not found in official sources'",
    "source_url": "the URL from the source data where this was found OR 'N/A'",
    "source_type": "Wikipedia/Official College Website/NIRF/NAAC",
    "confidence": "high/medium/low"
  }}
]

Now extract all {len(kpis_batch)} KPIs based on the source data above:"""

        try:
            response = model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.05,  # Low for precision
                    "top_p": 0.95,
                    "max_output_tokens": 8192
                }
            )
            
            text = response.text.strip()
            
            # Clean markdown
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            results = json.loads(text.strip())
            
            # Validate sources - ensure only official sources are cited
            validated_results = []
            for r in results:
                source_url = r.get('source_url', 'N/A')
                
                # Validate the source is actually official
                if source_url != 'N/A' and not self.validator.is_official_source(source_url):
                    # Reject non-official source
                    r['source_url'] = 'N/A'
                    r['value'] = 'Data Not Found'
                    r['evidence_quote'] = 'Source not from official channels'
                    r['confidence'] = 'low'
                
                validated_results.append(r)
            
            # Fill missing KPIs
            found_kpis = {str(r.get('kpi_name', '')).lower().strip() for r in validated_results}
            for kpi in kpis_batch:
                if kpi['name'].lower().strip() not in found_kpis:
                    validated_results.append({
                        "kpi_name": kpi['name'],
                        "category": kpi['category'],
                        "value": "Data Not Found",
                        "evidence_quote": "Not found in official sources",
                        "source_url": "N/A",
                        "source_type": "N/A",
                        "confidence": "low"
                    })
            
            return validated_results
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            try:
                json_match = re.search(r'\[[\s\S]*\]', text)
                if json_match:
                    return json.loads(json_match.group())
            except:
                pass
            
            return [
                {
                    "kpi_name": kpi['name'],
                    "category": kpi['category'],
                    "value": "Data Not Found",
                    "evidence_quote": "Processing error",
                    "source_url": "N/A",
                    "source_type": "N/A",
                    "confidence": "low"
                }
                for kpi in kpis_batch
            ]
        except Exception as e:
            logger.error(f"Extraction error: {e}")
            return [
                {
                    "kpi_name": kpi['name'],
                    "category": kpi['category'],
                    "value": "Data Not Found",
                    "evidence_quote": str(e),
                    "source_url": "N/A",
                    "source_type": "N/A",
                    "confidence": "low"
                }
                for kpi in kpis_batch
            ]

    async def run_audit(self, college_name: str, progress_callback=None) -> List[Dict]:
        """Run the complete audit process with STRICT official source filtering"""
        
        if not self.gemini_api_key:
            return [{"kpi_name": "Error", "category": "Config", "value": "GEMINI_API_KEY not set", 
                    "evidence_quote": "", "source_url": "", "confidence": "low"}]
        
        if not self.serper_api_key:
            return [{"kpi_name": "Error", "category": "Config", "value": "SERPER_API_KEY not set", 
                    "evidence_quote": "", "source_url": "", "confidence": "low"}]
        
        genai.configure(api_key=self.gemini_api_key)
        model = genai.GenerativeModel('models/gemini-2.0-flash')
        
        # Step 1: Gather data from OFFICIAL sources only
        if progress_callback:
            await progress_callback("Starting audit - gathering from OFFICIAL sources only...", 2)
        
        search_data = await self.gather_official_data(college_name, progress_callback)
        
        total_sources = (len(search_data["official_website"]) + len(search_data["nirf"]) + 
                        len(search_data["wikipedia"]) + len(search_data["naac"]))
        
        if total_sources < 3:
            return [{"kpi_name": "Error", "category": "Search", 
                    "value": "Insufficient official sources found. Please verify college name.", 
                    "evidence_quote": f"Found only {total_sources} official sources",
                    "source_url": "", "confidence": "low"}]
        
        if progress_callback:
            await progress_callback(f"Found {total_sources} official sources. Extracting KPIs...", 90)
        
        # Step 2: Extract KPIs in batches
        all_results = []
        batch_size = 5
        total_kpis = len(self.kpis_data)
        
        for i in range(0, total_kpis, batch_size):
            batch = self.kpis_data[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total_kpis + batch_size - 1) // batch_size
            
            if progress_callback:
                progress = 90 + int(((i + batch_size) / total_kpis) * 9)
                await progress_callback(f"Extracting KPIs batch {batch_num}/{total_batches}...", min(progress, 99))
            
            batch_results = await self.extract_kpi_with_strict_sources(
                college_name, batch, search_data, model
            )
            all_results.extend(batch_results)
            
            await asyncio.sleep(0.5)
        
        if progress_callback:
            await progress_callback("Audit complete!", 100)
        
        return all_results


# Initialize auditor
auditor = CollegeKPIAuditor()

# ============ Background Task Processing ============

async def process_audit(audit_id: str, college_name: str):
    """Background task to process audit"""
    try:
        async def progress_callback(message: str, progress: int):
            if audit_id in audits_store:
                audits_store[audit_id]["progress"] = progress
                audits_store[audit_id]["progress_message"] = message
        
        results = await auditor.run_audit(college_name, progress_callback)
        
        # Generate summary
        total = len(results)
        found = sum(1 for r in results if str(r.get('value', '')).lower() not in 
                   ['data not found', 'error', 'processing error', 'not available', ''])
        high_conf = sum(1 for r in results if r.get('confidence') == 'high')
        medium_conf = sum(1 for r in results if r.get('confidence') == 'medium')
        
        # Group by source type
        sources = {}
        for r in results:
            src = r.get('source_type', 'N/A')
            if src not in sources:
                sources[src] = 0
            if str(r.get('value', '')).lower() not in ['data not found', 'error', '']:
                sources[src] += 1
        
        # Group by category
        categories = {}
        for r in results:
            cat = r.get('category', 'Other')
            if cat not in categories:
                categories[cat] = {'total': 0, 'found': 0}
            categories[cat]['total'] += 1
            if str(r.get('value', '')).lower() not in ['data not found', 'error', 'processing error', '']:
                categories[cat]['found'] += 1
        
        summary = {
            "total_kpis": total,
            "data_found": found,
            "data_not_found": total - found,
            "high_confidence": high_conf,
            "medium_confidence": medium_conf,
            "coverage_percentage": round((found / total) * 100, 1) if total > 0 else 0,
            "sources_breakdown": sources,
            "categories": categories
        }
        
        if audit_id in audits_store:
            audits_store[audit_id].update({
                "status": "completed",
                "progress": 100,
                "progress_message": "Audit complete!",
                "results": results,
                "summary": summary,
                "completed_at": datetime.now(timezone.utc).isoformat()
            })
        
    except Exception as e:
        logger.error(f"Audit processing error: {e}")
        if audit_id in audits_store:
            audits_store[audit_id].update({
                "status": "failed",
                "progress_message": f"Error: {str(e)}"
            })


# ============ API Routes ============

@api_router.get("/")
async def root():
    return {"message": "College KPI Auditor API", "status": "running", "version": "2.0"}

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

@api_router.get("/kpis")
async def get_kpis():
    """Get all available KPIs"""
    return {
        "total": len(auditor.kpis_data),
        "kpis": auditor.kpis_data
    }

@api_router.get("/sources")
async def get_allowed_sources():
    """Get list of allowed official sources"""
    return {
        "allowed_sources": {
            "priority_1": "Official College Website (.ac.in, .edu.in)",
            "priority_2": "NIRF (nirfindia.org)",
            "priority_3": "Wikipedia (wikipedia.org)",
            "priority_4": "NAAC (naac.gov.in)"
        },
        "blocked_sources": OfficialSourceValidator.BLOCKED_SOURCES[:10]
    }

@api_router.post("/audit/start")
async def start_audit(request: AuditRequest, background_tasks: BackgroundTasks):
    """Start a new college audit"""
    audit_id = str(uuid.uuid4())
    college_name = request.college_name.strip()
    
    if not college_name:
        raise HTTPException(status_code=400, detail="College name is required")
    
    audit_doc = {
        "id": audit_id,
        "college_name": college_name,
        "status": "processing",
        "progress": 0,
        "progress_message": "Starting audit...",
        "results": [],
        "summary": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None
    }
    
    audits_store[audit_id] = audit_doc
    background_tasks.add_task(process_audit, audit_id, college_name)
    
    return {"audit_id": audit_id, "status": "processing", "message": f"Audit started for {college_name}"}

@api_router.get("/audit/{audit_id}")
async def get_audit_status(audit_id: str):
    """Get audit status and results"""
    audit = audits_store.get(audit_id)
    
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    
    return audit

@api_router.get("/audit/{audit_id}/stream")
async def stream_audit_progress(audit_id: str):
    """Stream audit progress updates via SSE"""
    async def event_generator():
        last_progress = -1
        while True:
            audit = audits_store.get(audit_id)
            
            if not audit:
                yield f"data: {json.dumps({'error': 'Audit not found'})}\n\n"
                break
            
            if audit.get('progress', 0) != last_progress or audit.get('status') == 'completed':
                last_progress = audit.get('progress', 0)
                yield f"data: {json.dumps(audit)}\n\n"
            
            if audit.get('status') in ['completed', 'failed']:
                break
            
            await asyncio.sleep(1)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

@api_router.get("/audits")
async def list_audits(limit: int = 20):
    """List recent audits"""
    sorted_audits = sorted(
        audits_store.values(),
        key=lambda x: x.get('created_at', ''),
        reverse=True
    )[:limit]
    return {"audits": sorted_audits, "count": len(sorted_audits)}

@api_router.delete("/audit/{audit_id}")
async def delete_audit(audit_id: str):
    """Delete an audit"""
    if audit_id not in audits_store:
        raise HTTPException(status_code=404, detail="Audit not found")
    del audits_store[audit_id]
    return {"message": "Audit deleted", "id": audit_id}


# Include router
app.include_router(api_router)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)
