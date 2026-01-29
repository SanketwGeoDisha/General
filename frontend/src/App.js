import { useState, useEffect, useRef } from "react";
import "@/App.css";
import axios from "axios";
import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./components/ui/card";
import { Badge } from "./components/ui/badge";
import { Progress } from "./components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import { ScrollArea } from "./components/ui/scroll-area";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "./components/ui/accordion";
import { 
  Search, 
  GraduationCap, 
  Building2, 
  TrendingUp, 
  Users, 
  Award,
  BookOpen,
  Briefcase,
  Globe,
  CheckCircle,
  XCircle,
  Clock,
  AlertCircle,
  Download,
  RefreshCw,
  ChevronRight,
  Sparkles,
  ExternalLink
} from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Category icons mapping
const categoryIcons = {
  "Infrastructure & Sustainability": Building2,
  "Graduate Outcome & Employability": Briefcase,
  "Innovation, Startup & IP": Sparkles,
  "Research Quality & Impact Output": BookOpen,
  "Admissions (Quality & Diversity)": Users,
  "Industry Integration": Globe,
  "Teaching and Learning Environment": GraduationCap,
  "Student Experience and Well-Being": Award,
  "Internationalization & Global Reputation": Globe,
  "Quality Assurance and NEP Implementation": CheckCircle,
};

// Confidence colors
const confidenceColors = {
  high: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  medium: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  low: "bg-red-500/20 text-red-400 border-red-500/30",
};

function App() {
  const [collegeName, setCollegeName] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [currentAudit, setCurrentAudit] = useState(null);
  const [recentAudits, setRecentAudits] = useState([]);
  const [activeTab, setActiveTab] = useState("overview");
  const pollIntervalRef = useRef(null);

  // Load recent audits on mount
  useEffect(() => {
    loadRecentAudits();
  }, []);

  // Poll for audit updates
  useEffect(() => {
    if (currentAudit?.status === "processing" && currentAudit?.id) {
      pollIntervalRef.current = setInterval(async () => {
        try {
          const response = await axios.get(`${API}/audit/${currentAudit.id}`);
          setCurrentAudit(response.data);
          
          if (response.data.status === "completed" || response.data.status === "failed") {
            clearInterval(pollIntervalRef.current);
            setIsLoading(false);
            loadRecentAudits();
          }
        } catch (error) {
          console.error("Poll error:", error);
        }
      }, 2000);
    }

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, [currentAudit?.id, currentAudit?.status]);

  const loadRecentAudits = async () => {
    try {
      const response = await axios.get(`${API}/audits?limit=10`);
      setRecentAudits(response.data.audits || []);
    } catch (error) {
      console.error("Failed to load audits:", error);
    }
  };

  const startAudit = async () => {
    if (!collegeName.trim()) return;
    
    setIsLoading(true);
    setActiveTab("overview");
    
    try {
      const response = await axios.post(`${API}/audit/start`, {
        college_name: collegeName.trim()
      });
      
      setCurrentAudit({
        id: response.data.audit_id,
        college_name: collegeName.trim(),
        status: "processing",
        progress: 0,
        progress_message: "Starting audit...",
        results: [],
        summary: {}
      });
    } catch (error) {
      console.error("Start audit error:", error);
      setIsLoading(false);
      alert("Failed to start audit. Please try again.");
    }
  };

  const loadAudit = async (auditId) => {
    try {
      const response = await axios.get(`${API}/audit/${auditId}`);
      setCurrentAudit(response.data);
      setCollegeName(response.data.college_name || "");
      setActiveTab("overview");
    } catch (error) {
      console.error("Load audit error:", error);
    }
  };

  const exportResults = () => {
    if (!currentAudit?.results) return;
    
    // Format time taken for export
    const formatTimeTaken = (seconds) => {
      if (!seconds) return "N/A";
      if (seconds >= 60) {
        return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
      }
      return `${Math.round(seconds)}s`;
    };
    
    // Overview Section
    const overviewSection = [
      "=== INSTITUTE INFORMATION ===",
      `Full Name,"${currentAudit.institute_info?.full_name || currentAudit.college_name}"`,
      `Short Name,"${currentAudit.institute_info?.short_name || 'N/A'}"`,
      `Location,"${currentAudit.institute_info?.location || 'N/A'}"`,
      `City,"${currentAudit.institute_info?.city || 'N/A'}"`,
      `State,"${currentAudit.institute_info?.state || 'N/A'}"`,
      `Established,"${currentAudit.institute_info?.established || 'N/A'}"`,
      `Type,"${currentAudit.institute_info?.type || 'N/A'}"`,
      `Website,"${currentAudit.institute_info?.website || 'N/A'}"`,
      `Wikipedia,"${currentAudit.institute_info?.wikipedia_url || 'N/A'}"`,
      "",
      "=== AUDIT OVERVIEW ===",
      `Audit Date,"${currentAudit.created_at ? new Date(currentAudit.created_at).toLocaleString() : 'N/A'}"`,
      `Time Taken,"${formatTimeTaken(currentAudit.time_taken_seconds)}"`,
      `Data Found,${currentAudit.summary?.data_found || 0}`,
      `Data Not Found,${currentAudit.summary?.data_not_found || 0}`,
      `High Confidence,${currentAudit.summary?.high_confidence || 0}`,
      `Coverage Percentage,${currentAudit.summary?.coverage_percentage || 0}%`,
      "",
      "=== CATEGORY BREAKDOWN ===",
      "Category,Found,Total,Percentage"
    ];
    
    // Add category breakdown
    Object.entries(currentAudit.summary?.categories || {}).forEach(([category, stats]) => {
      const percentage = stats.total > 0 ? Math.round((stats.found / stats.total) * 100) : 0;
      overviewSection.push(`"${category}",${stats.found},${stats.total},${percentage}%`);
    });
    
    overviewSection.push("", "=== KPI DETAILS ===");
    
    const csvContent = [
      ...overviewSection,
      ["KPI Name", "Category", "Value", "Evidence", "Source URL", "Confidence"].join(","),
      ...currentAudit.results.map(r => [
        `"${r.kpi_name}"`,
        `"${r.category}"`,
        `"${r.value}"`,
        `"${(r.evidence_quote || "").replace(/"/g, '""')}"`,
        `"${r.source_url}"`,
        r.confidence
      ].join(","))
    ].join("\n");
    
    const blob = new Blob([csvContent], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${currentAudit.college_name}_audit_${new Date().toISOString().split("T")[0]}.csv`;
    a.click();
  };

  // Group results by category
  const groupedResults = currentAudit?.results?.reduce((acc, result) => {
    const category = result.category || "Other";
    if (!acc[category]) acc[category] = [];
    acc[category].push(result);
    return acc;
  }, {}) || {};

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white">
      {/* Grain overlay */}
      <div className="fixed inset-0 pointer-events-none opacity-[0.03] z-50">
        <div className="absolute inset-0" style={{backgroundImage: "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E\")"}}></div>
      </div>

      {/* Header */}
      <header className="border-b border-white/5 backdrop-blur-xl bg-[#0a0a0f]/80 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-400 to-cyan-600 flex items-center justify-center">
              <GraduationCap className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-semibold tracking-tight font-['Space_Grotesk']">AskDiya</h1>
              <p className="text-xs text-white/40">KPI Intelligence Platform</p>
            </div>
          </div>
          
          <div className="flex items-center gap-3">
            {currentAudit?.results?.length > 0 && (
              <Button 
                variant="outline" 
                size="sm" 
                onClick={exportResults}
                className="border-white/10 bg-white/5 hover:bg-white/10"
                data-testid="export-btn"
              >
                <Download className="w-4 h-4 mr-2" />
                Export CSV
              </Button>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        {/* Search Section */}
        <section className="mb-8">
          <Card className="bg-white/[0.02] border-white/5 backdrop-blur-sm">
            <CardContent className="p-6">
              <div className="flex flex-col md:flex-row gap-4">
                <div className="flex-1 relative">
                  <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/30" />
                  <Input
                    placeholder="Enter college name (e.g., IIT Bombay, NIT Trichy, VIT Vellore)"
                    value={collegeName}
                    onChange={(e) => setCollegeName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && startAudit()}
                    className="pl-12 h-14 bg-white/5 border-white/10 text-white placeholder:text-white/30 text-lg"
                    data-testid="college-input"
                  />
                </div>
                <Button 
                  onClick={startAudit}
                  disabled={isLoading || !collegeName.trim()}
                  className="h-14 px-8 bg-gradient-to-r from-teal-500 to-cyan-600 hover:from-teal-400 hover:to-cyan-500 text-white font-semibold"
                  data-testid="start-audit-btn"
                >
                  {isLoading ? (
                    <>
                      <RefreshCw className="w-5 h-5 mr-2 animate-spin" />
                      Analyzing...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-5 h-5 mr-2" />
                      Start Audit
                    </>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </section>

        {/* Progress Section */}
        {currentAudit?.status === "processing" && (
          <section className="mb-8" data-testid="progress-section">
            <Card className="bg-gradient-to-br from-teal-500/10 to-cyan-600/10 border-teal-500/20">
              <CardContent className="p-6">
                <div className="flex items-center gap-4 mb-4">
                  <div className="w-12 h-12 rounded-xl bg-teal-500/20 flex items-center justify-center">
                    <RefreshCw className="w-6 h-6 text-teal-400 animate-spin" />
                  </div>
                  <div className="flex-1">
                    <h3 className="text-lg font-semibold text-white">Analyzing {currentAudit.college_name}</h3>
                    <p className="text-white/60 text-sm">{currentAudit.progress_message}</p>
                  </div>
                  <span className="text-2xl font-bold text-teal-400">{currentAudit.progress}%</span>
                </div>
                <Progress value={currentAudit.progress} className="h-2 bg-white/10" />
              </CardContent>
            </Card>
          </section>
        )}

        {/* Results Section */}
        {currentAudit?.status === "completed" && currentAudit?.results?.length > 0 && (
          <section data-testid="results-section">
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <div className="flex items-center justify-between mb-6">
                <TabsList className="bg-white/5 border border-white/10">
                  <TabsTrigger value="overview" className="data-[state=active]:bg-teal-500/20 data-[state=active]:text-teal-400">
                    Overview
                  </TabsTrigger>
                  <TabsTrigger value="category" className="data-[state=active]:bg-teal-500/20 data-[state=active]:text-teal-400">
                    By Category
                  </TabsTrigger>
                  <TabsTrigger value="all" className="data-[state=active]:bg-teal-500/20 data-[state=active]:text-teal-400">
                    All KPIs
                  </TabsTrigger>
                </TabsList>
              </div>

              {/* Overview Tab */}
              <TabsContent value="overview">
                {/* Institute Intro Card */}
                {currentAudit.institute_info && (
                  <Card className="bg-gradient-to-br from-teal-500/10 to-cyan-600/10 border-teal-500/20 mb-8">
                    <CardContent className="p-6">
                      <div className="flex items-start gap-6">
                        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-teal-400 to-cyan-600 flex items-center justify-center flex-shrink-0">
                          <GraduationCap className="w-8 h-8 text-white" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-3 mb-2 flex-wrap">
                            <h2 className="text-2xl font-bold text-white font-['Space_Grotesk']">
                              {currentAudit.institute_info.full_name || currentAudit.college_name}
                            </h2>
                            {currentAudit.institute_info.short_name && (
                              <Badge className="bg-teal-500/20 text-teal-400 border-teal-500/30">
                                {currentAudit.institute_info.short_name}
                              </Badge>
                            )}
                            {currentAudit.institute_info.type && (
                              <Badge variant="outline" className="border-white/20 text-white/70">
                                {currentAudit.institute_info.type}
                              </Badge>
                            )}
                          </div>
                          
                          <div className="flex flex-wrap items-center gap-4 text-sm text-white/60">
                            {currentAudit.institute_info.location && (
                              <span className="flex items-center gap-1.5">
                                <Building2 className="w-4 h-4 text-teal-400" />
                                {currentAudit.institute_info.location}
                              </span>
                            )}
                            {currentAudit.institute_info.established && (
                              <span className="flex items-center gap-1.5">
                                <Clock className="w-4 h-4 text-cyan-400" />
                                Est. {currentAudit.institute_info.established}
                              </span>
                            )}
                            {currentAudit.institute_info.website && (
                              <a 
                                href={currentAudit.institute_info.website}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="flex items-center gap-1.5 text-teal-400 hover:text-teal-300 transition-colors"
                              >
                                <Globe className="w-4 h-4" />
                                Official Website
                                <ExternalLink className="w-3 h-3" />
                              </a>
                            )}
                            {currentAudit.institute_info.wikipedia_url && (
                              <a 
                                href={currentAudit.institute_info.wikipedia_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="flex items-center gap-1.5 text-cyan-400 hover:text-cyan-300 transition-colors"
                              >
                                <BookOpen className="w-4 h-4" />
                                Wikipedia
                                <ExternalLink className="w-3 h-3" />
                              </a>
                            )}
                          </div>
                          
                          {currentAudit.institute_info.motto && (
                            <p className="mt-3 text-sm text-white/50 italic">
                              "{currentAudit.institute_info.motto}"
                            </p>
                          )}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                )}

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
                  <Card className="bg-white/[0.02] border-white/5">
                    <CardContent className="p-6">
                      <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-xl bg-teal-500/20 flex items-center justify-center">
                          <CheckCircle className="w-6 h-6 text-teal-400" />
                        </div>
                        <div>
                          <p className="text-3xl font-bold text-white">{currentAudit.summary?.data_found || 0}</p>
                          <p className="text-white/50 text-sm">Data Found</p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                  
                  <Card className="bg-white/[0.02] border-white/5">
                    <CardContent className="p-6">
                      <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-xl bg-amber-500/20 flex items-center justify-center">
                          <AlertCircle className="w-6 h-6 text-amber-400" />
                        </div>
                        <div>
                          <p className="text-3xl font-bold text-white">{currentAudit.summary?.data_not_found || 0}</p>
                          <p className="text-white/50 text-sm">Not Found</p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                  
                  <Card className="bg-white/[0.02] border-white/5">
                    <CardContent className="p-6">
                      <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-xl bg-emerald-500/20 flex items-center justify-center">
                          <TrendingUp className="w-6 h-6 text-emerald-400" />
                        </div>
                        <div>
                          <p className="text-3xl font-bold text-white">{currentAudit.summary?.high_confidence || 0}</p>
                          <p className="text-white/50 text-sm">High Confidence</p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                  
                  <Card className="bg-white/[0.02] border-white/5">
                    <CardContent className="p-6">
                      <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-xl bg-cyan-500/20 flex items-center justify-center">
                          <Award className="w-6 h-6 text-cyan-400" />
                        </div>
                        <div>
                          <p className="text-3xl font-bold text-white">{currentAudit.summary?.coverage_percentage || 0}%</p>
                          <p className="text-white/50 text-sm">Coverage</p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                  
                  <Card className="bg-white/[0.02] border-white/5">
                    <CardContent className="p-6">
                      <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-xl bg-purple-500/20 flex items-center justify-center">
                          <Clock className="w-6 h-6 text-purple-400" />
                        </div>
                        <div>
                          <p className="text-3xl font-bold text-white">
                            {currentAudit.time_taken_seconds 
                              ? currentAudit.time_taken_seconds >= 60 
                                ? `${Math.floor(currentAudit.time_taken_seconds / 60)}m ${Math.round(currentAudit.time_taken_seconds % 60)}s`
                                : `${Math.round(currentAudit.time_taken_seconds)}s`
                              : "N/A"}
                          </p>
                          <p className="text-white/50 text-sm">Time Taken</p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </div>

                {/* Category Summary */}
                <Card className="bg-white/[0.02] border-white/5">
                  <CardHeader>
                    <CardTitle className="text-lg">Category Breakdown</CardTitle>
                    <CardDescription>Data coverage by category</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-4">
                      {Object.entries(currentAudit.summary?.categories || {}).map(([category, stats]) => {
                        const Icon = categoryIcons[category] || BookOpen;
                        const percentage = stats.total > 0 ? Math.round((stats.found / stats.total) * 100) : 0;
                        
                        return (
                          <div key={category} className="flex items-center gap-4">
                            <div className="w-10 h-10 rounded-lg bg-white/5 flex items-center justify-center">
                              <Icon className="w-5 h-5 text-teal-400" />
                            </div>
                            <div className="flex-1">
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-sm font-medium text-white/80">{category}</span>
                                <span className="text-sm text-white/50">{stats.found}/{stats.total}</span>
                              </div>
                              <Progress value={percentage} className="h-1.5 bg-white/10" />
                            </div>
                            <span className="text-sm font-medium text-teal-400 w-12 text-right">{percentage}%</span>
                          </div>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>

              {/* By Category Tab */}
              <TabsContent value="category">
                <Accordion type="multiple" className="space-y-4">
                  {Object.entries(groupedResults).map(([category, results]) => {
                    const Icon = categoryIcons[category] || BookOpen;
                    const foundCount = results.filter(r => !["data not found", "error", "processing error", "not available"].includes(String(r.value ?? '').toLowerCase())).length;
                    
                    return (
                      <AccordionItem key={category} value={category} className="border border-white/5 rounded-xl bg-white/[0.02] overflow-hidden">
                        <AccordionTrigger className="px-6 py-4 hover:no-underline hover:bg-white/5">
                          <div className="flex items-center gap-4">
                            <div className="w-10 h-10 rounded-lg bg-teal-500/20 flex items-center justify-center">
                              <Icon className="w-5 h-5 text-teal-400" />
                            </div>
                            <div className="text-left">
                              <h3 className="font-semibold text-white">{category}</h3>
                              <p className="text-sm text-white/50">{foundCount}/{results.length} KPIs with data</p>
                            </div>
                          </div>
                        </AccordionTrigger>
                        <AccordionContent>
                          <div className="px-6 pb-4 space-y-3">
                            {results.map((result, idx) => (
                              <KPICard key={idx} result={result} />
                            ))}
                          </div>
                        </AccordionContent>
                      </AccordionItem>
                    );
                  })}
                </Accordion>
              </TabsContent>

              {/* All KPIs Tab */}
              <TabsContent value="all">
                <Card className="bg-white/[0.02] border-white/5">
                  <CardContent className="p-0">
                    <ScrollArea className="h-[600px]">
                      <div className="p-4 space-y-3">
                        {currentAudit.results.map((result, idx) => (
                          <KPICard key={idx} result={result} showCategory />
                        ))}
                      </div>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </TabsContent>
            </Tabs>
          </section>
        )}

        {/* Recent Audits */}
        {recentAudits.length > 0 && !currentAudit && (
          <section data-testid="recent-audits">
            <h2 className="text-xl font-semibold mb-4 text-white/80">Recent Audits</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {recentAudits.map((audit) => (
                <Card 
                  key={audit.id} 
                  className="bg-white/[0.02] border-white/5 cursor-pointer hover:bg-white/[0.04] transition-colors"
                  onClick={() => loadAudit(audit.id)}
                  data-testid={`audit-card-${audit.id}`}
                >
                  <CardContent className="p-4">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="font-medium text-white truncate">{audit.college_name}</h3>
                      <Badge variant={audit.status === "completed" ? "default" : "secondary"} className="text-xs">
                        {audit.status}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-4 text-sm text-white/50">
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {new Date(audit.created_at).toLocaleDateString()}
                      </span>
                      {audit.summary?.coverage_percentage && (
                        <span className="flex items-center gap-1">
                          <TrendingUp className="w-3 h-3" />
                          {audit.summary.coverage_percentage}% coverage
                        </span>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </section>
        )}

        {/* Empty State */}
        {!currentAudit && recentAudits.length === 0 && (
          <section className="text-center py-16" data-testid="empty-state">
            <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-teal-500/20 to-cyan-600/20 flex items-center justify-center mx-auto mb-6">
              <GraduationCap className="w-10 h-10 text-teal-400" />
            </div>
            <h2 className="text-2xl font-semibold text-white mb-2">Start Your First Audit</h2>
            <p className="text-white/50 max-w-md mx-auto">
              Enter a college name above to analyze 75+ Key Performance Indicators across infrastructure, placements, research, and more.
            </p>
          </section>
        )}
      </main>
    </div>
  );
}

// Helper function to format KPI values for display
function formatValue(value) {
  if (value === null || value === undefined) {
    return "N/A";
  }
  if (typeof value === 'boolean') {
    return value ? "Yes" : "No";
  }
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (typeof value === 'object') {
    // Handle objects like {facilities: [], achievements: []}
    return Object.entries(value)
      .map(([key, val]) => {
        const formattedVal = Array.isArray(val) ? val.join(", ") : String(val);
        return `${key}: ${formattedVal}`;
      })
      .join(" | ");
  }
  return String(value);
}

// KPI Card Component
function KPICard({ result, showCategory = false }) {
  const isFound = !["data not found", "error", "processing error", "not available"].includes(String(result.value ?? '').toLowerCase());
  const displayValue = formatValue(result.value);
  
  return (
    <div className={`p-4 rounded-lg border ${isFound ? "bg-white/[0.02] border-white/10" : "bg-red-500/5 border-red-500/10"}`}>
      <div className="flex items-start justify-between gap-4 mb-2">
        <div className="flex-1">
          <h4 className="font-medium text-white text-sm">{result.kpi_name}</h4>
          {showCategory && (
            <p className="text-xs text-white/40 mt-0.5">{result.category}</p>
          )}
        </div>
        <Badge variant="outline" className={`text-xs ${confidenceColors[result.confidence] || confidenceColors.low}`}>
          {result.confidence}
        </Badge>
      </div>
      
      <div className={`text-lg font-semibold mb-2 ${isFound ? "text-teal-400" : "text-white/30"}`}>
        {displayValue}
      </div>
      
      {result.evidence_quote && result.evidence_quote !== "Not found in search results" && (
        <p className="text-xs text-white/50 line-clamp-2 mb-2">
          "{result.evidence_quote}"
        </p>
      )}
      
      {result.source_url && result.source_url !== "N/A" && result.source_url !== "Not Available" && (
        <a 
          href={result.source_url.startsWith("http") ? result.source_url : `https://${result.source_url}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-teal-400/70 hover:text-teal-400 flex items-center gap-1 truncate"
        >
          <ExternalLink className="w-3 h-3 flex-shrink-0" />
          {result.source_url}
        </a>
      )}
    </div>
  );
}

export default App;
