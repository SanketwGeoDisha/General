from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
import json
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any, Tuple
import uuid
from datetime import datetime, timezone
import asyncio
import requests
from google import genai
from google.genai import types
import re
from urllib.parse import urlparse, quote
from bs4 import BeautifulSoup
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import functools
import hashlib
from collections import OrderedDict

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# In-memory storage for audits
audits_store: Dict[str, Dict[str, Any]] = {}

# ============ Intelligent Cache System ============

class LRUCache:
    """Thread-safe LRU Cache with TTL support for search results"""
    def __init__(self, max_size: int = 500, ttl_seconds: int = 3600):
        self.cache: OrderedDict = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._lock = asyncio.Lock() if asyncio.get_event_loop().is_running() else None
    
    def _get_key(self, *args) -> str:
        """Generate cache key from arguments"""
        return hashlib.md5(json.dumps(args, sort_keys=True).encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """Get item from cache if not expired"""
        if key in self.cache:
            item, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                self.cache.move_to_end(key)
                return item
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, value: Any):
        """Set item in cache with current timestamp"""
        if key in self.cache:
            del self.cache[key]
        elif len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)
        self.cache[key] = (value, time.time())
    
    def clear(self):
        """Clear all cache"""
        self.cache.clear()

# Global caches
search_cache = LRUCache(max_size=1000, ttl_seconds=7200)  # 2 hours for search results
content_cache = LRUCache(max_size=200, ttl_seconds=14400)  # 4 hours for fetched content

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
            "data_type": "string",
            "unit": "formatted list",
            "validation_rules": "string with grouped courses",
            "extraction_instruction": "List all courses in compact format: Group by degree type with specializations in parentheses. Format: 'B.Tech(CSE, ECE, ME), M.Tech(VLSI, AI), MBA, BBA, Ph.D'. Use standard abbreviations (CSE=Computer Science, ECE=Electronics, ME=Mechanical, EE=Electrical, CE=Civil, etc). Separate degree types with commas.",
            "example_value": "B.Tech(CSE, ECE, ME, EE, CE), M.Tech(CSE, VLSI), MBA, Ph.D",
            "remarks_required": False,
            "search_keywords": ["courses offered", "programs offered", "academic programs", "B.Tech", "M.Tech", "MBA", "departments", "branches", "specializations"]
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
            "data_type": "string",
            "unit": "LPA or Cr",
            "validation_rules": "formatted string with LPA or Cr suffix",
            "extraction_instruction": "Highest annual compensation offered to any student in last placement season. Format: If below 1 Crore (< 1,00,00,000), show as 'X.XX LPA' (e.g., '42 LPA', '8.5 LPA'). If 1 Crore or above, show as 'X.XX Cr' (e.g., '1.2 Cr', '2.1 Cr'). Always include the unit suffix.",
            "example_value": "42 LPA",
            "remarks_required": False,
            "search_keywords": ["highest package", "maximum salary", "top CTC", "highest CTC", "best package", "maximum compensation", "highest offer"]
        },
        {
            "field_name": "median_compensation_last_batch",
            "display_name": "Median Compensation (Last Batch)",
            "category": "Placements",
            "data_type": "string",
            "unit": "LPA or Cr",
            "validation_rules": "formatted string with LPA or Cr suffix",
            "extraction_instruction": "Median annual compensation offered to placed students from last graduating batch. Format: If below 1 Crore (< 1,00,00,000), show as 'X.XX LPA' (e.g., '8.5 LPA', '12 LPA'). If 1 Crore or above, show as 'X.XX Cr' (e.g., '1.2 Cr'). Always include the unit suffix.",
            "example_value": "8.5 LPA",
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
            "extraction_instruction": "Number of graduating students who enrolled in higher education (Masters/PhD) after graduation. Extract from NIRF data under 'Students admitted to higher studies' or 'Metric 5.2' section.",
            "example_value": 150,
            "remarks_required": False,
            "search_keywords": ["NIRF higher studies", "students admitted to higher studies", "pursuing masters", "MS abroad", "PhD admission", "higher education", "postgraduate studies", "NIRF metric 5.2", "nirfindia.org higher education"]
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
            "field_name": "nirf_ranking",
            "display_name": "NIRF Ranking",
            "category": "Accreditations & Rankings",
            "data_type": "string",
            "unit": "rank",
            "validation_rules": "exact rank number or band string",
            "extraction_instruction": "NIRF ranking from nirfindia.org. If exact rank is available (e.g., '1', '5', '23'), show the exact number. If only band is available (e.g., '51-100', '101-150', '151-200', '201+'), show the band. Prefer exact rank over band. Use 'Not Ranked' if not in NIRF.",
            "example_value": "5",
            "remarks_required": False,
            "search_keywords": ["NIRF ranking", "NIRF 2024", "NIRF 2025", "national ranking", "NIRF rank", "nirfindia.org", "India Rankings", "engineering ranking"]
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
            "extraction_instruction": "Total number of students currently enrolled in PhD/doctoral programs. Look for 'research scholars', 'PhD students', 'doctoral candidates'. Check NIRF data, annual reports, and research section.",
            "example_value": 85,
            "remarks_required": False,
            "search_keywords": ["PhD students", "doctoral students", "research scholars", "PhD enrollment", "doctoral programme", "research scholar count", "PhD admissions", "doctoral candidates", "NIRF research scholars"]
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
        
        # Priority 3: NAAC
        if 'naac' in url_lower:
            return 3
        
        # Priority 4: Other government
        if '.gov.in' in url_lower or '.nic.in' in url_lower:
            return 4
        
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


# ============ Retry Logic with Exponential Backoff ============

def retry_with_backoff(max_retries: int = 3, base_delay: float = 0.5, max_delay: float = 8.0):
    """Decorator for retry logic with exponential backoff"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        time.sleep(delay)
                        logging.warning(f"Retry {attempt + 1}/{max_retries} for {func.__name__}: {e}")
            raise last_exception
        return wrapper
    return decorator


# ============ Structured Data Parsers ============

class StructuredDataParser:
    """Parse structured data from NIRF PDFs, tables, and official documents"""
    
    # NIRF data patterns for extraction
    NIRF_PATTERNS = {
        'median_salary': [
            r'median\s*(?:salary|package|ctc|compensation)[:\s]*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(?:lpa|lakhs?|lac|per\s*annum)?',
            r'(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:lpa|lakhs?)?\s*median',
            r'median[:\s]*([\d.]+)\s*(?:lakh|lac)',
        ],
        'highest_salary': [
            r'(?:highest|maximum|max|top)\s*(?:salary|package|ctc)[:\s]*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)',
            r'(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:lpa|lakhs?)?\s*(?:highest|maximum)',
        ],
        'placement_percentage': [
            r'placement\s*(?:rate|percentage|%)[:\s]*([\d.]+)\s*%?',
            r'([\d.]+)\s*%\s*(?:placed|placement)',
            r'(?:placed|placement)[:\s]*([\d.]+)\s*%',
        ],
        'total_faculty': [
            r'(?:total|number\s*of)\s*faculty[:\s]*(\d+)',
            r'faculty\s*(?:strength|members|count)[:\s]*(\d+)',
            r'(\d+)\s*(?:faculty\s*members|professors)',
        ],
        'phd_faculty': [
            r'(?:faculty\s*with\s*)?ph\.?d\.?[:\s]*(\d+)',
            r'(\d+)\s*(?:faculty)?\s*with\s*ph\.?d',
            r'doctorate[:\s]*(\d+)',
        ],
        'total_students': [
            r'(?:total|enrolled)\s*students?[:\s]*(\d+)',
            r'student\s*(?:strength|enrollment)[:\s]*(\d+)',
            r'(\d+)\s*students?\s*enrolled',
        ],
        'nirf_rank': [
            r'nirf\s*(?:rank|ranking)[:\s]*#?(\d+)',
            r'ranked?\s*#?(\d+)\s*(?:in\s*)?nirf',
            r'nirf\s*(?:20\d{2})?[:\s]*#?(\d+)',
        ],
        'phd_students': [
            r'ph\.?d\.?\s*(?:students?|scholars?|enrollment|enrolled)[:\s]*(\d+)',
            r'(\d+)\s*(?:ph\.?d\.?|doctoral)\s*(?:students?|scholars?)',
            r'research\s*scholars?[:\s]*(\d+)',
            r'(\d+)\s*research\s*scholars?',
            r'doctoral\s*(?:students?|candidates?)[:\s]*(\d+)',
            r'(?:total|number\s*of)\s*ph\.?d[:\s]*(\d+)',
            r'ph\.?d\.?\s*programme?[:\s]*(\d+)\s*students?',
        ],
    }
    
    @classmethod
    def extract_numeric_data(cls, text: str, data_type: str) -> Optional[float]:
        """Extract numeric data using patterns"""
        if data_type not in cls.NIRF_PATTERNS:
            return None
        
        text_lower = text.lower()
        for pattern in cls.NIRF_PATTERNS[data_type]:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                value_str = match.group(1).replace(',', '')
                try:
                    return float(value_str)
                except ValueError:
                    continue
        return None
    
    @classmethod
    def extract_table_data(cls, html_content: str) -> List[Dict[str, Any]]:
        """Extract data from HTML tables"""
        tables_data = []
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            for table in soup.find_all('table'):
                rows = table.find_all('tr')
                if not rows:
                    continue
                
                # Extract headers
                headers = []
                header_row = rows[0]
                for th in header_row.find_all(['th', 'td']):
                    headers.append(th.get_text(strip=True))
                
                # Extract data rows
                table_data = []
                for row in rows[1:]:
                    cells = row.find_all(['td', 'th'])
                    row_data = {}
                    for i, cell in enumerate(cells):
                        key = headers[i] if i < len(headers) else f"col_{i}"
                        row_data[key] = cell.get_text(strip=True)
                    if row_data:
                        table_data.append(row_data)
                
                if table_data:
                    tables_data.append({
                        'headers': headers,
                        'rows': table_data
                    })
        except Exception as e:
            logging.warning(f"Table extraction error: {e}")
        
        return tables_data
    
    @classmethod
    def extract_all_numbers(cls, text: str) -> Dict[str, Any]:
        """Extract all structured numeric data from text"""
        extracted = {}
        for data_type in cls.NIRF_PATTERNS.keys():
            value = cls.extract_numeric_data(text, data_type)
            if value is not None:
                extracted[data_type] = value
        return extracted


# ============ KPI Auditor Class ============

class CollegeKPIAuditor:
    def __init__(self):
        self.kpis_data = self._load_kpis_from_schema()
        self.serper_api_key = os.environ.get("SERPER_API_KEY")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY")
        self.validator = OfficialSourceValidator()
        self.parser = StructuredDataParser()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })
        # Disable SSL verification for problematic sites (with warning suppression)
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.session.verify = False
        
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
        """Search specifically for a single KPI using its keywords - ENHANCED VERSION"""
        kpi_data = {
            "kpi_name": kpi['name'],
            "search_results": [],
            "fetched_content": []
        }
        
        keywords = kpi.get('search_keywords', [])
        if not keywords:
            return kpi_data
        
        # Build targeted search queries for this KPI - MORE COMPREHENSIVE
        queries = []
        
        # Use top 2 keywords for speed
        for keyword in keywords[:2]:
            queries.append(f'"{college_name}" {keyword}')
        
        # Add site-specific search for official sources
        primary_keyword = keywords[0] if keywords else kpi['name']
        queries.append(f'site:.ac.in OR site:.edu.in "{college_name}" {primary_keyword}')
        
        seen_urls = set()
        
        # Reduced to 3 queries per KPI for speed
        for query in queries[:3]:
            result = self.search_official_sources(query, num_results=5)
            if result.get("official_results"):
                for r in result["official_results"]:
                    url = r.get('url', '')
                    if url not in seen_urls:
                        seen_urls.add(url)
                        kpi_data["search_results"].append(r)
            time.sleep(0.03)  # Minimal rate limiting
        
        # Fetch content from top 3 official URLs for speed
        urls_to_fetch = [r['url'] for r in kpi_data["search_results"][:3]]
        
        for url in urls_to_fetch:
            content = self.fetch_webpage_content(url, max_length=8000)
            if content.get('success'):
                kpi_data["fetched_content"].append(content)
        
        return kpi_data

    def search_public_disclosure(self, college_name: str, abbreviation: str = "") -> Dict[str, Any]:
        """
        Search for Mandatory Public Disclosure pages (AICTE/UGC requirement).
        These pages contain standardized KPI data like faculty, infrastructure, placements, etc.
        """
        disclosure_data = {
            "pages": [],
            "pdfs": [],
            "fetched_content": []
        }
        
        # Mandatory Disclosure search queries - AICTE requires all colleges to have these
        disclosure_queries = [
            f'"{college_name}" "mandatory disclosure" site:.ac.in OR site:.edu.in',
            f'"{college_name}" "public disclosure" AICTE',
            f'"{college_name}" "mandatory disclosure" filetype:pdf',
            f'"{college_name}" AICTE approval faculty infrastructure',
        ]
        
        if abbreviation:
            disclosure_queries.append(f'"{abbreviation}" "mandatory disclosure"')
        
        seen_urls = set()
        
        # Execute disclosure searches in parallel
        def run_disclosure_search(query):
            return self.search_official_sources(query, num_results=10)
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_query = {executor.submit(run_disclosure_search, q): q for q in disclosure_queries}
            for future in as_completed(future_to_query):
                result = future.result()
                if result.get("official_results"):
                    for r in result["official_results"]:
                        url = r.get('url', '')
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            # Check if it's a PDF
                            if url.lower().endswith('.pdf'):
                                disclosure_data["pdfs"].append(r)
                            else:
                                disclosure_data["pages"].append(r)
        
        logger.info(f"Found {len(disclosure_data['pages'])} disclosure pages and {len(disclosure_data['pdfs'])} PDFs")
        return disclosure_data

    def fetch_disclosure_page_and_pdfs(self, page_url: str, max_pdfs: int = 3) -> Dict[str, Any]:
        """
        Fetch a disclosure page and extract PDF links from it.
        Returns page content plus any linked PDF content.
        """
        result = {
            "page_content": None,
            "pdf_links": [],
            "pdf_contents": []
        }
        
        try:
            # Fetch the HTML page
            response = self.session.get(page_url, timeout=30, allow_redirects=True, verify=False)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract all PDF links from the page
            base_url = '/'.join(page_url.split('/')[:3])
            pdf_links = set()
            
            for link in soup.find_all('a', href=True):
                href = link['href']
                # Check if it's a PDF link
                if '.pdf' in href.lower():
                    # Handle relative URLs
                    if href.startswith('/'):
                        full_url = base_url + href
                    elif href.startswith('http'):
                        full_url = href
                    else:
                        # Relative to current path
                        full_url = '/'.join(page_url.rsplit('/', 1)[:-1]) + '/' + href
                    
                    # Filter for disclosure-related PDFs
                    href_lower = href.lower()
                    if any(kw in href_lower for kw in ['disclosure', 'faculty', 'infrastructure', 'placement', 
                                                        'admission', 'approval', 'aicte', 'mandatory', 
                                                        'annual', 'report', 'ssr', 'aqar', 'naac']):
                        pdf_links.add(full_url)
                    elif len(pdf_links) < max_pdfs:
                        # Include other PDFs if we haven't found disclosure-specific ones
                        pdf_links.add(full_url)
            
            # Remove script, style elements for text extraction
            for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
                script.decompose()
            
            text = soup.get_text(separator=' ', strip=True)
            text = re.sub(r'\s+', ' ', text)
            
            result["page_content"] = {
                "url": page_url,
                "title": soup.title.string if soup.title else "Disclosure Page",
                "content": text[:15000],
                "success": True
            }
            
            result["pdf_links"] = list(pdf_links)[:max_pdfs]
            
            # Fetch PDF contents in parallel
            def fetch_single_pdf(pdf_url):
                return self._fetch_pdf_content(pdf_url, max_length=25000)
            
            if result["pdf_links"]:
                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_pdf = {executor.submit(fetch_single_pdf, url): url for url in result["pdf_links"]}
                    for future in as_completed(future_to_pdf):
                        pdf_content = future.result()
                        if pdf_content.get("success"):
                            result["pdf_contents"].append(pdf_content)
                            logger.info(f"Extracted PDF content: {pdf_content['url']} ({len(pdf_content.get('content', ''))} chars)")
            
        except Exception as e:
            logger.warning(f"Failed to fetch disclosure page {page_url}: {e}")
        
        return result

    def _fetch_pdf_content(self, url: str, max_length: int = 20000) -> Dict[str, Any]:
        """Fetch and extract text content from a PDF file"""
        try:
            import io
            try:
                import PyPDF2
            except ImportError:
                # Try alternative PDF library
                try:
                    import pdfplumber
                    response = self.session.get(url, timeout=60, verify=False)
                    response.raise_for_status()
                    pdf_file = io.BytesIO(response.content)
                    text_parts = []
                    with pdfplumber.open(pdf_file) as pdf:
                        for page in pdf.pages[:30]:  # Limit to 30 pages
                            page_text = page.extract_text()
                            if page_text:
                                text_parts.append(page_text)
                    text = "\n".join(text_parts)
                    if len(text) > max_length:
                        text = text[:max_length] + "..."
                    return {
                        "url": url,
                        "title": f"PDF: {url.split('/')[-1]}",
                        "content": text,
                        "success": True
                    }
                except ImportError:
                    return {"url": url, "content": "", "error": "No PDF library available (install PyPDF2 or pdfplumber)", "success": False}
            
            # Use PyPDF2
            response = self.session.get(url, timeout=60, verify=False)
            response.raise_for_status()
            pdf_file = io.BytesIO(response.content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            text_parts = []
            for page_num in range(min(len(pdf_reader.pages), 30)):  # Limit to 30 pages
                page = pdf_reader.pages[page_num]
                text_parts.append(page.extract_text())
            
            text = "\n".join(text_parts)
            text = re.sub(r'\s+', ' ', text)
            
            if len(text) > max_length:
                text = text[:max_length] + "..."
            
            return {
                "url": url,
                "title": f"PDF: {url.split('/')[-1]}",
                "content": text,
                "success": True
            }
            
        except Exception as e:
            logger.warning(f"Failed to fetch PDF {url}: {e}")
            return {"url": url, "content": "", "error": str(e), "success": False}

    def fetch_webpage_content(self, url: str, max_length: int = 20000, retry_count: int = 2) -> Dict[str, Any]:
        """Fetch and extract text content from a webpage with retry logic and CACHING"""
        # Check cache first
        cache_key = content_cache._get_key(url, max_length)
        cached_result = content_cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Cache hit for URL: {url[:50]}...")
            return cached_result
        
        for attempt in range(retry_count):
            try:
                # Handle PDF files
                if url.lower().endswith('.pdf'):
                    result = self._fetch_pdf_content(url, max_length)
                    if result.get("success"):
                        content_cache.set(cache_key, result)
                    return result
                
                # Increased timeout and disabled SSL verification
                response = self.session.get(url, timeout=25, allow_redirects=True, verify=False)
                response.raise_for_status()
                
                # Parse HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extract tables for structured data
                tables_data = StructuredDataParser.extract_table_data(response.text)
                
                # Remove script, style elements
                for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    script.decompose()
                
                # Get text
                text = soup.get_text(separator=' ', strip=True)
                
                # Clean up whitespace
                text = re.sub(r'\s+', ' ', text)
                
                # Append table data as structured text
                if tables_data:
                    text += "\n\n=== EXTRACTED TABLES ===\n"
                    for i, table in enumerate(tables_data[:3]):  # Limit to 3 tables
                        text += f"Table {i+1}: {json.dumps(table['rows'][:10])}\n"
                
                # Truncate if too long
                if len(text) > max_length:
                    text = text[:max_length] + "..."
                
                result = {
                    "url": url,
                    "title": soup.title.string if soup.title else "",
                    "content": text,
                    "tables": tables_data[:3] if tables_data else [],
                    "success": True
                }
                
                # Cache the result
                content_cache.set(cache_key, result)
                return result
                
            except Exception as e:
                if attempt < retry_count - 1:
                    time.sleep(0.5)  # Reduced wait before retry
                    continue
                logger.warning(f"Failed to fetch {url} after {retry_count} attempts: {e}")
                return {"url": url, "content": "", "error": str(e), "success": False}
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

    def extract_institute_info(self, college_name: str, wiki_content: str) -> Dict[str, Any]:
        """Extract basic institute information from Wikipedia content"""
        institute_info = {
            "full_name": college_name,
            "short_name": "",
            "location": "",
            "city": "",
            "state": "",
            "established": "",
            "type": "",
            "motto": "",
            "website": "",
            "wikipedia_url": ""
        }
        
        if not wiki_content:
            return institute_info
        
        try:
            content = wiki_content[:5000]  # First part usually has key info
            
            # Extract location patterns
            location_patterns = [
                r'(?:located|situated|based)\s+(?:in|at)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)?',
                r'(?:city|town|district)\s+(?:of|in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
                r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s*India',
            ]
            
            for pattern in location_patterns:
                match = re.search(pattern, content)
                if match:
                    groups = match.groups()
                    if groups[0]:
                        institute_info["city"] = groups[0].strip()
                    if len(groups) > 1 and groups[1]:
                        institute_info["state"] = groups[1].strip()
                    if institute_info["city"]:
                        institute_info["location"] = f"{institute_info['city']}, {institute_info['state']}" if institute_info["state"] else institute_info["city"]
                    break
            
            # Extract establishment year
            established_patterns = [
                r'(?:established|founded|started)\s+(?:in\s+)?([12][0-9]{3})',
                r'([12][0-9]{3})\s*[-–]\s*(?:present|now)',
                r'since\s+([12][0-9]{3})',
            ]
            
            for pattern in established_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    institute_info["established"] = match.group(1)
                    break
            
            # Extract type of institution
            type_patterns = [
                r'(public|private|autonomous|deemed|state|central|national)\s+(?:university|institute|college)',
                r'(?:is\s+a[n]?)\s+(public|private|autonomous|deemed)\s+(?:research)?\s*(?:university|institute|institution)',
            ]
            
            for pattern in type_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    institute_info["type"] = match.group(1).title()
                    break
            
            # Extract motto
            motto_match = re.search(r'motto[:\s]+["\']?([^"\n]+)["\']?', content, re.IGNORECASE)
            if motto_match:
                institute_info["motto"] = motto_match.group(1).strip()[:100]
            
            # Extract website
            website_match = re.search(r'(?:website|official\s+site)[:\s]+(?:www\.)?([a-z0-9.-]+\.(?:ac\.in|edu\.in|edu|org))', content, re.IGNORECASE)
            if website_match:
                institute_info["website"] = f"https://www.{website_match.group(1)}"
            
            # Generate short name/abbreviation
            words = college_name.split()
            if len(words) > 2:
                # Check for common abbreviations in content
                abbrev_match = re.search(r'\(([A-Z]{2,10})\)', content)
                if abbrev_match:
                    institute_info["short_name"] = abbrev_match.group(1)
                else:
                    # Generate from initials of major words
                    initials = ''.join([w[0].upper() for w in words if w[0].isupper() and len(w) > 2])
                    if len(initials) >= 2:
                        institute_info["short_name"] = initials
            
        except Exception as e:
            logger.warning(f"Failed to extract institute info: {e}")
        
        return institute_info

    @retry_with_backoff(max_retries=3, base_delay=0.5)
    def search_official_sources(self, query: str, num_results: int = 10) -> Dict[str, Any]:
        """Perform web search with strict filtering for official sources only - WITH CACHING"""
        if not self.serper_api_key:
            return {"error": "SERPER_API_KEY not set", "results": []}
        
        # Check cache first
        cache_key = search_cache._get_key(query, num_results)
        cached_result = search_cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Cache hit for query: {query[:50]}...")
            return cached_result
        
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
            
            result = {
                "query": query,
                "official_results": filtered_results,
                "knowledge_graph": knowledge_graph,
                "total_found": len(filtered_results)
            }
            
            # Cache the result
            search_cache.set(cache_key, result)
            
            return result
            
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
        1. Official College Website (fetched content)
        2. Public Disclosure (AICTE/UGC)
        3. NIRF Search Results
        4. NAAC Documents
        """
        
        clean_name = college_name.strip()
        all_data = {
            "official_website": [],
            "official_website_content": [],
            "public_disclosure": [],
            "public_disclosure_content": [],
            "nirf": [],
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
        
        # ============ PRIORITY 1: OFFICIAL COLLEGE WEBSITE ============
        if progress_callback:
            await progress_callback("Searching Official College Website...", 5)
        
        # Consolidated search queries for speed
        official_queries = [
            f'site:.ac.in OR site:.edu.in "{clean_name}" official placements faculty',
            f'"{clean_name}" official courses fees infrastructure hostel',
            f'"{clean_name}" placement statistics 2024 2025',
            f'"{clean_name}" PhD research scholars doctoral students enrollment',
        ]
        
        if abbreviation:
            official_queries.append(f'site:.ac.in OR site:.edu.in "{abbreviation}" official')
        
        official_urls_to_fetch = set()
        
        # Execute searches in parallel using ThreadPoolExecutor
        def run_search(query):
            return self.search_official_sources(query, num_results=8)
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_query = {executor.submit(run_search, q): q for q in official_queries}
            for future in as_completed(future_to_query):
                result = future.result()
                if result.get("official_results"):
                    for r in result["official_results"]:
                        if r['source_type'] == "Official College Website":
                            all_data["official_website"].append(r)
                            combined_text_parts.append(f"[OFFICIAL WEBSITE SEARCH]\nTitle: {r['title']}\nURL: {r['url']}\nSnippet: {r['snippet']}\n")
                            if r['url'] and not r['url'].lower().endswith('.pdf'):
                                official_urls_to_fetch.add(r['url'])
        
        if progress_callback:
            await progress_callback(f"Official website search complete", 35)
        
        # Fetch content from top official pages in parallel
        if progress_callback:
            await progress_callback("Fetching official website content...", 40)
        
        urls_to_fetch = [u for u in list(official_urls_to_fetch)[:8] if u not in all_data["fetched_urls"]]
        
        def fetch_url(url):
            try:
                return self.fetch_webpage_content(url, max_length=10000)
            except Exception as e:
                logger.warning(f"Failed to fetch {url}: {e}")
                return None
        
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_url = {executor.submit(fetch_url, url): url for url in urls_to_fetch}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                page_content = future.result()
                if page_content and page_content.get("success") and page_content.get("content"):
                    all_data["official_website_content"].append(page_content)
                    all_data["fetched_urls"].add(url)
                    combined_text_parts.append(f"[OFFICIAL WEBSITE PAGE CONTENT]\nURL: {url}\nTitle: {page_content.get('title', '')}\nContent: {page_content['content']}\n")
                    logger.info(f"Fetched official page: {url} ({len(page_content['content'])} chars)")
        
        # ============ PRIORITY 2.5: MANDATORY PUBLIC DISCLOSURE (AICTE/UGC) ============
        if progress_callback:
            await progress_callback("Searching Mandatory Public Disclosure pages...", 45)
        
        # Search for public disclosure pages and PDFs
        disclosure_data = self.search_public_disclosure(clean_name, abbreviation)
        
        # Process disclosure pages - these contain standardized KPI data
        disclosure_pages_to_fetch = []
        for page in disclosure_data.get("pages", [])[:4]:
            all_data["public_disclosure"].append(page)
            disclosure_pages_to_fetch.append(page['url'])
            combined_text_parts.append(f"[PUBLIC DISCLOSURE PAGE]\nTitle: {page['title']}\nURL: {page['url']}\nSnippet: {page['snippet']}\n")
        
        # Fetch disclosure pages and extract PDFs from them
        if disclosure_pages_to_fetch:
            if progress_callback:
                await progress_callback("Fetching Public Disclosure pages and PDFs...", 48)
            
            def fetch_disclosure_with_pdfs(page_url):
                return self.fetch_disclosure_page_and_pdfs(page_url, max_pdfs=2)
            
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_page = {executor.submit(fetch_disclosure_with_pdfs, url): url for url in disclosure_pages_to_fetch[:3]}
                for future in as_completed(future_to_page):
                    page_url = future_to_page[future]
                    result = future.result()
                    
                    # Add page content
                    if result.get("page_content") and result["page_content"].get("success"):
                        all_data["public_disclosure_content"].append(result["page_content"])
                        all_data["fetched_urls"].add(page_url)
                        combined_text_parts.append(f"[PUBLIC DISCLOSURE PAGE CONTENT]\nURL: {page_url}\nTitle: {result['page_content'].get('title', '')}\nContent: {result['page_content']['content']}\n")
                        logger.info(f"Fetched disclosure page: {page_url}")
                    
                    # Add PDF contents - these are gold for KPIs
                    for pdf_content in result.get("pdf_contents", []):
                        all_data["public_disclosure_content"].append(pdf_content)
                        combined_text_parts.append(f"[PUBLIC DISCLOSURE PDF - HIGH VALUE KPI DATA]\nURL: {pdf_content['url']}\nTitle: {pdf_content.get('title', 'PDF Document')}\nContent: {pdf_content['content']}\n")
                        logger.info(f"Extracted disclosure PDF: {pdf_content['url']} ({len(pdf_content.get('content', ''))} chars)")
        
        # Also directly fetch any PDFs found in search results
        for pdf in disclosure_data.get("pdfs", [])[:3]:
            if pdf['url'] not in all_data["fetched_urls"]:
                pdf_content = self._fetch_pdf_content(pdf['url'], max_length=25000)
                if pdf_content.get("success"):
                    all_data["public_disclosure_content"].append(pdf_content)
                    all_data["fetched_urls"].add(pdf['url'])
                    combined_text_parts.append(f"[PUBLIC DISCLOSURE PDF - DIRECT]\nURL: {pdf['url']}\nTitle: {pdf.get('title', 'PDF')}\nContent: {pdf_content['content']}\n")
                    logger.info(f"Fetched direct disclosure PDF: {pdf['url']}")
        
        if progress_callback:
            disclosure_count = len(all_data.get("public_disclosure_content", []))
            await progress_callback(f"Public Disclosure complete: {disclosure_count} documents fetched", 52)
        
        # ============ PRIORITY 3: NIRF DATA ============
        if progress_callback:
            await progress_callback("Searching NIRF Documents...", 55)
        
        nirf_queries = [
            f'site:nirfindia.org "{clean_name}"',
            f'"{clean_name}" NIRF 2024 ranking placement median salary',
            f'"{clean_name}" NIRF research scholars PhD students faculty',
        ]
        if abbreviation:
            nirf_queries.append(f'site:nirfindia.org "{abbreviation}"')
        
        # Parallel NIRF search
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_query = {executor.submit(run_search, q): q for q in nirf_queries}
            for future in as_completed(future_to_query):
                result = future.result()
                if result.get("official_results"):
                    for r in result["official_results"]:
                        if r['source_type'] == "NIRF" or 'nirf' in r['url'].lower():
                            all_data["nirf"].append(r)
                            combined_text_parts.append(f"[NIRF]\nTitle: {r['title']}\nURL: {r['url']}\nData: {r['snippet']}\n")
        
        # ============ PRIORITY 4: NAAC DOCUMENTS ============
        if progress_callback:
            await progress_callback("Searching NAAC Documents...", 65)
        
        naac_query = f'site:naac.gov.in "{clean_name}" OR "{clean_name}" NAAC accreditation'
        result = self.search_official_sources(naac_query, num_results=5)
        if result.get("official_results"):
            for r in result["official_results"]:
                if 'naac' in r['url'].lower():
                    all_data["naac"].append(r)
                    combined_text_parts.append(f"[NAAC]\nTitle: {r['title']}\nURL: {r['url']}\nData: {r['snippet']}\n")
        
        # ============ PRIORITY 5: PER-KPI TARGETED SEARCH (PARALLEL) ============
        if progress_callback:
            await progress_callback("Searching for specific KPI data (parallel)...", 70)
        
        all_data["kpi_specific_data"] = {}
        
        # Search KPIs in parallel batches
        def search_single_kpi(kpi):
            return (kpi['name'], self.search_for_kpi(clean_name, kpi, abbreviation))
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_kpi = {executor.submit(search_single_kpi, kpi): kpi for kpi in self.kpis_data}
            for future in as_completed(future_to_kpi):
                kpi_name, kpi_search_data = future.result()
                all_data["kpi_specific_data"][kpi_name] = kpi_search_data
                
                # Add to combined text
                if kpi_search_data["search_results"]:
                    combined_text_parts.append(f"\n[KPI-SPECIFIC: {kpi_name}]")
                    for r in kpi_search_data["search_results"][:2]:
                        combined_text_parts.append(f"  Source: {r['url']}\n  Snippet: {r['snippet']}")
                
                if kpi_search_data["fetched_content"]:
                    for content in kpi_search_data["fetched_content"][:1]:
                        combined_text_parts.append(f"  [Fetched Page for {kpi_name}]\n  URL: {content['url']}\n  Content: {content['content'][:2000]}")
        
        if progress_callback:
            await progress_callback(f"KPI-specific search complete", 85)
        
        all_data["combined_text"] = "\n\n".join(combined_text_parts)
        
        # Convert set to list for JSON serialization
        all_data["fetched_urls"] = list(all_data["fetched_urls"])
        
        if progress_callback:
            total_sources = len(all_data["official_website"]) + len(all_data["nirf"]) + len(all_data["naac"]) + len(all_data["public_disclosure"])
            content_pages = len(all_data["official_website_content"])
            disclosure_docs = len(all_data.get("public_disclosure_content", []))
            kpi_sources = sum(len(v.get("search_results", [])) for v in all_data.get("kpi_specific_data", {}).values())
            await progress_callback(f"Data collection complete. {total_sources} sources, {disclosure_docs} disclosure docs, {content_pages} pages fetched", 98)
        
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
                                               search_data: Dict[str, Any], client) -> List[Dict]:
        """Extract KPI values using Gemini with STRICT official source validation and per-KPI data"""
        
        # Build structured data from official sources - prioritize FULL content
        source_sections = []
        
        # Add pre-extracted structured data if available
        if search_data.get("structured_extracted"):
            source_sections.append("=== PRE-EXTRACTED STRUCTURED DATA (VERIFIED NUMERIC VALUES) ===")
            for key, value in search_data["structured_extracted"].items():
                source_sections.append(f"{key}: {value}")
            source_sections.append("")
        
        # PRIORITY 0 (HIGHEST): PUBLIC DISCLOSURE PAGES AND PDFs (AICTE Mandatory Data)
        if search_data.get("public_disclosure_content"):
            source_sections.append("=== MANDATORY PUBLIC DISCLOSURE (HIGHEST PRIORITY - AICTE/UGC VERIFIED DATA) ===")
            source_sections.append("NOTE: This data is from mandatory disclosure documents required by AICTE/UGC. It contains verified KPIs.")
            for item in search_data["public_disclosure_content"][:6]:
                source_sections.append(f"Document URL: {item.get('url', '')}")
                source_sections.append(f"Document Title: {item.get('title', '')}")
                source_sections.append(f"Content:\n{item.get('content', '')[:12000]}")
                source_sections.append("")
        
        # PRIORITY 1: Fetched Official Website Content
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
        
        if search_data.get("naac"):
            source_sections.append("=== NAAC DOCUMENTS (ACCREDITATION DATA) ===")
            for item in search_data["naac"][:5]:
                source_sections.append(f"Title: {item['title']}")
                source_sections.append(f"URL: {item['url']}")
                source_sections.append(f"Content: {item['snippet']}")
                source_sections.append("")
        
        search_content = "\n".join(source_sections)
        
        # Limit content size for API - smart truncation
        if len(search_content) > 120000:
            search_content = search_content[:120000] + "\n[Content truncated for processing]"
        
        # Build KPI extraction instructions with search keywords hint
        kpi_details = []
        for i, kpi in enumerate(kpis_batch, 1):
            detail = f"{i}. KPI: {kpi['name']}"
            detail += f"\n   Category: {kpi['category']}"
            detail += f"\n   Data Type: {kpi['data_type']} ({kpi['unit']})"
            detail += f"\n   Extraction Rule: {kpi['extraction_instruction']}"
            if kpi.get('search_keywords'):
                detail += f"\n   Look for keywords: {', '.join(kpi['search_keywords'][:5])}"
            kpi_details.append(detail)
        
        kpi_list_str = "\n".join(kpi_details)
        
        prompt = f"""You are an elite data extraction AI specializing in Indian educational institution KPIs. Your extraction accuracy directly impacts institutional rankings and decisions.

INSTITUTION: "{college_name}"

=== EXTRACTION PHILOSOPHY ===
AGGRESSIVE EXTRACTION: Find data even from indirect mentions. "Data Not Found" is only acceptable if NO related information exists anywhere.

=== ACCURACY REQUIREMENTS ===
1. EXHAUSTIVE SEARCH: Read EVERY section of source data - data often appears in unexpected places
2. EXACT EXTRACTION: Copy numbers, percentages, and values exactly as they appear
3. SMART INFERENCE: Calculate derived values (e.g., percentage from ratio, total from sum of parts)
4. BOOLEAN LOGIC:
   - TRUE: Any mention of facility/feature existing (even partial)
   - FALSE: Explicit statement of non-existence
   - null: ONLY if topic never mentioned
5. CONTEXT CLUES: Use related data to infer missing values
6. PRIORITIZE SOURCES:
   a) Public Disclosure PDFs (AICTE mandated - highest trust)
   b) NIRF data (government verified)
   c) Official website content
   d) NAAC documents (accreditation verified)

=== CONFIDENCE SCORING ===
- "high": Direct quote with exact value from official document
- "medium": Calculated/inferred value OR from search snippets
- "low": Estimated from context OR partial data

=== DATA TYPE STRATEGIES ===
| Type | Extraction Strategy |
|------|---------------------|
| Integer | Look for: "X students", "total of X", statistics tables |
| Boolean | Look for: mentions, descriptions, facility lists, infrastructure pages |
| Array | Look for: lists, menus, program pages, department listings |
| Float | Look for: percentages, CTCs, ratios, averages |
| Object | Look for: fee structures, cutoffs, key-value data in tables |

=== OFFICIAL SOURCE DATA (READ EVERY SECTION) ===
{search_content}
=== END OF SOURCE DATA ===

=== KPIs TO EXTRACT ({len(kpis_batch)} items) ===
{kpi_list_str}
=== END KPIs ===

EXTRACTION EXAMPLES:
Example 1 - Infrastructure:
If source says "The college has smart classrooms with projectors and LMS system"
→ ICT-Enabled Learning Infrastructure: true, confidence: high

Example 2 - Numbers from context:
If source says "We have 15 departments with an average of 50 faculty per department"
→ Total Faculty: 750 (calculated: 15*50), confidence: medium

Example 3 - Lists from descriptions:
If source mentions "Our clubs include coding, robotics, music and drama societies"
→ Active Clubs: ["Coding Club", "Robotics Club", "Music Society", "Drama Society"], confidence: high

OUTPUT FORMAT - Return ONLY valid JSON array (no markdown, no explanation):
[
  {{
    "kpi_name": "exact KPI name from list",
    "category": "category from list",
    "value": "extracted/derived value OR 'Data Not Found' only if truly absent",
    "evidence_quote": "exact quote or calculation explanation",
    "source_url": "URL where found OR 'N/A'",
    "source_type": "Official College Website/NIRF/NAAC/AICTE/UGC/Public Disclosure/Derived",
    "confidence": "high/medium/low"
  }}
]

MANDATORY: Extract ALL {len(kpis_batch)} KPIs. Use inference and context clues. Return ONLY the JSON array now:"""

        # Define response schema for accurate KPI extraction
        kpi_response_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kpi_name": {"type": "string"},
                    "category": {"type": "string"},
                    "value": {},  # Can be string, number, boolean, array, or object
                    "evidence_quote": {"type": "string"},
                    "source_url": {"type": "string"},
                    "source_type": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]}
                },
                "required": ["kpi_name", "category", "value", "evidence_quote", "source_url", "source_type", "confidence"]
            }
        }

        try:
            # Use modern google-genai client API with Gemini 3 Flash
            response = client.models.generate_content(
                model="gemini-3-flash-preview",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.4,  # 0.0 is optimal for extraction accuracy
                    response_mime_type="application/json",
                    response_schema=kpi_response_schema,  # Schema for accuracy
                    thinking_config=types.ThinkingConfig(thinking_budget=1024)  # Low thinking for speed
                )
            )
            
            text = response.text.strip()
            
            # Clean markdown if present
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
                    # Don't reject, just mark as lower confidence
                    r['confidence'] = 'medium' if r.get('confidence') == 'high' else r.get('confidence', 'low')
                
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

    def _extract_structured_data(self, search_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract structured numeric data from all content sources"""
        extracted = {}
        
        # Process all content sources
        all_content = []
        
        # Add official website content
        for item in search_data.get("official_website_content", []):
            if item.get("content"):
                all_content.append(item["content"])
        
        # Add public disclosure content
        for item in search_data.get("public_disclosure_content", []):
            if item.get("content"):
                all_content.append(item["content"])
        
        # Add snippets from search results
        for item in search_data.get("nirf", []):
            if item.get("snippet"):
                all_content.append(item["snippet"])
        
        # Extract structured data from all content
        combined_text = " ".join(all_content)
        extracted = StructuredDataParser.extract_all_numbers(combined_text)
        
        logger.info(f"Structured data extracted: {list(extracted.keys())}")
        return extracted
    
    def _validate_and_boost_results(self, results: List[Dict], search_data: Dict[str, Any]) -> List[Dict]:
        """Validate results and boost confidence based on multiple source verification"""
        validated_results = []
        structured_data = search_data.get("structured_extracted", {})
        
        # Map KPI names to structured data types
        kpi_to_structured = {
            "Median Compensation (Last Batch)": "median_salary",
            "Maximum Compensation (Last Placement Season)": "highest_salary",
            "Total Faculty": "total_faculty",
            "PhD Faculty": "phd_faculty",
            "Total Students Enrolled": "total_students",
            "NIRF Ranking": "nirf_rank",
            "PhD Students Enrolled": "phd_students",
        }
        
        for result in results:
            kpi_name = result.get("kpi_name", "")
            current_value = result.get("value", "")
            current_confidence = result.get("confidence", "low")
            
            # Try to cross-verify with structured data
            if kpi_name in kpi_to_structured:
                structured_key = kpi_to_structured[kpi_name]
                if structured_key in structured_data:
                    structured_value = structured_data[structured_key]
                    
                    # If LLM didn't find data but structured parser did
                    if current_value in ["Data Not Found", "N/A", "", None]:
                        result["value"] = structured_value
                        result["confidence"] = "medium"
                        result["evidence_quote"] = f"Extracted via pattern matching: {structured_value}"
                        result["source_type"] = "Structured Extraction"
                    
                    # If both found similar values, boost confidence
                    elif current_value and str(current_value) != "Data Not Found":
                        try:
                            llm_val = float(str(current_value).replace(',', '').replace('₹', '').replace('Rs', ''))
                            # If values are within 20% of each other, boost confidence
                            max_val = max(llm_val, structured_value)
                            if max_val > 0 and abs(llm_val - structured_value) / max_val < 0.2:
                                result["confidence"] = "high"
                                result["evidence_quote"] += f" [Cross-verified: {structured_value}]"
                            elif max_val == 0 and llm_val == structured_value:
                                # Both are zero, they match exactly
                                result["confidence"] = "high"
                                result["evidence_quote"] += f" [Cross-verified: {structured_value}]"
                        except (ValueError, TypeError, ZeroDivisionError):
                            pass
            
            # Validate URL is from official source
            source_url = result.get("source_url", "")
            if source_url and source_url != "N/A":
                if not self.validator.is_official_source(source_url):
                    result["source_url"] = "N/A"
                    if result["confidence"] == "high":
                        result["confidence"] = "medium"
            
            # Ensure confidence is valid
            if result.get("confidence") not in ["high", "medium", "low"]:
                result["confidence"] = "low"
            
            validated_results.append(result)
        
        return validated_results

    async def run_audit(self, college_name: str, progress_callback=None) -> List[Dict]:
        """Run the complete audit process with STRICT official source filtering"""
        
        if not self.gemini_api_key:
            return [{"kpi_name": "Error", "category": "Config", "value": "GEMINI_API_KEY not set", 
                    "evidence_quote": "", "source_url": "", "confidence": "low"}]
        
        if not self.serper_api_key:
            return [{"kpi_name": "Error", "category": "Config", "value": "SERPER_API_KEY not set", 
                    "evidence_quote": "", "source_url": "", "confidence": "low"}]
        
        # Initialize modern google-genai client
        client = genai.Client(api_key=self.gemini_api_key)
        
        # Step 1: Gather data from OFFICIAL sources only
        if progress_callback:
            await progress_callback("Starting audit - gathering from OFFICIAL sources only...", 2)
        
        search_data = await self.gather_official_data(college_name, progress_callback)
        
        # Extract structured data from content using parser
        structured_data = self._extract_structured_data(search_data)
        search_data["structured_extracted"] = structured_data
        
        total_sources = (len(search_data["official_website"]) + len(search_data["nirf"]) + 
                        len(search_data["naac"]) + len(search_data.get("public_disclosure", [])))
        
        if total_sources < 2:
            return [{"kpi_name": "Error", "category": "Search", 
                    "value": "Insufficient official sources found. Please verify college name.", 
                    "evidence_quote": f"Found only {total_sources} official sources",
                    "source_url": "", "confidence": "low"}]
        
        if progress_callback:
            await progress_callback(f"Found {total_sources} official sources. Extracting KPIs...", 90)
        
        # Step 2: Extract KPIs in smaller batches for better accuracy (5 KPIs per batch)
        all_results = []
        batch_size = 5  # Smaller batches for better accuracy on each KPI
        total_kpis = len(self.kpis_data)
        
        for i in range(0, total_kpis, batch_size):
            batch = self.kpis_data[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total_kpis + batch_size - 1) // batch_size
            
            if progress_callback:
                progress = 90 + int(((i + batch_size) / total_kpis) * 9)
                await progress_callback(f"Extracting KPIs batch {batch_num}/{total_batches}...", min(progress, 99))
            
            batch_results = await self.extract_kpi_with_strict_sources(
                college_name, batch, search_data, client
            )
            all_results.extend(batch_results)
            
            await asyncio.sleep(0.05)  # Minimal delay between batches
        
        # Step 3: Validate and boost confidence
        if progress_callback:
            await progress_callback("Validating and cross-referencing results...", 99)
        
        all_results = self._validate_and_boost_results(all_results, search_data)
        
        if progress_callback:
            await progress_callback("Audit complete!", 100)
        
        return all_results


# Initialize auditor
auditor = CollegeKPIAuditor()

# ============ Background Task Processing ============

async def process_audit(audit_id: str, college_name: str):
    """Background task to process audit"""
    try:
        institute_info = {}
        
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
                "institute_info": institute_info,
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
            "priority_2": "Public Disclosure (AICTE/UGC Mandatory)",
            "priority_3": "NIRF (nirfindia.org)",
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
    
    # Calculate time taken if audit is completed
    response = dict(audit)
    if audit.get('status') == 'completed' and audit.get('created_at') and audit.get('completed_at'):
        try:
            created = datetime.fromisoformat(audit['created_at'].replace('Z', '+00:00'))
            completed = datetime.fromisoformat(audit['completed_at'].replace('Z', '+00:00'))
            time_taken_seconds = (completed - created).total_seconds()
            response['time_taken_seconds'] = time_taken_seconds
        except Exception as e:
            logger.warning(f"Could not calculate time taken: {e}")
    
    return response

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
