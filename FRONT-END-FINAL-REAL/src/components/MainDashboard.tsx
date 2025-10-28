// MainDashboard.tsx
import { useState } from "react"; // ❗️ useEffect, useRef, useCallback 제거
import { Search, Building2, Bell, Plus, CheckCircle2, Building } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Badge } from "./ui/badge";
import { Card } from "./ui/card";
import { allCompanies, CompanyData } from "./companyDatabase";
import kiwoomLogo from "figma:asset/7edd7880e1ed1575f3f3496ccc95c4ca1ab02475.png";
// import axios from "axios"; // ❗️ 제거

// ❗️ 모든 API, WATCHLIST, POLL_MS, getRatingOrder, showBrowserNotification, AnalyzeManyItem 관련 코드 제거

interface Company {
  name: string;
  rating: string;
  loanAmount: number;
  interestRate: number;
  delinquency: string;
  collateral: string;
  rm: string;
  ratingChange: string;
}

// ❗️ Notification 인터페이스 제거 (App.tsx가 관리)

interface MainDashboardProps {
  onSearchCompany: (companyName: string) => void;
  onViewMyList: () => void;
  onViewNotifications: () => void;
  unreadCount: number; // ❗️ 이 prop을 받아서 사용
  onAddToMyCompanies: (companyName: string) => void;
  myCompanies: Company[];
}

export function MainDashboard({ 
  onSearchCompany, 
  onViewMyList, 
  onViewNotifications,
  unreadCount, // ❗️ props로 받음
  onAddToMyCompanies,
  myCompanies
}: MainDashboardProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<CompanyData[]>([]);

  // ❗️ 모든 prevGradesRef, pollingRef, fetchCurrentGrades, 폴링 useEffect 로직 제거

  // 🔎 기존 검색 로직 (유지)
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      const filteredCompanies = allCompanies.filter((company) =>
        company.name.toLowerCase().includes(searchQuery.toLowerCase())
      );
      setSearchResults(filteredCompanies);
    }
  };

  const handleViewDetail = (companyName: string) => {
    onSearchCompany(companyName);
  };

  const handleAddCompany = (companyName: string) => {
    onAddToMyCompanies(companyName);
  };

  const isAlreadyAdded = (companyName: string) => {
    return myCompanies.some((company) => company.name === companyName);
  };

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header (유지) */}
      <header className="bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
            {/* ... (로고 등 UI 유지) ... */}
            <div className="flex items-center gap-2">
              <div className="w-10 h-10 flex items-center justify-center">
                <img src={kiwoomLogo} alt="Kiwoom Logo" className="w-full h-full object-contain" />
              </div>
              <span className="text-slate-700">키움은행</span>
            </div>
            
            <div className="h-8 w-px bg-slate-300"></div>
            
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#AD1765] to-[#8B1252] flex items-center justify-center">
                <span className="text-white tracking-tight">ACI</span>
              </div>
              <span className="text-slate-900">AI Credit Insight</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Button
              onClick={onViewNotifications}
              variant="outline"
              className="border-[#AD1765] text-[#AD1765] hover:bg-[#AD1765]/10 relative"
            >
              <Bell className="w-4 h-4 mr-2" />
              알림함
              {/* ❗️ props로 받은 unreadCount 사용 */}
              {unreadCount > 0 && ( 
                <Badge className="absolute -top-2 -right-2 bg-red-600 text-white px-2 py-0.5 min-w-[1.25rem] h-5 flex items-center justify-center">
                  {unreadCount}
                </Badge>
              )}
            </Button>
            <Button
              onClick={onViewMyList}
              variant="outline"
              className="border-[#AD1765] text-[#AD1765] hover:bg-[#AD1765]/10"
            >
              <Building2 className="w-4 h-4 mr-2" />
              관리 기업 목록
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content (유지) */}
      <div className="max-w-4xl mx-auto px-6 pt-32">
        {/* ... (검색 폼 및 검색 결과 UI 모두 유지) ... */}
        <div className="text-center mb-12">
          <h1 className="text-slate-900 mb-4">
            기업 신용등급을 분석하세요
          </h1>
          <p className="text-slate-600">
            AI 기반 실시간 신용등급 분석 및 모니터링 서비스
          </p>
        </div>

        <form onSubmit={handleSearch} className="relative">
          <div className="relative">
            <Search className="absolute left-6 top-1/2 -translate-y-1/2 text-slate-400 w-6 h-6" />
            <Input
              type="text"
              placeholder="분석할 기업명을 입력하세요."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full h-16 pl-16 pr-6 bg-white border-slate-300 shadow-lg rounded-2xl"
            />
          </div>
          <Button
            type="submit"
            className="absolute right-2 top-1/2 -translate-y-1/2 bg-gradient-to-r from-[#AD1765] to-[#8B1252] hover:from-[#8B1252] hover:to-[#6E0E42] px-8 h-12"
          >
            검색
          </Button>
        </form>

        {searchResults.length > 0 && (
          <div className="mt-8">
            <div className="flex items-center gap-2 mb-4">
              <Building className="w-5 h-5 text-slate-600" />
              <h3 className="text-slate-900">
                검색 결과 <span className="text-[#AD1765]">{searchResults.length}</span>개 기업
              </h3>
            </div>
            <div className="grid gap-4">
              {searchResults.map((company) => (
                <Card key={company.name} className="p-6 shadow-lg hover:shadow-xl transition-shadow">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-2">
                        <h3 className="text-slate-900">{company.name}</h3>
                        <Badge className="bg-[#AD1765]/10 text-[#AD1765] border-[#AD1765]/20">
                          {company.rating}
                        </Badge>
                        <Badge variant="outline" className="text-slate-600">
                          {company.industry}
                        </Badge>
                      </div>
                      <p className="text-slate-600 mb-4">
                        {company.description}
                      </p>
                      <div className="flex gap-3">
                        <Button
                          onClick={() => handleViewDetail(company.name)}
                          className="bg-gradient-to-r from-[#AD1765] to-[#8B1252] hover:from-[#8B1252] hover:to-[#6E0E42]"
                        >
                          <Search className="w-4 h-4 mr-2" />
                          ACI신용등급 확인
                        </Button>
                        {isAlreadyAdded(company.name) ? (
                          <Button
                            variant="outline"
                            className="border-green-600 text-green-700 hover:bg-green-50"
                            disabled
                          >
                            <CheckCircle2 className="w-4 h-4 mr-2" />
                            관심기업 목록에 추가됨
                          </Button>
                        ) : (
                          <Button
                            onClick={() => handleAddCompany(company.name)}
                            variant="outline"
                            className="border-[#AD1765] text-[#AD1765] hover:bg-[#AD1765]/10"
                          >
                            <Plus className="w-4 h-4 mr-2" />
                            관심기업 목록에 추가
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          </div>
        )}

        {searchQuery && searchResults.length === 0 && searchQuery.trim() !== "" && (
          <Card className="mt-8 p-8 text-center shadow-lg">
            <Building className="w-12 h-12 text-slate-400 mx-auto mb-4" />
            <h3 className="text-slate-900 mb-2">검색 결과가 없습니다</h3>
            <p className="text-slate-600">
              '{searchQuery}'에 대한 기업을 찾을 수 없습니다.<br />
              다른 검색어로 시도해보세요.
            </p>
          </Card>
        )}

      </div>
    </div>
  );
}