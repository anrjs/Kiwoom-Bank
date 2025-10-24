import { useState } from "react";
import { ArrowLeft, TrendingUp, TrendingDown } from "lucide-react";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "./ui/table";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface CompanyAnalysisProps {
  companyName: string;
  onBack: () => void;
}

// Mock 재무 데이터
const financialData = [
  {
    category: "매출액",
    q1: "71.9조원",
    q2: "74.1조원",
    q3: "67.4조원",
    change: "-9.0%",
    description: "전년 동기 대비",
  },
  {
    category: "영업이익",
    q1: "6.5조원",
    q2: "6.8조원",
    q3: "5.5조원",
    change: "-15.2%",
    description: "전년 동기 대비",
  },
  {
    category: "당기순이익",
    q1: "5.9조원",
    q2: "6.1조원",
    q3: "4.8조원",
    change: "-18.5%",
    description: "전년 동기 대비",
  },
  {
    category: "영업이익률",
    q1: "9.0%",
    q2: "9.2%",
    q3: "8.2%",
    change: "-0.8%p",
    description: "전년 동기 대비 포인트",
  },
];

// Mock 주가 데이터
const stockData = [
  { month: "1월", price: 72000 },
  { month: "2월", price: 74500 },
  { month: "3월", price: 71200 },
  { month: "4월", price: 68900 },
  { month: "5월", price: 70100 },
  { month: "6월", price: 67800 },
];

// Mock 뉴스 데이터
const newsData = [
  {
    title: "삼성전자, 3분기 실적 시장 기대치 하회",
    source: "한국경제",
    date: "2025.10.10",
    sentiment: "negative",
  },
  {
    title: "메모리 반도체 가격 하락세 지속 전망",
    source: "매일경제",
    date: "2025.10.09",
    sentiment: "negative",
  },
  {
    title: "반도체 업황 불확실성 증가, 수익성 악화 우려",
    source: "조선일보",
    date: "2025.10.08",
    sentiment: "negative",
  },
  {
    title: "삼성전자, AI 반도체 개발 박차",
    source: "전자신문",
    date: "2025.10.07",
    sentiment: "positive",
  },
  {
    title: "글로벌 반도체 시장 회복 조짐",
    source: "디지털타임스",
    date: "2025.10.05",
    sentiment: "positive",
  },
];

export function CompanyAnalysis({ companyName, onBack }: CompanyAnalysisProps) {
  const [activeTab, setActiveTab] = useState("financial");

  const getSentimentColor = (sentiment: string) => {
    return sentiment === "positive" ? "text-green-600" : "text-red-600";
  };

  const getSentimentBadge = (sentiment: string) => {
    return sentiment === "positive" ? (
      <Badge className="bg-green-50 text-green-700 border-green-200">
        긍정
      </Badge>
    ) : (
      <Badge className="bg-red-50 text-red-700 border-red-200">부정</Badge>
    );
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
          <Button onClick={onBack} variant="ghost" className="text-slate-600">
            <ArrowLeft className="w-4 h-4 mr-2" />
            돌아가기
          </Button>
        </div>
      </header>

      {/* Company Info Header */}
      <div className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <h1 className="text-slate-900 mb-6">{companyName}</h1>

          {/* Credit Ratings - 공개신용등급과 ACI등급 구분 */}
          <div className="grid grid-cols-2 gap-6">
            {/* ACI 자체 등급 (핵심 지표) */}
            <Card className="border-2 border-blue-900 shadow-lg bg-gradient-to-br from-blue-50 to-white">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2">
                  <span className="text-blue-900">🎯 ACI 신용등급</span>
                  <Badge className="bg-blue-900 text-white">핵심 지표</Badge>
                </CardTitle>
                <p className="text-slate-600 mt-1">
                  AI 기반 실시간 분석 등급
                </p>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-3 mb-2">
                      <Badge className="px-4 py-2 bg-blue-900 text-white">
                        AA
                      </Badge>
                      <div className="flex items-center gap-2 text-red-600">
                        <TrendingDown className="w-5 h-5" />
                        <span>하락</span>
                      </div>
                    </div>
                    <p className="text-slate-600">최근 변동: AAA → AA</p>
                  </div>
                  <div className="text-right">
                    <div className="text-slate-600 mb-1">신뢰도</div>
                    <div className="text-blue-900">높음 (92%)</div>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* 공개 신용등급 (공식 등급) */}
            <Card className="border-2 border-slate-300 shadow-md">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2">
                  <span className="text-slate-900">📋 공개 신용등급</span>
                  <Badge variant="outline" className="bg-slate-100 text-slate-700">
                    공식 등급
                  </Badge>
                </CardTitle>
                <p className="text-slate-600 mt-1">
                  국가 공인 신용평가기관 등급
                </p>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-3 mb-2">
                      <Badge
                        variant="outline"
                        className="px-4 py-2 bg-slate-100 text-slate-900 border-slate-300"
                      >
                        AAA
                      </Badge>
                      <div className="flex items-center gap-2 text-slate-600">
                        <span>안정적</span>
                      </div>
                    </div>
                    <p className="text-slate-600">평가사: 한국신용평가</p>
                  </div>
                  <div className="text-right">
                    <div className="text-slate-600 mb-1">전망</div>
                    <div className="text-slate-900">안정적</div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* 등급 차이 설명 */}
          <Card className="mt-4 bg-blue-50 border-blue-200">
            <CardContent className="pt-4 pb-4 px-5">
              <p className="text-slate-700 leading-relaxed">
                <strong className="text-blue-900">ACI 신용등급</strong>은 AI
                기반 실시간 데이터 분석을 통해 빠르게 위험을 감지하며,{" "}
                <strong className="text-slate-700">공개 신용등급</strong>은
                보수적인 기준으로 평가된 공식 등급입니다. ACI 등급의 변화는
                위험 조기 경보 신호로 활용하실 수 있습니다.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Tabs Content */}
      <div className="max-w-7xl mx-auto px-6 py-8">
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="grid w-full grid-cols-3 mb-6">
            <TabsTrigger
              value="financial"
              className="data-[state=active]:bg-blue-900 data-[state=active]:text-white"
            >
              재무제표
            </TabsTrigger>
            <TabsTrigger
              value="stock"
              className="data-[state=active]:bg-blue-900 data-[state=active]:text-white"
            >
              주가 변동 추이
            </TabsTrigger>
            <TabsTrigger
              value="news"
              className="data-[state=active]:bg-blue-900 data-[state=active]:text-white"
            >
              관련 뉴스
            </TabsTrigger>
          </TabsList>

          {/* 재무제표 탭 */}
          <TabsContent value="financial">
            <Card>
              <CardHeader>
                <CardTitle>2024년 분기별 재무제표</CardTitle>
                <p className="text-slate-600 mt-2">
                  주요 재무 지표 및 전년 동기 대비 증감률
                </p>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>항목</TableHead>
                      <TableHead className="text-right">1분기</TableHead>
                      <TableHead className="text-right">2분기</TableHead>
                      <TableHead className="text-right">3분기</TableHead>
                      <TableHead className="text-right">
                        전년 동기 대비 변화율
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {financialData.map((item) => (
                      <TableRow key={item.category}>
                        <TableCell>
                          <span className="text-slate-900">{item.category}</span>
                        </TableCell>
                        <TableCell className="text-right text-slate-900">
                          {item.q1}
                        </TableCell>
                        <TableCell className="text-right text-slate-900">
                          {item.q2}
                        </TableCell>
                        <TableCell className="text-right text-slate-900">
                          {item.q3}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex flex-col items-end gap-1">
                            <span
                              className={
                                item.change.startsWith("-")
                                  ? "text-red-600"
                                  : "text-green-600"
                              }
                            >
                              {item.change}
                            </span>
                            <span className="text-slate-500">
                              ({item.description})
                            </span>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                {/* 지표 설명 추가 */}
                <div className="mt-6 p-4 bg-slate-50 rounded-lg border border-slate-200">
                  <h4 className="text-slate-900 mb-3">지표 설명</h4>
                  <div className="space-y-2 text-slate-700">
                    <p>
                      • <strong>영업이익률</strong>: 매출액 대비 영업이익의
                      비율 (영업이익 ÷ 매출액 × 100)
                    </p>
                    <p>
                      • <strong>전년 동기 대비</strong>: 작년 같은 분기와
                      비교한 증감률
                    </p>
                    <p>
                      • <strong>%p (퍼센트 포인트)</strong>: 비율의 차이를
                      나타내는 단위 (예: 9.2% → 8.2% = -1.0%p)
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* 주가 변동 추이 탭 */}
          <TabsContent value="stock">
            <Card>
              <CardHeader>
                <CardTitle>최근 6개월 주가 추이</CardTitle>
                <p className="text-slate-600 mt-2">단위: 원</p>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={400}>
                  <LineChart data={stockData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="month" tick={{ fill: "#64748b" }} />
                    <YAxis
                      tick={{ fill: "#64748b" }}
                      domain={[65000, 76000]}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#ffffff",
                        border: "1px solid #e2e8f0",
                        borderRadius: "8px",
                      }}
                    />
                    <Line
                      type="monotone"
                      dataKey="price"
                      stroke="#1e3a8a"
                      strokeWidth={3}
                      dot={{ fill: "#1e3a8a", r: 5 }}
                    />
                  </LineChart>
                </ResponsiveContainer>

                <div className="grid grid-cols-3 gap-4 mt-6">
                  <Card className="bg-slate-50">
                    <CardContent className="pt-4 pb-4">
                      <div className="text-slate-600 mb-1">현재가</div>
                      <div className="text-slate-900">67,800원</div>
                    </CardContent>
                  </Card>
                  <Card className="bg-red-50">
                    <CardContent className="pt-4 pb-4">
                      <div className="text-red-600 mb-1">전일 대비</div>
                      <div className="text-red-900 flex items-center gap-1">
                        <TrendingDown className="w-4 h-4" />
                        -1,200원 (-1.7%)
                      </div>
                    </CardContent>
                  </Card>
                  <Card className="bg-slate-50">
                    <CardContent className="pt-4 pb-4">
                      <div className="text-slate-600 mb-1">거래량</div>
                      <div className="text-slate-900">12.5M</div>
                    </CardContent>
                  </Card>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* 관련 뉴스 탭 */}
          <TabsContent value="news">
            <Card>
              <CardHeader>
                <CardTitle>최근 관련 뉴스</CardTitle>
                <p className="text-slate-600 mt-2">
                  AI 기반 감성 분석 결과 포함
                </p>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {newsData.map((news, index) => (
                    <Card
                      key={index}
                      className="hover:shadow-md transition-shadow"
                    >
                      <CardContent className="pt-5 pb-5 px-6">
                        <div className="flex items-start justify-between mb-3">
                          <h4 className="text-slate-900 flex-1">
                            {news.title}
                          </h4>
                          {getSentimentBadge(news.sentiment)}
                        </div>
                        <div className="flex items-center justify-between text-slate-600">
                          <span>{news.source}</span>
                          <span>{news.date}</span>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>

                {/* 뉴스 감성 분석 요약 */}
                <Card className="mt-6 bg-slate-50 border-slate-300">
                  <CardContent className="pt-5 pb-5 px-6">
                    <h4 className="text-slate-900 mb-3">뉴스 감성 분석 요약</h4>
                    <div className="grid grid-cols-3 gap-4">
                      <div className="text-center">
                        <div className="text-slate-600 mb-1">전체 뉴스</div>
                        <div className="text-slate-900">{newsData.length}건</div>
                      </div>
                      <div className="text-center">
                        <div className="text-green-600 mb-1">긍정</div>
                        <div className="text-green-900">
                          {newsData.filter((n) => n.sentiment === "positive").length}건
                        </div>
                      </div>
                      <div className="text-center">
                        <div className="text-red-600 mb-1">부정</div>
                        <div className="text-red-900">
                          {newsData.filter((n) => n.sentiment === "negative").length}건
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
