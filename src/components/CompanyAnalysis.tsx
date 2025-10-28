import { useState, useEffect } from "react";
import { ArrowLeft, Home, TrendingUp, TrendingDown } from "lucide-react";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import axios from "axios";

// ✅ 실제 파일 경로
import kiwoomLogo from "./kiwoomLogo.png";

/* ------------------------------------------------------------------
  (A) 공통 상수/유틸
------------------------------------------------------------------- */
const API_BASE =
  (import.meta as any)?.env?.VITE_API_BASE_URL || "http://localhost:8000";

const toPercentage = (val: unknown): string => {
  const num = Number(val);
  if (Number.isNaN(num) || !isFinite(num)) return "-";
  return `${(num * 100).toFixed(2)}%`;
};

const isLikelyUrl = (s?: string) => !!s && /^https?:\/\/\S+$/i.test(s.trim());
const toHost = (url?: string) => {
  try {
    if (!url) return "-";
    const u = new URL(url);
    return u.host || url;
  } catch {
    return url || "-";
  }
};

// 백엔드 응답 타입(필요 최소)
type YearRatios = {
  debtRatio: string;
  currentRatio: string;
  quickRatio: string;
  roa: string;
  assetGrowthRate: string;
  cfoToDebt: string;
};
type MetricsRow = {
  stock_code: string;
  debt_ratio: number | null;
  roa: number | null;
  total_asset_growth_rate: number | null;
  cfo_to_total_debt: number | null;
  current_ratio: number | null;
  quick_ratio: number | null;
};
type MetricsResp = { data: MetricsRow[] };
type CreditResp = { ratings: Record<string, string> };
type NewsItem = {
  title: string;
  link: string;
  press: string;
  published_at: string;
  summary?: string;
  sentiment?: "positive" | "negative" | "neutral";
};
type NewsAggregate = {
  POSITIVE: number;
  NEGATIVE: number;
  NEUTRAL: number;
  positive_ratio: number;
  negative_ratio: number;
  neutral_ratio: number;
};
type NewsBlock = {
  query: string;
  news_count: number;
  aggregate: NewsAggregate;
  news_sentiment_score: number;
  sentiment_volatility?: number;
  recency_weight_mean?: number;
  items: NewsItem[];
};
type NewsResp = { results: NewsBlock[] };
type NonFinResult = { company: string; score: { final_score: number } };
type NonFinResp = { results: NonFinResult[] };

/* ------------------------------------------------------------------
  (B) 신용등급 스케일 + 3분 버킷 차트 유틸
------------------------------------------------------------------- */
const RATING_ORDER = [
  "AAA","AA+","AA","AA-",
  "A+","A","A-",
  "BBB+","BBB","BBB-",
  "BB+","BB","BB-",
  "B+","B","B-",
  "CCC","CC","C","D",
] as const;
type RatingLetter = (typeof RATING_ORDER)[number];
const ratingToIndex = (r: string) => RATING_ORDER.indexOf(r as RatingLetter);
const indexToRating = (i: number) => RATING_ORDER[i] ?? "";

const floorToNMinutes = (d: Date, n = 3) => {
  const t = new Date(d);
  t.setSeconds(0, 0);
  t.setMinutes(Math.floor(t.getMinutes() / n) * n);
  return t;
};
const formatKoDateTime = (ts: number) =>
  new Date(ts).toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
const WINDOW_MS = 1000 * 60 * 60 * 24 * 30 * 6;

/* ------------------------------------------------------------------
  (C) 컴포넌트
------------------------------------------------------------------- */
interface CompanyAnalysisProps {
  companyName: string;
  onBack: () => void;
  onHome: () => void;
  onViewNotificationDetail: () => void;
}

export function CompanyAnalysis({
  companyName,
  onBack,
  onHome,
  onViewNotificationDetail,
}: CompanyAnalysisProps) {
  const [activeTab, setActiveTab] = useState("financial");
  const [selectedYear, setSelectedYear] = useState("2024"); // UI 유지(백엔드 오면 disabled)

  // ── 신용등급 추이(3분 버킷)
  type CreditPoint = { time: number; score: number; label: string };
  const [aciRating, setAciRating] = useState<string>("AA");
  const [ratingDirection, setRatingDirection] =
    useState<"상향" | "하향" | "유지">("유지");
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [creditData, setCreditData] = useState<CreditPoint[]>([]);
  const [lastChangeText, setLastChangeText] = useState<string>("");

  useEffect(() => {
    if (!aciRating || !lastUpdated) return;

    const idx = ratingToIndex(aciRating);
    if (idx < 0) return;

    const bucket = floorToNMinutes(lastUpdated, 3).getTime();

    setCreditData((prev) => {
      const prevLast = prev.length ? prev[prev.length - 1] : undefined;
      const prevIdx = prevLast?.score ?? idx;
      const prevLabel = prevLast?.label;

      const dir: "상향" | "하향" | "유지" =
        idx < prevIdx ? "상향" : idx > prevIdx ? "하향" : "유지";
      setRatingDirection(dir);

      if (prevLabel && prevLabel !== aciRating) {
        setLastChangeText(`${prevLabel} → ${aciRating}`);
      } else if (!prevLabel) {
        setLastChangeText("");
      }

      const existsAt = prev.findIndex((p) => p.time === bucket);
      const point: CreditPoint = { time: bucket, score: idx, label: aciRating };

      let next =
        existsAt >= 0
          ? prev.map((p, i) => (i === existsAt ? point : p))
          : [...prev, point].sort((a, b) => a.time - b.time);

      // 최근 6개월만 유지
      const cutoff = Date.now() - WINDOW_MS;
      next = next.filter((p) => p.time >= cutoff);

      return next;
    });
  }, [aciRating, lastUpdated]);

  // ── 백엔드 연동 상태
  const [metricsRatios, setMetricsRatios] = useState<YearRatios | null>(null);
  const [metricsLoading, setMetricsLoading] = useState<boolean>(false);
  const [publicRating, setPublicRating] = useState<string>("-");
  const [newsBlock, setNewsBlock] = useState<NewsBlock | null>(null);
  const [bizTextScore, setBizTextScore] = useState<number | null>(null);

  // 1) metrics
  const loadRatiosFromMetrics = async (targetName: string) => {
    setMetricsLoading(true);
    try {
      const url = `${API_BASE}/metrics?codes=${encodeURIComponent(
        targetName
      )}&all_periods=false&percent_format=false&search_mode=auto`;
      const { data } = await axios.get<MetricsResp>(url);
      const row = data?.data?.[0];
      if (row) {
        setMetricsRatios({
          debtRatio: toPercentage(row.debt_ratio),
          roa: toPercentage(row.roa),
          assetGrowthRate: toPercentage(row.total_asset_growth_rate),
          cfoToDebt: toPercentage(row.cfo_to_total_debt),
          currentRatio: toPercentage(row.current_ratio),
          quickRatio: toPercentage(row.quick_ratio),
        });
      } else {
        setMetricsRatios(null);
      }
    } catch {
      setMetricsRatios(null);
    } finally {
      setMetricsLoading(false);
    }
  };

  // 2) 공개 신용등급
  const loadPublicCredit = async (targetName: string) => {
    try {
      const url = `${API_BASE}/credit`;
      const { data } = await axios.post<CreditResp>(url, {
        queries: [targetName],
      });
      const rating = data?.ratings?.[targetName] || "-";
      setPublicRating(rating);
    } catch {
      setPublicRating("-");
    }
  };

  // 3) 뉴스
  const loadNews = async (targetName: string) => {
    try {
      const url = `${API_BASE}/news/sentiment?codes=${encodeURIComponent(
        targetName
      )}&limit=20&days=3`;
    const { data } = await axios.get<NewsResp>(url);
      const blk = data?.results?.[0];
      setNewsBlock(blk || null);
    } catch {
      setNewsBlock(null);
    }
  };

  // 4) 비재무
  const loadNonFinancial = async (targetName: string) => {
    try {
      const url = `${API_BASE}/nonfinancial?company=${encodeURIComponent(
        targetName
      )}&include_score=true`;
      const { data } = await axios.get<NonFinResp>(url);
      const score = data?.results?.[0]?.score?.final_score;
      setBizTextScore(typeof score === "number" ? score : null);
    } catch {
      setBizTextScore(null);
    }
  };

  // 회사 변경 시 4종 데이터 로딩
  useEffect(() => {
    if (!companyName) return;
    loadRatiosFromMetrics(companyName);
    loadPublicCredit(companyName);
    loadNews(companyName);
    loadNonFinancial(companyName);
  }, [companyName]);

  // CSV 저장(+분석 호출) 준비 상태
  const allReady =
    !!metricsRatios &&
    publicRating !== "-" &&
    newsBlock !== null &&
    bizTextScore !== null;

  // 특징 CSV 저장 후 ACI 분석 호출
  const parsePct = (s: string) =>
    typeof s === "string" && s.endsWith("%")
      ? Number(s.replace("%", "")) / 100
      : s === "-"
      ? null
      : Number(s);

  const saveFeaturesCsv = async () => {
    const displayRatios: YearRatios =
      metricsRatios ??
      ({
        debtRatio: "-",
        currentRatio: "-",
        quickRatio: "-",
        roa: "-",
        assetGrowthRate: "-",
        cfoToDebt: "-",
      } as YearRatios);

    const payload = {
      company: companyName,
      debt_ratio: parsePct(displayRatios.debtRatio),
      roa: parsePct(displayRatios.roa),
      total_asset_growth_rate: parsePct(displayRatios.assetGrowthRate),
      cfo_to_total_debt: parsePct(displayRatios.cfoToDebt),
      current_ratio: parsePct(displayRatios.currentRatio),
      quick_ratio: parsePct(displayRatios.quickRatio),
      news_sentiment_score: newsBlock?.news_sentiment_score ?? null,
      news_count: newsBlock?.news_count ?? null,
      sentiment_volatility: (newsBlock as any)?.sentiment_volatility ?? null,
      positive_ratio: newsBlock?.aggregate?.positive_ratio ?? null,
      negative_ratio: newsBlock?.aggregate?.negative_ratio ?? null,
      recency_weight_mean: (newsBlock as any)?.recency_weight_mean ?? null,
      business_report_text_score: bizTextScore,
      public_credit_rating: publicRating || null,
    };

    try {
      await axios.post(`${API_BASE.replace(/\/$/, "")}/comp_features`, payload, {
        headers: { "Content-Type": "application/json" },
      });
      return true;
    } catch {
      return false;
    }
  };

  // 분석 호출 (/analyze)
  const fetchAci = async () => {
    if (!companyName) return;
    try {
      const res = await axios.post(`${API_BASE}/analyze`, {
        company_name: companyName,
      });
      const next = String(res?.data?.predicted_grade ?? "");
      if (next) {
        setAciRating(next);
        setLastUpdated(new Date());
      }
    } catch {
      // 무시
    }
  };

  // 4종 준비되면 한 번 저장 → 분석
  const [savedKey, setSavedKey] = useState<string>("");
  useEffect(() => {
    (async () => {
      if (!companyName || !allReady) return;

      const key = JSON.stringify({
        c: companyName,
        m: metricsRatios,
        r: publicRating,
        n: newsBlock?.news_sentiment_score ?? null,
        b: bizTextScore,
      });
      if (savedKey === key) return;

      const ok = await saveFeaturesCsv();
      if (ok) {
        setSavedKey(key);
        await fetchAci();
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyName, allReady]);

  // 3분 폴링(예측 재호출) — 추이 그래프에만 반영
  useEffect(() => {
    const id = setInterval(fetchAci, 180000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyName]);

  // 화면 표시용 재무지표(백엔드가 오면 우선 사용)
  const displayRatios: YearRatios =
    metricsRatios ??
    ({
      debtRatio: "-",
      currentRatio: "-",
      quickRatio: "-",
      roa: "-",
      assetGrowthRate: "-",
      cfoToDebt: "-",
    } as YearRatios);

  const getSentimentBadge = (sentiment?: string) =>
    sentiment === "positive" ? (
      <Badge className="bg-green-50 text-green-700 border-green-200">긍정</Badge>
    ) : sentiment === "negative" ? (
      <Badge className="bg-red-50 text-red-700 border-red-200">부정</Badge>
    ) : sentiment === "neutral" ? (
      <Badge className="bg-slate-100 text-slate-700 border-slate-200">중립</Badge>
    ) : null;

  /* --------------------------- UI (기존 구조 유지) --------------------------- */
  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
            {/* Kiwoom Logo */}
            <div className="flex items-center gap-2">
              <div className="w-10 h-10 flex items-center justify-center">
                <img
                  src={kiwoomLogo}
                  alt="Kiwoom Logo"
                  className="w-full h-full object-contain"
                />
              </div>
              <span className="text-slate-700">키움은행</span>
            </div>

            {/* Divider */}
            <div className="h-8 w-px bg-slate-300"></div>

            {/* ACI Logo */}
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#7C1D2E] to-[#6A1528] flex items-center justify-center">
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

      {/* Company Info Header */}
      <div className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <div className="flex items-center justify-between mb-6 bg-white">
            <h1 className="text-slate-900 text-xl font-semibold">{companyName}</h1>

            <Button
              onClick={() => {
                const key = "managed_companies";
                const raw = localStorage.getItem(key);
                const list = raw ? JSON.parse(raw) : [];
                if (!list.includes(companyName)) {
                  list.push(companyName);
                  localStorage.setItem(key, JSON.stringify(list));
                  window.dispatchEvent(
                    new CustomEvent("managed-companies-updated", {
                      detail: { name: companyName },
                    })
                  );
                }
              }}
              className="bg-[#7C1D2E] text-white px-4 py-2 rounded-md hover:bg-[#6a1324] transition"
            >
              관리 기업 목록에 추가
            </Button>
          </div>


          {/* Credit Ratings - 공개신용등급과 ACI등급 구분 */}
          <div className="grid grid-cols-2 gap-6">
            {/* ACI 자체 등급 (핵심 지표) */}
            <Card className="border-2 border-[#7C1D2E] shadow-lg bg-gradient-to-br from-[#7C1D2E]/5 to-white">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2">
                  <span className="text-[#7C1D2E]">⭐ ACI 신용등급</span>
                  <Badge className="bg-[#7C1D2E] text-white">핵심 지표</Badge>
                </CardTitle>
                <p className="text-slate-600 mt-1">AI 기반 실시간 분석 등급</p>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      {/* ▶ 가독성 개선: 공개 등급과 동일한 형태의 뱃지로 통일 */}
                      <Badge
                        variant="outline"
                        className="px-4 py-2 bg-slate-100 text-slate-900 border-slate-300"
                      >
                        {aciRating}
                      </Badge>
                      <div
                        className={
                          "flex items-center gap-2 " +
                          (ratingDirection === "상향"
                            ? "text-green-600"
                            : ratingDirection === "하향"
                            ? "text-red-600"
                            : "text-slate-600")
                        }
                      >
                        {ratingDirection === "상향" && (
                          <TrendingUp className="w-5 h-5" />
                        )}
                        {ratingDirection === "하향" && (
                          <TrendingDown className="w-5 h-5" />
                        )}
                        <span>
                          {ratingDirection === "유지" ? "유지" : ratingDirection}
                        </span>
                      </div>
                    </div>
                    <p className="text-slate-600">
                      최근 변동: {lastChangeText || "변동 없음"}
                    </p>
                  </div>
                  <div>
                    <Button
                      onClick={onViewNotificationDetail}
                      variant="outline"
                      className="border-[#7C1D2E] text-[#7C1D2E] hover:bg-[#7C1D2E]/10"
                    >
                      신용등급 지표확인
                    </Button>
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
                <p className="text-slate-600 mt-1">nice신용평가 등급</p>
              </CardHeader>
              <CardContent>
                <div>
                  <div className="flex items-center gap-3 mb-2">
                    <Badge
                      variant="outline"
                      className="px-4 py-2 bg-slate-100 text-slate-900 border-slate-300"
                    >
                      {publicRating}
                    </Badge>
                  </div>
                  <p className="text-slate-600">평가사: nice신용평가</p>
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
                보수적인 기준으로 평가된 공식 등급입니다.
              </p>
              <p className="text-slate-700 leading-relaxed mt-2">
                ACI 등급의 변화는 위험 조기 경보 신호로 활용하실 수 있습니다.
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
              ACI 신용등급 추이
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
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <CardTitle>투자 지표</CardTitle>
                    <p className="text-slate-600 mt-2">
                      {metricsLoading ? "지표 불러오는 중…" : "주요 재무 비율 분석"}
                    </p>
                  </div>
                  <Select
                    value={selectedYear}
                    onValueChange={setSelectedYear}
                    disabled={!!metricsRatios}
                  >
                    <SelectTrigger className="w-[180px] bg-blue-900 text-white hover:bg-blue-800 border-blue-900 disabled:opacity-60 disabled:cursor-not-allowed">
                      <SelectValue placeholder="연도 선택" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="2024">2024년</SelectItem>
                      <SelectItem value="2023">2023년</SelectItem>
                      <SelectItem value="2022">2022년</SelectItem>
                      <SelectItem value="2021">2021년</SelectItem>
                      <SelectItem value="2020">2020년</SelectItem>
                      <SelectItem value="2019">2019년</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-3 gap-4 mb-8">
                  <div className="bg-slate-50 rounded-lg p-6 border border-slate-200">
                    <div className="text-slate-600 mb-3">부채비율</div>
                    <div className="text-slate-900">{displayRatios.debtRatio}</div>
                  </div>
                  <div className="bg-slate-50 rounded-lg p-6 border border-slate-200">
                    <div className="text-slate-600 mb-3">유동비율</div>
                    <div className="text-slate-900">{displayRatios.currentRatio}</div>
                  </div>
                  <div className="bg-slate-50 rounded-lg p-6 border border-slate-200">
                    <div className="text-slate-600 mb-3">당좌비율</div>
                    <div className="text-slate-900">{displayRatios.quickRatio}</div>
                  </div>
                  <div className="bg-slate-50 rounded-lg p-6 border border-slate-200">
                    <div className="text-slate-600 mb-3">총자산이익률</div>
                    <div className="text-slate-900">{displayRatios.roa}</div>
                  </div>
                  <div className="bg-slate-50 rounded-lg p-6 border border-slate-200">
                    <div className="text-slate-600 mb-3">총자산증가율</div>
                    <div className="text-slate-900">
                      {displayRatios.assetGrowthRate}
                    </div>
                  </div>
                  <div className="bg-slate-50 rounded-lg p-6 border border-slate-200">
                    <div className="text-slate-600 mb-3">
                      영업활동현금흐름대비 총부채비율
                    </div>
                    <div className="text-slate-900">{displayRatios.cfoToDebt}</div>
                  </div>
                </div>

                <div className="p-5 bg-slate-50 rounded-lg border border-slate-200">
                  <h4 className="text-slate-900 mb-4">지표 설명</h4>
                  <div className="grid gap-3 text-slate-700">
                    <div className="flex gap-3">
                      <span className="text-blue-900 shrink-0">•</span>
                      <div>
                        <strong>부채비율</strong>: 자기자본 대비 부채의 비율 (총부채 ÷ 자기자본 ×
                        100).
                      </div>
                    </div>
                    <div className="flex gap-3">
                      <span className="text-blue-900 shrink-0">•</span>
                      <div>
                        <strong>유동비율</strong>: 유동부채 대비 유동자산의 비율.
                      </div>
                    </div>
                    <div className="flex gap-3">
                      <span className="text-blue-900 shrink-0">•</span>
                      <div>
                        <strong>당좌비율</strong>: 유동부채 대비 당좌자산의 비율.
                      </div>
                    </div>
                    <div className="flex gap-3">
                      <span className="text-blue-900 shrink-0">•</span>
                      <div>
                        <strong>총자산이익률(ROA)</strong>: 총자산 대비 당기순이익의 비율.
                      </div>
                    </div>
                    <div className="flex gap-3">
                      <span className="text-blue-900 shrink-0">•</span>
                      <div>
                        <strong>총자산증가율</strong>: 전년 대비 총자산의 증가율.
                      </div>
                    </div>
                    <div className="flex gap-3">
                      <span className="text-blue-900 shrink-0">•</span>
                      <div>
                        <strong>영업활동현금흐름대비 총부채비율</strong>: 영업현금흐름 대비 총부채의
                        비율.
                      </div>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ACI 신용등급 추이 탭 (이 탭에서만 그래프 표시) */}
          <TabsContent value="stock">
            <Card>
              <CardHeader>
                <CardTitle>3분 간격 ACI 신용등급 추이</CardTitle>
                <p className="text-slate-600 mt-2">단위: 등급 (상단이 우수)</p>
              </CardHeader>

              <CardContent>
                <ResponsiveContainer width="100%" height={400}>
                  <LineChart data={creditData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis
                      dataKey="time"
                      type="number"
                      domain={["dataMin", "dataMax"]}
                      tick={{ fill: "#64748b" }}
                      tickMargin={8}
                      tickFormatter={(ts) => formatKoDateTime(Number(ts))}
                      allowDataOverflow
                    />
                    <YAxis type="number" domain={[RATING_ORDER.length - 1, 0]} hide />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#ffffff",
                        border: "1px solid #e2e8f0",
                        borderRadius: "8px",
                      }}
                      labelFormatter={(ts) => `시각: ${formatKoDateTime(Number(ts))}`}
                      formatter={(val: number) => [indexToRating(Number(val)), "등급"]}
                    />
                    <Line
                      type="stepAfter"
                      dataKey="score"
                      stroke="#1e3a8a"
                      strokeWidth={3}
                      dot={{ r: 3 }}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>

                {/* 요약 카드: 2개 (현재등급, 등급 변화) */}
                <div className="grid grid-cols-2 gap-4 mt-6">
                  <Card className="bg-slate-50">
                    <CardContent className="pt-4 pb-4">
                      <div className="text-slate-600 mb-1">현재등급</div>
                      <div className="text-slate-900">
                        {/* ▶ 가독성 개선된 뱃지 스타일 적용 */}
                        <Badge
                          variant="outline"
                          className="px-3 py-1 bg-slate-100 text-slate-900 border-slate-300"
                        >
                          {aciRating ?? "-"}
                        </Badge>
                      </div>
                    </CardContent>
                  </Card>

                  <Card
                    className={
                      ratingDirection === "하향"
                        ? "bg-red-50"
                        : ratingDirection === "상향"
                        ? "bg-green-50"
                        : "bg-slate-50"
                    }
                  >
                    <CardContent className="pt-4 pb-4">
                      <div
                        className={
                          ratingDirection === "하향"
                            ? "text-red-600 mb-1"
                            : ratingDirection === "상향"
                            ? "text-green-600 mb-1"
                            : "text-slate-600 mb-1"
                        }
                      >
                        등급 변화
                      </div>
                      <div
                        className={
                          "flex items-center gap-2 " +
                          (ratingDirection === "하향"
                            ? "text-red-700"
                            : ratingDirection === "상향"
                            ? "text-green-700"
                            : "text-slate-700")
                        }
                      >
                        {ratingDirection === "상향" && (
                          <TrendingUp className="w-4 h-4" />
                        )}
                        {ratingDirection === "하향" && (
                          <TrendingDown className="w-4 h-4" />
                        )}
                        <span className="text-slate-900">
                          {ratingDirection === "상향"
                            ? "등급상승"
                            : ratingDirection === "하향"
                            ? "등급하락"
                            : "등급유지"}
                        </span>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* 뉴스 탭 — 그래프 제거, 제목만 하이퍼링크 유지, URL 텍스트는 절대 노출 X */}
         <TabsContent value="news">
          <Card>
            <CardHeader>
              <CardTitle>최근 관련 뉴스</CardTitle>
              <p className="text-slate-600 mt-2">AI 기반 감성 분석 결과 포함</p>
            </CardHeader>
            <CardContent>
              {/* 요약 카드 (있을 때만) */}
              {newsBlock && (
                <Card className="mb-6 bg-slate-50 border-slate-300">
                  <CardContent className="pt-5 pb-5 px-6">
                    <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                      <div>
                        <h4 className="text-slate-900 mb-1">뉴스 감성 분석 요약</h4>
                        <div className="text-slate-700">
                          기업명: {newsBlock?.query ?? "-"}
                        </div>
                      </div>
                      <div className="grid grid-cols-3 gap-4">
                        <div className="text-center">
                          <div className="text-slate-600 mb-1">전체 뉴스</div>
                          <div className="text-slate-900">{newsBlock.news_count}건</div>
                        </div>
                        <div className="text-center">
                          <div className="text-green-600 mb-1">긍정</div>
                          <div className="text-green-900">
                            {Math.round(
                              (newsBlock.aggregate?.positive_ratio || 0) *
                                (newsBlock.news_count || 0)
                            )}
                            건 ({toPercentage(newsBlock.aggregate?.positive_ratio)})
                          </div>
                        </div>
                        <div className="text-center">
                          <div className="text-red-600 mb-1">부정</div>
                          <div className="text-red-900">
                            {Math.round(
                              (newsBlock.aggregate?.negative_ratio || 0) *
                                (newsBlock.news_count || 0)
                            )}
                            건 ({toPercentage(newsBlock.aggregate?.negative_ratio)})
                          </div>
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* 뉴스 리스트 — 제목(링크) + 날짜만 */}
              <div className="space-y-4">
                {!newsBlock && (
                  <div className="text-slate-600">표시할 뉴스가 없습니다.</div>
                )}

                {newsBlock?.items?.map((news, index) => (
                  <Card key={index} className="hover:shadow-md transition-shadow">
                    <CardContent className="pt-5 pb-5 px-6">
                      {/* 제목: 하이퍼링크 유지 */}
                      <a
                        href={news.link}
                        target="_blank"
                        rel="noreferrer"
                        className="text-slate-900 flex-1 hover:underline block mb-2"
                      >
                        {news.title}
                      </a>

                      {/* 날짜만 표시 */}
                      <div className="text-right text-slate-600 text-sm">
                        {news.published_at}
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}