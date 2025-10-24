import { useState } from "react";
import { Search, Building2, Bell } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Badge } from "./ui/badge";

interface MainDashboardProps {
  onSearchCompany: (companyName: string) => void;
  onViewMyList: () => void;
  onViewNotifications: () => void;
  unreadCount: number;
}

export function MainDashboard({ 
  onSearchCompany, 
  onViewMyList, 
  onViewNotifications,
  unreadCount 
}: MainDashboardProps) {
  const [searchQuery, setSearchQuery] = useState("");

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      onSearchCompany(searchQuery);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg kb-burgundy flex items-center justify-center">
              <span className="text-white font-semibold tracking-tight">KB</span>
            </div>
            <span className="text-slate-900 font-medium">Kiwoom-Bank</span>
          </div>
          <div className="flex items-center gap-3">
            <Button
              onClick={onViewNotifications}
              variant="outline"
              className="border-blue-900 text-blue-900 hover:bg-blue-50 relative"
            >
              <Bell className="w-4 h-4 mr-2" />
              알림함
              {unreadCount > 0 && (
                <Badge className="absolute -top-2 -right-2 bg-red-600 text-white px-2 py-0.5 min-w-[1.25rem] h-5 flex items-center justify-center">
                  {unreadCount}
                </Badge>
              )}
            </Button>
            <Button
              onClick={onViewMyList}
              variant="outline"
              className="border-blue-900 text-blue-900 hover:bg-blue-50"
            >
              <Building2 className="w-4 h-4 mr-2" />
              관리 기업 목록
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="max-w-4xl mx-auto px-6 pt-32">
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
              placeholder="분석할 기업명을 입력하세요..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full h-16 pl-16 pr-6 bg-white border-slate-300 shadow-lg rounded-2xl"
            />
          </div>
          <Button
            type="submit"
            className="absolute right-2 top-1/2 -translate-y-1/2 bg-blue-900 hover:bg-blue-800 px-8 h-12"
          >
            검색
          </Button>
        </form>

      </div>
    </div>
  );
}
