import { ArrowLeft, Home, AlertTriangle, TrendingDown } from "lucide-react";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import kiwoomLogo from "figma:asset/7edd7880e1ed1575f3f3496ccc95c4ca1ab02475.png";

interface NotificationDetailProps {
  onBack: () => void;
  onHome: () => void;
  onViewAnalysis: () => void;
}

export function NotificationDetail({
  onBack,
  onHome,
  onViewAnalysis,
}: NotificationDetailProps) {
  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
            {/* Kiwoom Logo */}
            <div className="flex items-center gap-2">
              <div className="w-10 h-10 flex items-center justify-center">
                <img src={kiwoomLogo} alt="Kiwoom Logo" className="w-full h-full object-contain" />
              </div>
              <span className="text-slate-700">키움은행</span>
            </div>
            
            {/* Divider */}
            <div className="h-8 w-px bg-slate-300"></div>
            
            {/* ACI Logo */}
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#AD1765] to-[#8B1252] flex items-center justify-center">
                <span className="text-white tracking-tight">ACI</span>
              </div>
              <span className="text-slate-900">AI Credit Insight</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={onHome} variant="ghost" className="text-slate-600">
              <Home className="w-4 h-4 mr-2" />
              처음으로
            </Button>
            <Button onClick={onBack} variant="ghost" className="text-slate-600">
              <ArrowLeft className="w-4 h-4 mr-2" />
              뒤로가기
            </Button>
          </div>
        </div>
      </header>

      {/* Content */}
      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* Page Header - 페이지 제목 섹션 */}
        <div className="mb-8">
          {/* 위험 태그 */}
          <Badge className="mb-4 bg-red-600 text-white border-red-600 px-4 py-2 shadow-md">
            <AlertTriangle className="w-4 h-4 mr-2" />
            위험
          </Badge>

          {/* 메인 타이틀 */}
          <h1 className="text-slate-900 mb-3">삼성전자 등급 조정</h1>

          {/* 서브 타이틀 - 등급 변화 */}
          <div className="flex items-center gap-3">
            <div className="bg-[#AD1765]/10 text-[#AD1765] px-4 py-2 rounded-lg border border-[#AD1765]/30">
              AAA
            </div>
            <TrendingDown className="w-6 h-6 text-red-600" />
            <div className="bg-red-100 text-red-900 px-4 py-2 rounded-lg border border-red-300">
              AA
            </div>
          </div>
        </div>

        <div className="space-y-6">
          {/* 카드 1: 핵심 경고 메시지 */}
          <Card className="border-red-300 shadow-lg">
            <CardHeader className="bg-red-50 border-b border-red-200">
              <CardTitle className="text-red-900 flex items-center gap-2">
                <AlertTriangle className="w-5 h-5" />
                핵심 경고 메시지
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-6 pb-6">
              <p className="text-slate-900 leading-relaxed">
                삼성전자의 신용등급이{" "}
                <strong className="text-red-700">AAA에서 AA로 하향 조정</strong>
                되었습니다. 3분기 실적 악화와 반도체 시장의 불확실성 증가가 주요
                원인으로 분석되었습니다. 향후 추가 하락 가능성에 대한 면밀한
                모니터링이 필요합니다.
              </p>
            </CardContent>
          </Card>

          {/* 카드 2: 관련 근거 데이터 */}
          <Card className="shadow-lg">
            <CardHeader className="bg-slate-50 border-b border-slate-200">
              <CardTitle className="text-slate-900 flex items-center gap-2">
                📊 관련 근거 데이터
              </CardTitle>
              <p className="text-slate-600 mt-2">
                등급 변경을 뒷받침하는 핵심 데이터와 근거
              </p>
            </CardHeader>
            <CardContent className="pt-6 pb-6">
              {/* 재무 데이터 섹션 */}
              <div className="mb-6">
                <h3 className="text-slate-900 mb-4">재무 데이터</h3>
                <div className="space-y-3">
                  <Card className="bg-red-50 border-red-200 hover:shadow-md transition-shadow">
                    <CardContent className="pt-4 pb-4 px-5">
                      <div className="flex items-center justify-between">
                        <span className="text-slate-900">3분기 영업이익</span>
                        <span className="text-red-700">전년 대비 -15%</span>
                      </div>
                    </CardContent>
                  </Card>
                  <Card className="bg-red-50 border-red-200 hover:shadow-md transition-shadow">
                    <CardContent className="pt-4 pb-4 px-5">
                      <div className="flex items-center justify-between">
                        <span className="text-slate-900">메모리 반도체 가격</span>
                        <span className="text-red-700">전분기 대비 -8%</span>
                      </div>
                    </CardContent>
                  </Card>
                  <Card className="bg-red-50 border-red-200 hover:shadow-md transition-shadow">
                    <CardContent className="pt-4 pb-4 px-5">
                      <div className="flex items-center justify-between">
                        <span className="text-slate-900">영업현금흐름</span>
                        <span className="text-red-700">전년 대비 -12%</span>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </div>

              {/* 비재무 데이터 섹션 */}
              <div>
                <h3 className="text-slate-900 mb-4">비재무 데이터 (뉴스 분석)</h3>
                <Card className="bg-yellow-50 border-yellow-200">
                  <CardContent className="pt-4 pb-4 px-5">
                    <div className="flex items-center justify-between mb-4">
                      <span className="text-slate-900">부정 뉴스 증가율</span>
                      <span className="text-orange-700">+35%</span>
                    </div>
                    <div className="space-y-3 pt-3 border-t border-yellow-300">
                      <div className="pl-4 border-l-2 border-orange-400">
                        <p className="text-slate-800">
                          "삼성전자, 3분기 실적 시장 기대치 하회"
                        </p>
                        <p className="text-slate-500 mt-1">
                          한국경제 | 2025.10.10
                        </p>
                      </div>
                      <div className="pl-4 border-l-2 border-orange-400">
                        <p className="text-slate-800">
                          "메모리 반도체 가격 하락세 지속 전망"
                        </p>
                        <p className="text-slate-500 mt-1">
                          매일경제 | 2025.10.09
                        </p>
                      </div>
                      <div className="pl-4 border-l-2 border-orange-400">
                        <p className="text-slate-800">
                          "반도체 업황 불확실성 증가, 수익성 악화 우려"
                        </p>
                        <p className="text-slate-500 mt-1">
                          조선일보 | 2025.10.08
                        </p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </CardContent>
          </Card>

          {/* CTA Button - 행동 유도 버튼 */}
          <Button
            onClick={onViewAnalysis}
            className="w-full bg-blue-900 hover:bg-blue-800 text-white py-7 shadow-lg hover:shadow-xl transition-all"
          >
            📈 상세 분석 대시보드 보기
          </Button>
        </div>
      </div>
    </div>
  );
}
