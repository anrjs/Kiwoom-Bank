import { ArrowLeft, TrendingDown } from "lucide-react";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

interface DeepAnalysisDashboardProps {
  onBack: () => void;
}

// 차트 1: 핵심 재무 지표 추이 데이터 (영업이익, 현금흐름)
const financialTrendData = [
  { quarter: "Q1 2024", profit: 6.5, cashflow: 8.2 },
  { quarter: "Q2 2024", profit: 6.8, cashflow: 7.9 },
  { quarter: "Q3 2024", profit: 5.5, cashflow: 6.5 },
  { quarter: "Q4 2024 (E)", profit: 5.0, cashflow: 6.0 },
];

// 차트 2: 뉴스 감성 분석 데이터 (부정 뉴스 급증)
const sentimentData = [
  { week: "1주", positive: 45, negative: 15, neutral: 40 },
  { week: "2주", positive: 40, negative: 20, neutral: 40 },
  { week: "3주", positive: 35, negative: 30, neutral: 35 },
  { week: "4주", positive: 25, negative: 45, neutral: 30 },
];

// 추가 차트 1: 부채 비율 추이
const debtRatioData = [
  { quarter: "Q1 2024", ratio: 42.1 },
  { quarter: "Q2 2024", ratio: 44.5 },
  { quarter: "Q3 2024", ratio: 48.3 },
  { quarter: "Q4 2024 (E)", ratio: 51.2 },
];

// 추가 차트 2: 시장 지배력 지수
const marketDominanceData = [
  { quarter: "Q1 2024", dominance: 85, competitorGap: 25 },
  { quarter: "Q2 2024", dominance: 82, competitorGap: 22 },
  { quarter: "Q3 2024", dominance: 78, competitorGap: 18 },
  { quarter: "Q4 2024 (E)", dominance: 75, competitorGap: 15 },
];

export function DeepAnalysisDashboard({ onBack }: DeepAnalysisDashboardProps) {
  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-blue-900 flex items-center justify-center">
              <span className="text-white tracking-tight">ACI</span>
            </div>
            <span className="text-slate-900">AI Credit Insight</span>
          </div>
          <Button onClick={onBack} variant="ghost" className="text-slate-600">
            <ArrowLeft className="w-4 h-4 mr-2" />
            돌아가기
          </Button>
        </div>
      </header>

      {/* Page Header */}
      <div className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-slate-900 mb-2">삼성전자 심층 분석 대시보드</h1>
              <p className="text-slate-600">
                데이터 시각화 기반 등급 하락 원인 분석
              </p>
            </div>
            <Badge className="bg-red-100 text-red-700 border-red-200 px-4 py-2">
              <TrendingDown className="w-4 h-4 mr-2" />
              등급 하락: AAA → AA
            </Badge>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        {/* 차트 1: 핵심 지표 변동성 시각화 (라인 차트) */}
        <Card className="shadow-md hover:shadow-lg transition-shadow">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2">
              <span>📉</span>
              <span>핵심 지표 변동성 시각화</span>
            </CardTitle>
            <p className="text-slate-600 mt-2">
              영업이익과 현금흐름의 급락 추이 (단위: 조원)
            </p>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={350}>
              <LineChart data={financialTrendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="quarter" tick={{ fill: "#64748b" }} />
                <YAxis tick={{ fill: "#64748b" }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#ffffff",
                    border: "1px solid #e2e8f0",
                    borderRadius: "8px",
                  }}
                />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="profit"
                  stroke="#dc2626"
                  strokeWidth={3}
                  name="영업이익"
                  dot={{ fill: "#dc2626", r: 6 }}
                />
                <Line
                  type="monotone"
                  dataKey="cashflow"
                  stroke="#f59e0b"
                  strokeWidth={3}
                  name="영업현금흐름"
                  dot={{ fill: "#f59e0b", r: 6 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* 차트 2: 비재무 위험 분석 (감성 분석 차트) */}
        <Card className="shadow-md hover:shadow-lg transition-shadow">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2">
              <span>📰</span>
              <span>비재무 위험 분석 (뉴스 감성 분석)</span>
            </CardTitle>
            <p className="text-slate-600 mt-2">
              최근 4주간 부정적인 뉴스 급증 추이
            </p>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={350}>
              <BarChart data={sentimentData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="week" tick={{ fill: "#64748b" }} />
                <YAxis tick={{ fill: "#64748b" }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#ffffff",
                    border: "1px solid #e2e8f0",
                    borderRadius: "8px",
                  }}
                />
                <Legend />
                <Bar
                  dataKey="positive"
                  fill="#16a34a"
                  name="긍정"
                  radius={[8, 8, 0, 0]}
                />
                <Bar
                  dataKey="neutral"
                  fill="#64748b"
                  name="중립"
                  radius={[8, 8, 0, 0]}
                />
                <Bar
                  dataKey="negative"
                  fill="#dc2626"
                  name="부정"
                  radius={[8, 8, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* 추가 차트들 (Grid) */}
        <div className="grid grid-cols-2 gap-6">
          {/* 추가 차트 1: 부채 비율 추이 */}
          <Card className="shadow-md hover:shadow-lg transition-shadow">
            <CardHeader className="pb-4">
              <CardTitle className="flex items-center gap-2">
                <span>💰</span>
                <span>부채 비율 추이</span>
              </CardTitle>
              <p className="text-slate-600 mt-2">
                부채 비율 증가로 재무 안정성 약화 (단위: %)
              </p>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={debtRatioData}>
                  <defs>
                    <linearGradient id="colorRatio" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#dc2626" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#dc2626" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="quarter" tick={{ fill: "#64748b" }} />
                  <YAxis tick={{ fill: "#64748b" }} domain={[40, 55]} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#ffffff",
                      border: "1px solid #e2e8f0",
                      borderRadius: "8px",
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="ratio"
                    stroke="#dc2626"
                    strokeWidth={3}
                    fillOpacity={1}
                    fill="url(#colorRatio)"
                    name="부채비율 (%)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* 추가 차트 2: 시장 지배력 지수 */}
          <Card className="shadow-md hover:shadow-lg transition-shadow">
            <CardHeader className="pb-4">
              <CardTitle className="flex items-center gap-2">
                <span>🎯</span>
                <span>시장 지배력 분석</span>
              </CardTitle>
              <p className="text-slate-600 mt-2">
                경쟁사 대비 기술 격차 축소 추세
              </p>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={marketDominanceData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="quarter" tick={{ fill: "#64748b" }} />
                  <YAxis tick={{ fill: "#64748b" }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#ffffff",
                      border: "1px solid #e2e8f0",
                      borderRadius: "8px",
                    }}
                  />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="dominance"
                    stroke="#1e3a8a"
                    strokeWidth={3}
                    name="시장 지배력"
                    dot={{ fill: "#1e3a8a", r: 5 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="competitorGap"
                    stroke="#f59e0b"
                    strokeWidth={3}
                    name="경쟁사 격차"
                    dot={{ fill: "#f59e0b", r: 5 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>

        {/* 위험 지표 요약 */}
        <Card className="shadow-md">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>⚠️</span>
              <span>위험 지표 요약</span>
            </CardTitle>
            <p className="text-slate-600 mt-2">
              주요 재무 지표 및 시장 신뢰도 현황
            </p>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-4 gap-5">
              <div className="p-6 bg-red-50 rounded-xl border-2 border-red-200 hover:shadow-md transition-shadow">
                <div className="text-red-600 mb-2">영업이익률</div>
                <div className="text-red-900">7.6%</div>
                <div className="text-red-700 mt-2">-2.1%p ↓</div>
              </div>
              <div className="p-6 bg-red-50 rounded-xl border-2 border-red-200 hover:shadow-md transition-shadow">
                <div className="text-red-600 mb-2">부채비율</div>
                <div className="text-red-900">48.3%</div>
                <div className="text-red-700 mt-2">+3.1%p ↑</div>
              </div>
              <div className="p-6 bg-yellow-50 rounded-xl border-2 border-yellow-300 hover:shadow-md transition-shadow">
                <div className="text-yellow-700 mb-2">유동비율</div>
                <div className="text-yellow-900">198.5%</div>
                <div className="text-yellow-700 mt-2">-16.8%p ↓</div>
              </div>
              <div className="p-6 bg-red-50 rounded-xl border-2 border-red-200 hover:shadow-md transition-shadow">
                <div className="text-red-600 mb-2">시장 신뢰도</div>
                <div className="text-red-900">중간</div>
                <div className="text-red-700 mt-2">하락 추세 ↓</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
