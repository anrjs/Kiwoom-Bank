// NotificationDetail.tsx
import { useEffect, useState } from "react";
import axios from "axios";
import { ArrowLeft, Home, TrendingDown, TrendingUp, AlertTriangle, Loader2 } from "lucide-react"; // ❗️ Loader2 추가
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import kiwoomLogo from "figma:asset/7edd7880e1ed1575f3f3496ccc95c4ca1ab02475.png";
import type { Notification } from "./NotificationInbox"; // ❗️ Notification 타입 import

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const POLL_MS = 30 * 1000; // ❗️ 상세 페이지는 30초마다 새로고침

// ❗️ [수정] props 인터페이스 정의
interface NotificationDetailProps {
  notification: Notification | undefined; // App.tsx에서 전달받음
  onBack: () => void;
  onHome: () => void;
  onViewAnalysis: () => void; // (이 prop은 현재 사용되지 않음)
}

export function NotificationDetail({ 
  notification, 
  onBack, 
  onHome 
}: NotificationDetailProps) {
  
  // ❗️ [수정] prevGrade 제거, currentGrade만 관리
  const [currentGrade, setCurrentGrade] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const selectedCompany = notification?.companyName; // 알림 객체에서 회사 이름 추출

  // ❗️ [수정] 30초마다 현재 등급을 폴링하는 useEffect
  useEffect(() => {
    if (!selectedCompany) {
      setLoading(false);
      return;
    }

    let isMounted = true;
    
    const fetchGrade = () => {
      axios.post(`${API_BASE}/analyze`, { company_name: selectedCompany })
        .then(res => {
          if (isMounted) {
            const grade = res.data?.predicted_grade || null;
            setCurrentGrade(grade);
          }
        })
        .catch(err => console.error(`[Detail] ${selectedCompany} 등급 조회 실패:`, err))
        .finally(() => {
          if (isMounted) setLoading(false);
        });
    };

    setLoading(true);
    fetchGrade(); // 즉시 1회 실행
    
    const timer = setInterval(fetchGrade, POLL_MS); // 30초마다 폴링

    return () => {
      isMounted = false;
      clearInterval(timer); // 컴포넌트 언마운트 시 타이머 정리
    };
  }, [selectedCompany]); // selectedCompany가 바뀔 때마다 폴링 재시작

  // ❗️ [수정] 등급 비교 로직 (현재 등급 vs 알림 당시 등급)
  const originalRating = notification?.ratingChange?.split("→")[1]?.trim() || notification?.ratingChange;
  const isDown = notification?.type === "down";
  const isUp = notification?.type === "up";
  
  // 현재 등급과 알림 당시 등급이 다른지
  const hasChangedAgain = currentGrade && originalRating && currentGrade !== originalRating;

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header (유지) */}
      <header className="bg-white border-b border-slate-200 shadow-sm">
        {/* ... (기존 UI와 동일) ... */}
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
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
          <div className="flex gap-2">
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

      {/* Content (❗️ [수정] UI 로직 변경) */}
      <div className="max-w-5xl mx-auto px-6 py-8">
        <h1 className="text-slate-900 mb-6">
          {selectedCompany || "알림 없음"} 등급 상세 분석
        </h1>

        {/* 등급 변화 시각화 */}
        <div className="flex items-center gap-4 mb-6">
          <Card className="p-4 flex-1">
            <div className="text-slate-500 text-sm mb-1">알림 당시 등급</div>
            <div className={`text-3xl ${isDown ? 'text-red-600' : isUp ? 'text-green-600' : 'text-slate-900'}`}>
              {originalRating || "-"}
            </div>
            <div className="text-slate-500 text-sm mt-1">{notification?.ratingChange || "N/A"}</div>
          </Card>
          
          <div className="flex flex-col items-center">
            {loading ? (
              <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
            ) : hasChangedAgain ? (
              <AlertTriangle className="w-6 h-6 text-yellow-500" />
            ) : (
              <TrendingDown className="w-6 h-6 text-slate-400 -rotate-90" />
            )}
          </div>

          <Card className="p-4 flex-1 bg-blue-50 border-blue-200">
            <div className="text-blue-700 text-sm mb-1">현재 실시간 등급</div>
            <div className={`text-3xl text-blue-900 ${loading ? 'animate-pulse' : ''}`}>
              {loading ? "..." : (currentGrade || "-")}
            </div>
            <div className={`text-blue-600 text-sm mt-1 ${hasChangedAgain ? 'font-bold' : ''}`}>
              {hasChangedAgain ? "추가 변동 감지" : "등급 유지 중"}
            </div>
          </Card>
        </div>

        <Card className="border-slate-300">
          <CardHeader>
            <CardTitle className="text-slate-900 flex items-center gap-2">
              {isDown ? <TrendingDown className="w-5 h-5 text-red-600" /> : isUp ? <TrendingUp className="w-5 h-5 text-green-600" /> : <AlertTriangle className="w-5 h-5 text-yellow-600" />}
              알림 상세 내역
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <p className="text-slate-500">불러오는 중...</p>
            ) : notification ? (
              <div className="space-y-3">
                 <p className="text-xl text-slate-800">
                  {notification.title}
                </p>
                <p className="text-slate-600">
                  <span className="font-semibold">감지 시각:</span> {notification.timestamp}
                </p>
                 <p className="text-slate-600">
                  <span className="font-semibold">주요 키워드:</span> {notification.newsKeywords}
                </p>
              </div>
            ) : (
              <p className="text-slate-500">알림 정보를 불러올 수 없습니다.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}